#!/usr/bin/env python3
"""Validate a temporary Mac LaunchAgent installation without replacing an existing one."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin" or os.geteuid() == 0:
        raise RuntimeError("Use the logged-in Mac owner account without sudo")
    executable = args.executable.resolve(strict=True)
    plist = Path.home() / "Library/LaunchAgents/app.magi.server.plist"
    target = f"gui/{os.geteuid()}/app.magi.server"
    if plist.exists() or plist.is_symlink() or subprocess.run(
        ["/bin/launchctl", "print", target], capture_output=True
    ).returncode == 0:
        raise RuntimeError("An existing Magi LaunchAgent must not be changed by this validation")

    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix="ms-agent-", dir="/private/tmp")).resolve()
    config = root / "server.json"
    subprocess.run([str(executable), "init", "--config", str(config),
                    "--data-dir", str(root / "data"), "--port", "0"], check=True, capture_output=True)

    def command(name: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run([str(executable), name, "--config", str(config)],
                                capture_output=True, text=True, timeout=60, check=check)
        if name != "status":
            print(json.dumps({"step": name, "data_root": str(root), "exit_code": result.returncode}), flush=True)
        return result

    def ready() -> dict:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            result = command("status", check=False)
            if result.returncode == 0:
                status = json.loads(result.stdout)
                if status.get("runtime_ready"):
                    return status
            time.sleep(0.5)
        diagnostic = subprocess.run(["/bin/launchctl", "print", target], capture_output=True, text=True)
        raise RuntimeError(f"Managed service never became ready; inspect {root}\n{diagnostic.stdout}\n{diagnostic.stderr}")

    def stopped() -> None:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if command("status", check=False).returncode != 0 and not (root / "data/runtime/worker.ready").exists():
                return
            time.sleep(0.25)
        raise RuntimeError(f"Managed service did not stop; inspect {root}")

    try:
        command("install")
        first = ready()
        command("start")
        assert ready()["server_id"] == first["server_id"]
        assert plist.is_file()
        assert (root / "data/logs/service.log").is_file()
        assert (root / "data/logs/backend.log").is_file()
        command("stop")
        stopped()
        assert plist.exists()
        command("start")
        assert ready()["server_id"] == first["server_id"]
        command("restart")
        assert ready()["server_id"] == first["server_id"]
        command("uninstall")
        stopped()
        assert not plist.exists()
        assert config.is_file() and (root / "data/service/server.db").is_file()
        print(json.dumps({"result": "passed", "data_root": str(root),
                          "runtime_ready": first["runtime_ready"],
                          "install_start_stop_restart_uninstall": True,
                          "data_preserved": True}), flush=True)
    finally:
        # The installer verifies exact executable/config ownership before removal.
        if plist.exists():
            cleanup = command("uninstall", check=False)
            if cleanup.returncode:
                raise RuntimeError(f"Temporary LaunchAgent cleanup failed: {cleanup.stderr}")


if __name__ == "__main__":
    main()
