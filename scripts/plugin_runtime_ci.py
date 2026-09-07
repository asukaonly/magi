#!/usr/bin/env python3
"""Run bounded native worker gates for an explicitly identified repository pair.

Host CI pins MAGI_PLUGINS_SHA in .github/workflows/ci.yml. Update that full SHA
in a reviewed host change after the companion package commit is published.
Companion CI resolves its host from scripts/registry-requirements.txt, then runs
this helper from that exact host checkout. Publish the host before the SDK pin.
Local runs omit expected SHAs and record both working-tree states as evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SDK_PIN = re.compile(
    r"magi-plugin-sdk\s*@\s*git\+https://github\.com/asukaonly/magi\.git@"
    r"([0-9a-f]{40})#subdirectory=sdk"
)


def resolve_host_pin(requirements: Path) -> str:
    """Reject missing, ambiguous, mutable, or foreign SDK requirements."""
    lines = [
        line.strip()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    candidates = [line for line in lines if "magi-plugin-sdk" in line.lower()]
    match = SDK_PIN.fullmatch(candidates[0]) if len(candidates) == 1 else None
    if match is None:
        raise ValueError(
            "Require one exact Magi SDK VCS pin ending in #subdirectory=sdk"
        )
    return match[1]


def native_platform() -> str:
    """Use the real operating system; the worker gate never simulates platforms."""
    return {"linux": "linux", "darwin": "macos", "win32": "windows"}[sys.platform]


def supports_native(platforms: list[str]) -> bool:
    return not platforms or native_platform() in platforms


def checkout_evidence(root: Path, expected: str | None = None) -> dict[str, object]:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    if expected is not None and (
        not re.fullmatch(r"[0-9a-f]{40}", expected) or head != expected
    ):
        raise ValueError(
            f"Checkout mismatch at {root}: expected {expected}, found {head}"
        )
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=root,
        text=True,
    )
    diff = subprocess.check_output(["git", "diff", "HEAD", "--binary"], cwd=root)
    return {
        "root": str(root),
        "head": head,
        "status": status,
        "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
    }


def test_selection(host: Path) -> list[str]:
    """Pick existing process files, including source-watch tests when integrated."""
    directory = host / "backend/tests/plugins"
    files = sorted(directory.glob("test_process_*.py"))
    required = [
        directory / "test_worker_sdk_admission.py",
        directory / "test_plugin_dependency_wheels.py",
        host / "backend/tests/scripts/test_plugin_runtime_ci.py",
    ]
    for path in [
        directory / "test_process_runtime.py",
        directory / "test_process_callback_lifecycle.py",
        *required,
    ]:
        if not path.is_file():
            raise ValueError(f"Required worker gate test is missing: {path}")
    return [str(path) for path in [host / "sdk/tests", *files, *required]]


def run_bounded(
    command: list[str], *, cwd: Path, env: dict[str, str], timeout: float
) -> dict[str, object]:
    """Bound a stage and terminate its process tree on timeout on each native OS."""
    started = time.monotonic()
    process = subprocess.Popen(
        command, cwd=cwd, env=env, start_new_session=os.name != "nt"
    )
    timed_out = False
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                timeout=30,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        code = process.wait(timeout=30)
    return {
        "command": command,
        "returncode": code,
        "timed_out": timed_out,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugins-repo", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument(
        "--pair-source", choices=["host-ci", "companion-ci", "local"], default="local"
    )
    parser.add_argument("--expected-host-sha")
    parser.add_argument("--expected-plugins-sha")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 13):
        parser.error("The paired worker gate requires Python 3.13")
    if args.pair_source != "local" and not (
        args.expected_host_sha and args.expected_plugins_sha
    ):
        parser.error("CI requires both exact checkout SHAs")
    companion = args.plugins_repo.resolve()
    output = args.report_dir.resolve()
    pin = resolve_host_pin(companion / "scripts/registry-requirements.txt")
    host = checkout_evidence(ROOT, args.expected_host_sha)
    plugins = checkout_evidence(companion, args.expected_plugins_sha)
    if args.pair_source == "companion-ci" and host["head"] != pin:
        parser.error("Companion CI host must equal its registry SDK pin")
    report = {
        "pair_source": args.pair_source,
        "host": host,
        "plugins": plugins,
        "registry_sdk_pin": pin,
        "native_platform": native_platform(),
        "python": sys.version,
        "stages": [],
    }
    output.mkdir(parents=True, exist_ok=True)

    def save() -> None:
        (output / "gate.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

    save()
    print(json.dumps(report), flush=True)
    env = os.environ.copy()
    env.update(
        PYTHONPATH=os.pathsep.join([str(ROOT / "sdk/src"), str(ROOT / "backend/src")]),
        PYTHONUNBUFFERED="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
    )
    with tempfile.TemporaryDirectory(prefix="magi-ci-worker-") as temporary:
        worker_root = Path(temporary) / "venv"
        worker_python = worker_root / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        env["MAGI_PLUGIN_PYTHON"] = str(worker_python)
        env["MAGI_HOME"] = str(Path(temporary) / "host-data")
        report["worker_python"] = str(worker_python)
        stages = [
            ([sys.executable, "-m", "venv", str(worker_root)], ROOT, 60),
            (
                [
                    str(worker_python),
                    "-I",
                    "-m",
                    "pip",
                    "install",
                    str(ROOT / "sdk"),
                    f"pydantic=={importlib.metadata.version('pydantic')}",
                ],
                ROOT,
                180,
            ),
            (
                [
                    str(worker_python),
                    "-I",
                    "-c",
                    "import importlib.util; "
                    "assert importlib.util.find_spec('magi') is None; import magi_plugin_sdk",
                ],
                ROOT,
                30,
            ),
            (
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-ra",
                    *test_selection(ROOT),
                    f"--junitxml={output / 'worker-tests.xml'}",
                ],
                ROOT / "backend",
                600,
            ),
            (
                [
                    sys.executable,
                    str(ROOT / "scripts/check-plugin-runtime.py"),
                    "--plugins-repo",
                    str(companion),
                    "--python",
                    str(worker_python),
                    "--install-dependencies",
                    "--report",
                    str(output / "plugin-runtime.json"),
                ],
                ROOT,
                900,
            ),
        ]
        for command, cwd, timeout in stages:
            result = run_bounded(command, cwd=cwd, env=env, timeout=timeout)
            report["stages"].append(result)
            save()
            print(json.dumps(result), flush=True)
            if result["returncode"] != 0 or result["timed_out"]:
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
