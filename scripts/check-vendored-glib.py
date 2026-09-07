#!/usr/bin/env python3
"""Verify the exact upstream GLib archive and reviewed safety backport."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def validate_patch(root: Path = ROOT) -> list[str]:
    """Reject modified, incomplete or disconnected copies of the backport."""
    try:
        provenance = json.loads((root / "vendor/glib-provenance.json").read_text())
        workspace = tomllib.loads((root / "Cargo.toml").read_text())
        lockfile = tomllib.loads((root / "Cargo.lock").read_text())
        package_root = root / "vendor/glib"
        package = tomllib.loads((package_root / "Cargo.toml").read_text())
        expected = provenance["upstream_files"] | provenance["patched_files"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"Cannot read GLib patch provenance: {exc}"]

    failures: list[str] = []
    locked = [package for package in lockfile["package"] if package["name"] == "glib"]
    if len(locked) != 1 or locked[0].get("source") or locked[0]["version"] != "0.18.5":
        failures.append(
            "The lockfile must resolve GLib to the reviewed local 0.18.5 crate"
        )
    if workspace.get("patch", {}).get("crates-io", {}).get("glib") != {
        "path": "vendor/glib"
    }:
        failures.append("The workspace must use the reviewed local GLib patch")
    if (
        package["package"]["name"] != "glib"
        or package["package"]["version"] != "0.18.5"
    ):
        failures.append("The GLib patch package identity changed")
    actual = {
        path.relative_to(package_root).as_posix(): path
        for path in package_root.rglob("*")
        if path.is_file()
        and "target" not in path.relative_to(package_root).parts
        and path.name != "Cargo.lock"
    }
    for relative in sorted(set(actual) | set(expected)):
        path = actual.get(relative)
        if path is None:
            failures.append(f"Missing GLib source: {relative}")
        elif relative not in expected:
            failures.append(f"Unexpected GLib source: {relative}")
        elif (
            path.is_symlink()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected[relative]
        ):
            failures.append(f"GLib source checksum mismatch: {relative}")
    return failures


def main() -> int:
    failures = validate_patch()
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("Verified the GLib 0.18.5 upstream archive and VariantStrIter safety patch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
