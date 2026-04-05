#!/usr/bin/env python3
"""
Magi backend server launcher.

In desktop mode the Rust gateway spawns this script with --role=ipc_worker.
"""
import argparse
import sys
import os

# Suppress leaked-semaphore warning from HuggingFace tokenizers in forked processes
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Add src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from magi.process_roles import PROCESS_ROLE_ENV_VAR, ProcessRole, resolve_process_role


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Magi backend launcher")
    parser.add_argument(
        "--role",
        dest="process_role",
        help="Backend process role: ipc_worker or runtime_worker",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    role = resolve_process_role(args.process_role, env=os.environ)
    os.environ[PROCESS_ROLE_ENV_VAR] = role.value

    if role is ProcessRole.RUNTIME_WORKER:
        from magi.backend_runtime_worker import main as run_runtime_worker
        run_runtime_worker()
        return

    if role is ProcessRole.IPC_WORKER:
        from magi.worker_app import main as run_ipc_worker
        run_ipc_worker()
        return

    raise SystemExit(
        f"Process role '{role.value}' requires the Rust gateway. "
        "Use --role=ipc_worker for the Python IPC backend."
    )


if __name__ == "__main__":
    main()
