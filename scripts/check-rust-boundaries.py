#!/usr/bin/env python3
"""Check declared Rust dependencies across all targets, features and dependency kinds."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHARED = {"magi-platform", "magi-service-contract"}
WORKSPACE_DEPENDENCIES = {
    "magi-desktop": SHARED,
    "magi-server": SHARED | {"magi-server-runtime"},
    "magi-server-runtime": SHARED | {"magi-gateway"},
    "magi-gateway": {"magi-service-contract"},
    "magi-platform": set(),
    "magi-service-contract": set(),
}
EXTERNAL_ALLOWLISTS = {
    "magi-service-contract": {"serde", "serde_json"},
    "magi-platform": {"libc", "windows-sys"},
}


def validate_metadata(metadata: dict[str, Any]) -> list[str]:
    """Reject reverse dependencies and shared crates that pull in implementation libraries."""
    members = set(metadata["workspace_members"])
    packages = {
        package["name"]: package for package in metadata["packages"] if package["id"] in members
    }
    failures = []
    for name in sorted(set(packages) ^ set(WORKSPACE_DEPENDENCIES)):
        failures.append(f"Workspace package needs an explicit boundary rule: {name}")
    for name, package in packages.items():
        for dependency in package["dependencies"]:
            target = dependency["name"]
            kind = dependency.get("kind") or "normal"
            label = f"{name} -> {target} ({kind})"
            if target in packages:
                allowed = WORKSPACE_DEPENDENCIES.get(name, set())
                # CLI integration fixtures exercise the gateway directly; production does not.
                if name == "magi-server" and kind == "dev":
                    allowed = allowed | {"magi-gateway"}
                if target not in allowed:
                    failures.append(f"Forbidden workspace dependency: {label}")
            elif dependency.get("path"):
                failures.append(f"Local dependency must have a workspace boundary rule: {label}")
            elif name in EXTERNAL_ALLOWLISTS and target not in EXTERNAL_ALLOWLISTS[name]:
                failures.append(f"Shared crate must remain lightweight: {label}")
            elif name == "magi-desktop" and target in {
                "axum",
                "rusqlite",
                "sqlx",
                "libsqlite3-sys",
            }:
                failures.append(f"Desktop must use the service API: {label}")
            elif name != "magi-desktop" and (target == "tauri" or target.startswith("tauri-")):
                failures.append(f"Service crates must not depend on the desktop: {label}")
    return sorted(failures)


def main() -> int:
    result = subprocess.run(
        ["cargo", "metadata", "--no-deps", "--locked", "--format-version", "1"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        return result.returncode
    failures = validate_metadata(json.loads(result.stdout))
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("Rust workspace dependency boundaries passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
