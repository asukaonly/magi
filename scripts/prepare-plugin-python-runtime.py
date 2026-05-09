#!/usr/bin/env python3
"""Prepare a relocatable Python runtime for packaged plugin dependency installs."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


REPOSITORIES = (
    "astral-sh/python-build-standalone",
    "indygreg/python-build-standalone",
)

TARGET_ALIASES = {
    "x86_64-apple-darwin": ("x86_64-apple-darwin",),
    "aarch64-apple-darwin": ("aarch64-apple-darwin",),
    "x86_64-pc-windows-msvc": ("x86_64-pc-windows-msvc",),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Tauri/Rust target triple")
    parser.add_argument(
        "--python-version",
        default=os.environ.get("MAGI_PLUGIN_PYTHON_VERSION", "3.13"),
        help="CPython major.minor or exact patch version to select from assets",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Directory where the runtime archive will be downloaded and extracted",
    )
    parser.add_argument(
        "--github-env",
        type=Path,
        help="Optional GitHub Actions env file to receive MAGI_PLUGIN_PYTHON_SOURCE",
    )
    parser.add_argument(
        "--asset-url",
        help="Optional explicit python-build-standalone archive URL",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and print the selected asset without downloading it",
    )
    return parser.parse_args()


def request_json(url: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "magi-release-runtime-preparer",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    request = urllib.request.Request(
        url,
        headers=headers,
    )
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == 3:
                break
            time.sleep(attempt * 2)
    raise last_error or RuntimeError(f"Failed to request {url}")


def python_version_pattern(python_version: str) -> str:
    parts = python_version.split(".")
    if len(parts) == 2:
        return rf"{re.escape(python_version)}\.\d+"
    return re.escape(python_version)


def asset_pattern(python_version: str, target: str) -> re.Pattern[str]:
    version_pattern = python_version_pattern(python_version)
    escaped_target = re.escape(target)
    return re.compile(
        rf"^cpython-{version_pattern}\+.*-{escaped_target}-"
        rf"(install_only_stripped|install_only)\.(tar\.gz|zip)$"
    )


def asset_priority(name: str) -> tuple[int, int, str]:
    stripped_rank = 0 if "install_only_stripped" in name else 1
    archive_rank = 0 if name.endswith(".tar.gz") else 1
    return (stripped_rank, archive_rank, name)


def find_asset_url(python_version: str, target: str) -> tuple[str, str, str]:
    aliases = TARGET_ALIASES.get(target)
    if aliases is None:
        raise SystemExit(f"Unsupported plugin Python target: {target}")

    checked: list[str] = []
    for repository in REPOSITORIES:
        release_batches: list[list[dict[str, Any]]] = []
        try:
            latest_release = request_json(
                f"https://api.github.com/repos/{repository}/releases/latest"
            )
            release_batches.append([latest_release])
        except (urllib.error.URLError, TimeoutError) as exc:
            checked.append(f"{repository} latest: {exc}")

        try:
            release_batches.append(
                request_json(
                    f"https://api.github.com/repos/{repository}/releases?per_page=5"
                )
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            checked.append(f"{repository} release list: {exc}")

        if not release_batches:
            continue

        for releases in release_batches:
            matches: list[tuple[tuple[int, int, str], str, str]] = []
            for release in releases:
                for asset in release.get("assets", []):
                    name = asset.get("name", "")
                    for alias in aliases:
                        if asset_pattern(python_version, alias).match(name):
                            matches.append(
                                (
                                    asset_priority(name),
                                    name,
                                    asset["browser_download_url"],
                                )
                            )

            if matches:
                _, name, url = sorted(matches, key=lambda item: item[0])[0]
                return repository, name, url

        checked.append(f"{repository}: no matching asset")

    details = "; ".join(checked)
    raise SystemExit(
        "Could not find a python-build-standalone asset for "
        f"CPython {python_version} target {target}. Checked: {details}"
    )


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "magi-release-runtime-preparer"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as handle:
            shutil.copyfileobj(response, handle)


def extract_archive(archive_path: Path, extract_dir: Path) -> None:
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)

    if archive_path.name.endswith(".tar.gz"):
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(extract_dir)
        return

    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extract_dir)
        return

    raise SystemExit(f"Unsupported runtime archive format: {archive_path.name}")


def find_runtime_root(extract_dir: Path) -> Path:
    candidates = (
        extract_dir / "python" / "install",
        extract_dir / "install",
        extract_dir / "python",
        extract_dir,
    )
    for candidate in candidates:
        if (candidate / "bin").is_dir() or (candidate / "python.exe").is_file():
            return candidate.resolve()
    raise SystemExit(f"Could not locate Python runtime root under {extract_dir}")


def runtime_python_candidates(runtime_root: Path, target: str) -> list[Path]:
    if target.endswith("windows-msvc"):
        return [
            runtime_root / "python.exe",
            runtime_root / "Scripts" / "python.exe",
        ]
    return [
        runtime_root / "bin" / "python",
        runtime_root / "bin" / "python3",
        *sorted((runtime_root / "bin").glob("python3.*")),
    ]


def validate_runtime(runtime_root: Path, target: str) -> None:
    for candidate in runtime_python_candidates(runtime_root, target):
        if candidate.is_file():
            print(f"Plugin Python executable: {candidate}")
            return
    raise SystemExit(
        f"No Python executable found in prepared runtime root: {runtime_root}"
    )


def write_github_env(github_env: Path, runtime_root: Path) -> None:
    with github_env.open("a", encoding="utf-8") as handle:
        handle.write(f"MAGI_PLUGIN_PYTHON_SOURCE={runtime_root}\n")
        handle.write("MAGI_REQUIRE_RELOCATABLE_PLUGIN_PYTHON=1\n")


def main() -> None:
    args = parse_args()
    output_dir = args.output.resolve()

    if args.asset_url:
        repository = "explicit-url"
        asset_name = Path(args.asset_url).name
        asset_url = args.asset_url
    else:
        repository, asset_name, asset_url = find_asset_url(
            args.python_version,
            args.target,
        )

    print(f"Selected plugin Python runtime from {repository}: {asset_name}")
    print(asset_url)
    if args.dry_run:
        return

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    archive_path = output_dir / asset_name
    print(f"Downloading runtime archive to {archive_path}")
    download(asset_url, archive_path)

    extract_dir = output_dir / "extract"
    print(f"Extracting runtime archive to {extract_dir}")
    extract_archive(archive_path, extract_dir)

    runtime_root = find_runtime_root(extract_dir)
    validate_runtime(runtime_root, args.target)
    print(f"MAGI_PLUGIN_PYTHON_SOURCE={runtime_root}")

    if args.github_env:
        write_github_env(args.github_env, runtime_root)
        print(f"Wrote MAGI_PLUGIN_PYTHON_SOURCE to {args.github_env}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
