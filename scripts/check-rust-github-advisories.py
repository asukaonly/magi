#!/usr/bin/env python3
"""Match Cargo packages against the public GitHub advisory dump locally."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import tomllib
from typing import Any
from urllib.request import urlopen
import zipfile

from semantic_version import Version

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = "https://storage.googleapis.com/osv-vulnerabilities/crates.io/all.zip"
MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_RECORD_BYTES = 2 * 1024 * 1024
GLIB_BACKPORT = ("GHSA-wrw7-89jp-8q8g", "glib", "0.18.5")


def semver(value: str) -> Version:
    """Compare SemVer precedence without build metadata."""
    core, separator, prerelease = value.split("+", maxsplit=1)[0].partition("-")
    parts = core.split(".")
    # Some GitHub records abbreviate a release boundary as 0.20 or 1.
    if len(parts) < 3 and all(part.isdecimal() for part in parts):
        core = ".".join(parts + ["0"] * (3 - len(parts)))
    return Version(core + separator + prerelease)


def affected_version(version: str, affected: dict[str, Any]) -> bool:
    """Evaluate OSV SemVer intervals, including inclusive last-affected ends."""
    target = semver(version)
    if any(target == semver(item) for item in affected.get("versions", [])):
        return True
    matched = False
    ranges = affected.get("ranges", [])
    if not ranges and "versions" not in affected:
        raise ValueError("An affected package has no version information")
    for interval in ranges:
        if interval["type"] != "SEMVER":
            raise ValueError(f"Unsupported advisory range type: {interval['type']}")
        opened = False
        lower: Version | None = None
        events = interval["events"]
        if not events:
            raise ValueError("Empty advisory version interval")
        for event in events:
            if not isinstance(event, dict) or len(event) != 1:
                raise ValueError("Malformed advisory version event")
            kind, value = next(iter(event.items()))
            if kind == "introduced":
                if opened:
                    raise ValueError("An advisory interval was opened twice")
                lower = None if value == "0" else semver(value)
                opened = True
            elif kind in {"fixed", "last_affected", "limit"}:
                if not opened:
                    raise ValueError("An advisory interval has no introduction")
                upper = semver(value)
                if lower is not None and upper < lower:
                    raise ValueError("Reversed advisory version interval")
                within_end = (
                    target <= upper if kind == "last_affected" else target < upper
                )
                matched |= (lower is None or target >= lower) and within_end
                opened = False
            else:
                raise ValueError(f"Unsupported advisory event: {kind}")
        matched |= opened and (lower is None or target >= lower)
    return matched


def read_advisories(data: bytes) -> list[dict[str, Any]]:
    """Read reviewed GitHub records without extracting the downloaded archive."""
    records: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            if not entry.filename.startswith("GHSA-") or not entry.filename.endswith(
                ".json"
            ):
                continue
            if entry.file_size > MAX_RECORD_BYTES:
                raise ValueError("An advisory record exceeds the size limit")
            record = json.loads(archive.read(entry))
            if not isinstance(record, dict) or record.get("id") != entry.filename[:-5]:
                raise ValueError("Malformed GitHub advisory record")
            if record.get("withdrawn"):
                continue
            if not isinstance(record.get("affected"), list):
                raise ValueError("Missing affected packages in a GitHub advisory")
            records.append(record)
    if not records:
        raise ValueError("The database contains no GitHub advisory records")
    return records


def find_advisories(
    packages: list[dict[str, Any]], records: list[dict[str, Any]]
) -> set[tuple[str, str, str]]:
    """Check registry packages and the known vendored third-party crate."""
    versions: dict[str, set[str]] = {}
    for package in packages:
        # The backport must still be checked for every other GLib advisory.
        # No package names or versions leave this process.
        if (
            package.get("source", "").startswith("registry+")
            or (package["name"] == "glib" and not package.get("source"))
        ):
            versions.setdefault(package["name"], set()).add(package["version"])
        elif package.get("source"):
            raise ValueError(
                f"Non-registry dependency needs explicit audit coverage: {package['name']}"
            )
    if not versions:
        raise ValueError("The lockfile contains no registry packages to audit")
    findings: set[tuple[str, str, str]] = set()
    for record in records:
        for affected in record["affected"]:
            package = affected["package"]
            if package["ecosystem"] != "crates.io":
                continue
            for version in versions.get(package["name"], set()):
                try:
                    matches = affected_version(version, affected)
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(
                        f"{record['id']} ({package['name']}): {exc}"
                    ) from exc
                if matches:
                    findings.add((record["id"], package["name"], version))
    return findings


def download_database() -> bytes:
    """Download the same public Rust dump for every repository, without a payload."""
    with urlopen(DATABASE_URL, timeout=45) as response:
        data = response.read(MAX_DATABASE_BYTES + 1)
    if len(data) > MAX_DATABASE_BYTES:
        raise ValueError("The advisory database exceeds the size limit")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path, help="Use a previously downloaded public dump"
    )
    parser.add_argument("--lockfile", type=Path, default=ROOT / "Cargo.lock")
    args = parser.parse_args()
    # A local version-only exception is valid only with the actual source fix.
    if subprocess.run(
        [sys.executable, str(ROOT / "scripts/check-vendored-glib.py")], check=False
    ).returncode:
        return 1
    try:
        data = args.database.read_bytes() if args.database else download_database()
        if len(data) > MAX_DATABASE_BYTES:
            raise ValueError("The advisory database exceeds the size limit")
        records = read_advisories(data)
        packages = tomllib.loads(args.lockfile.read_text())["package"]
        findings = find_advisories(packages, records)
        if any(
            package["name"] == "glib"
            and package["version"] == "0.18.5"
            and not package.get("source")
            for package in packages
        ):
            findings.discard(GLIB_BACKPORT)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        zipfile.BadZipFile,
    ) as exc:
        print(f"GitHub advisory scan failed: {exc}", file=sys.stderr)
        return 1
    if findings:
        for advisory, package, version in sorted(findings):
            print(
                f"{package} {version}: https://github.com/advisories/{advisory}",
                file=sys.stderr,
            )
        return 1
    print(
        f"GitHub advisory scan passed against {len(records)} public records; dependency matching stayed local"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
