#!/usr/bin/env python3
"""Select CI jobs and conservative backend test groups from the complete Git diff."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


JOBS = ("backend", "frontend", "plugin_runtime", "gateway", "desktop", "rust_security")
# Shared runtime, storage, model and configuration changes use the full backend suite.
# Feature groups include their callers and public API/lifecycle boundaries.
FEATURE_TESTS = {
    "media": ("media", "awareness", "chat", "agent", "api", "plugins", "tools"),
    "mcp": ("mcp", "tools", "agent", "api", "plugins", "skills"),
    "speech": ("speech", "media", "tools", "api", "plugins"),
}


def changed_paths(root: Path, event_name: str, event: dict) -> list[str] | None:
    """Return both sides of renames; an unavailable baseline requests full validation."""
    if event_name == "pull_request":
        pull = event["pull_request"]
        base, head = pull["base"]["sha"], pull["head"]["sha"]
        revision = f"{base}...{head}"
    elif event_name == "push":
        base, head = event.get("before"), event.get("after")
        if not base or not head or set(base) == {"0"}:
            return None
        revision = f"{base}..{head}"
    else:
        return None
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--no-renames", "-z", revision, "--"],
            cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError:
        return None
    return [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]


def select_scope(paths: list[str] | None, root: Path) -> dict:
    """Unknown shared inputs require complete validation instead of skipped checks."""
    selected: set[str] = set()
    targets: set[str] = set()
    full = paths is None
    for path in paths or []:
        if path.startswith((".github/workflows/", "sdk/", "contracts/", "configs/")) or path in {
            "VERSION", "backend/pyproject.toml",
        }:
            full = True
        elif path.startswith("scripts/"):
            full = True
        elif path.startswith("backend/tests/"):
            selected.add("backend")
            relative = Path(path).relative_to("backend")
            if relative.name == "conftest.py" or relative.parts[1] == "_shared" or len(relative.parts) < 3:
                targets.add("tests")
                selected.add("plugin_runtime")
            else:
                targets.add(str(Path(*relative.parts[:2])))
                if relative.parts[1] in {"plugins", "sdk"}:
                    selected.add("plugin_runtime")
        elif path.startswith("backend/src/magi/"):
            selected.update(("backend", "plugin_runtime"))
            feature = path.split("/")[3]
            targets.update(f"tests/{name}" for name in FEATURE_TESTS.get(feature, ()))
            if feature not in FEATURE_TESTS:
                targets.add("tests")
            else:
                targets.update(("tests/bootstrap", "tests/runtime", "tests/integration"))
            if feature in {"api", "transport", "ipc", "bootstrap", "config", "db"}:
                selected.update(("frontend", "gateway", "desktop"))
        elif path.startswith("backend/"):
            selected.update(("backend", "plugin_runtime", "gateway", "desktop"))
            targets.add("tests")
        elif path.startswith("frontend/src-tauri/"):
            selected.update(("frontend", "desktop", "rust_security"))
        elif path.startswith("frontend/"):
            selected.add("frontend")
            if not path.startswith(("frontend/src/", "frontend/public/")):
                selected.update(("desktop", "backend"))
                targets.update(("tests/scripts", "tests/tools"))
        elif path.startswith(("crates/", "server/", "vendor/", ".cargo/")) or path in {
            "Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "rustfmt.toml",
        }:
            selected.update(("gateway", "desktop", "rust_security", "backend"))
            targets.add("tests/scripts")
        elif path.startswith("plugins/"):
            selected.update(("backend", "plugin_runtime"))
            targets.add("tests")
        elif path.startswith("benchmark/"):
            selected.add("backend")
            targets.add("tests/scripts")
        elif path == "docs/task-agent-runtime-architecture.md":
            selected.add("backend")
            targets.add("tests/runtime")
        elif path.startswith("docs/") or path.endswith(".md") or path in {"LICENSE", ".gitignore"}:
            continue
        else:
            full = True
    if full:
        selected.update(JOBS)
        targets = {"tests"}
    # A removed/renamed test directory must not turn into a collection error or no tests.
    if "tests" in targets or any(not (root / "backend" / target).is_dir() for target in targets):
        targets = {"tests"}
    return {
        "full": full,
        **{job: job in selected for job in JOBS},
        "backend_targets": sorted(targets),
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    paths = changed_paths(root, os.environ["GITHUB_EVENT_NAME"], event)
    scope = select_scope(paths, root)
    print(json.dumps({"changed_paths": paths, **scope}, indent=2))
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        for key, value in scope.items():
            output.write(f"{key}={json.dumps(value)}\n")
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
        summary.write("## Validation scope\n\n")
        summary.write("Mode: " + ("full" if scope["full"] else "changed paths") + "\n\n")
        summary.write("Jobs: " + ", ".join(job for job in JOBS if scope[job]) + "\n\n")
        summary.write("Backend tests: " + ", ".join(scope["backend_targets"]) + "\n")


if __name__ == "__main__":
    main()
