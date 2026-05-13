#!/usr/bin/env python3
"""Sync and validate repository release version metadata."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / "VERSION"
CARGO_LOCK = REPO_ROOT / "Cargo.lock"
FRONTEND_PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
FRONTEND_PACKAGE_LOCK = REPO_ROOT / "frontend" / "package-lock.json"
TAURI_CONFIG = REPO_ROOT / "frontend" / "src-tauri" / "tauri.conf.json"
TAURI_CARGO = REPO_ROOT / "frontend" / "src-tauri" / "Cargo.toml"
BACKEND_PYPROJECT = REPO_ROOT / "backend" / "pyproject.toml"


def _normalize_version(raw: str) -> str:
    value = raw.strip()
    if value.startswith("v"):
        value = value[1:]
    if not value:
        raise SystemExit("Version must not be empty.")
    return value


def _read_version_file() -> str:
    return _normalize_version(VERSION_FILE.read_text(encoding="utf-8"))


def _write_version_file(version: str) -> None:
    VERSION_FILE.write_text(f"{version}\n", encoding="utf-8")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _replace_first_version(path: Path, version: str) -> None:
    content = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'(?m)^version = "[^"]+"$',
        f'version = "{version}"',
        content,
        count=1,
    )
    if count != 1:
        raise SystemExit(f"Could not find a package version line in {path.relative_to(REPO_ROOT)}")
    path.write_text(updated, encoding="utf-8")


def _replace_cargo_lock_package_version(path: Path, package_name: str, version: str) -> None:
    content = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        rf'(?ms)(\[\[package\]\]\nname = "{re.escape(package_name)}"\nversion = ")([^"]+)(")',
        rf'\g<1>{version}\g<3>',
        content,
        count=1,
    )
    if count != 1:
        relative_path = path.relative_to(REPO_ROOT)
        raise SystemExit(f"Could not find package {package_name!r} in {relative_path}")
    path.write_text(updated, encoding="utf-8")


def sync_versions(version: str) -> None:
    _write_version_file(version)
    _replace_cargo_lock_package_version(CARGO_LOCK, "magi-desktop", version)

    package_json = _load_json(FRONTEND_PACKAGE_JSON)
    package_json["version"] = version
    _write_json(FRONTEND_PACKAGE_JSON, package_json)

    package_lock = _load_json(FRONTEND_PACKAGE_LOCK)
    package_lock["version"] = version
    packages = package_lock.setdefault("packages", {})
    root_package = packages.setdefault("", {})
    root_package["version"] = version
    _write_json(FRONTEND_PACKAGE_LOCK, package_lock)

    tauri_config = _load_json(TAURI_CONFIG)
    tauri_config["version"] = version
    _write_json(TAURI_CONFIG, tauri_config)

    _replace_first_version(TAURI_CARGO, version)
    _replace_first_version(BACKEND_PYPROJECT, version)


def collect_versions() -> dict[str, str]:
    cargo_lock = tomllib.loads(CARGO_LOCK.read_text(encoding="utf-8"))
    package_json = _load_json(FRONTEND_PACKAGE_JSON)
    package_lock = _load_json(FRONTEND_PACKAGE_LOCK)
    tauri_config = _load_json(TAURI_CONFIG)
    tauri_cargo = tomllib.loads(TAURI_CARGO.read_text(encoding="utf-8"))
    backend_pyproject = tomllib.loads(BACKEND_PYPROJECT.read_text(encoding="utf-8"))

    cargo_lock_version = next(
        (
            str(package["version"])
            for package in cargo_lock.get("package", [])
            if package.get("name") == "magi-desktop"
        ),
        None,
    )
    if cargo_lock_version is None:
        raise SystemExit("Could not find magi-desktop in Cargo.lock")

    return {
        "VERSION": _read_version_file(),
        "Cargo.lock magi-desktop": cargo_lock_version,
        "frontend/package.json": str(package_json["version"]),
        "frontend/package-lock.json": str(package_lock["version"]),
        "frontend/package-lock.json packages['']": str(package_lock["packages"][""]["version"]),
        "frontend/src-tauri/tauri.conf.json": str(tauri_config["version"]),
        "frontend/src-tauri/Cargo.toml": str(tauri_cargo["package"]["version"]),
        "backend/pyproject.toml": str(backend_pyproject["project"]["version"]),
    }


def validate_versions(expected_version: str) -> None:
    versions = collect_versions()
    mismatches = {
        path: found
        for path, found in versions.items()
        if found != expected_version
    }
    if mismatches:
        details = "\n".join(
            f"- {path}: expected {expected_version}, found {found}"
            for path, found in mismatches.items()
        )
        raise SystemExit(f"Release tag does not match version metadata:\n{details}")

    print(f"Validated release version {expected_version} across version metadata files.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", help="Sync all version metadata from a version string.")
    sync_parser.add_argument("version", nargs="?", help="Version to write. Defaults to the VERSION file.")

    validate_parser = subparsers.add_parser("validate", help="Validate that all version metadata matches the expected version.")
    validate_parser.add_argument("--tag", help="Release tag such as v0.1.3.")
    validate_parser.add_argument("--version", help="Expected version such as 0.1.3.")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "sync":
        version = _normalize_version(args.version) if args.version else _read_version_file()
        sync_versions(version)
        print(f"Synced version metadata to {version}.")
        return

    expected = args.version or args.tag or _read_version_file()
    validate_versions(_normalize_version(expected))


if __name__ == "__main__":
    main()