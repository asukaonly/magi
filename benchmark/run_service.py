"""Own a local Magi service for an authenticated benchmark session."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--server", type=Path,
        default=Path(__file__).resolve().parents[1] / "target" / "debug" / (
            "magi-server.exe" if os.name == "nt" else "magi-server"
        ),
    )
    args = parser.parse_args()
    environment = dict(os.environ)
    token = environment.pop("MAGI_DESKTOP_SESSION_TOKEN", "")
    if len(token) < 32:
        parser.error("MAGI_DESKTOP_SESSION_TOKEN must contain a fresh random credential of at least 32 characters")
    process = subprocess.Popen(
        [str(args.server), "run", "--config", str(args.config), "--bootstrap-stdin"],
        stdin=subprocess.PIPE, text=True, env=environment,
    )
    assert process.stdin is not None
    try:
        process.stdin.write(json.dumps({"session_token": token}) + "\n")
        process.stdin.flush()
        return process.wait()
    except KeyboardInterrupt:
        process.stdin.close()
        try:
            return process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait()
    finally:
        process.stdin.close()


if __name__ == "__main__":
    raise SystemExit(main())
