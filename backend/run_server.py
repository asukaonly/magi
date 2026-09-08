#!/usr/bin/env python3
"""
Magi backend server launcher.

In desktop mode the Rust gateway spawns this script with --role=ipc_worker.
The only supported role is ipc_worker (agent runtime + IPC server, no HTTP).
"""
import sys
import os
import traceback

# Suppress leaked-semaphore warning from HuggingFace tokenizers in forked processes
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Add src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def main() -> None:
    from magi.utils.log_redaction import install_redacting_standard_streams

    install_redacting_standard_streams()

    from magi_plugin_sdk.runtime_paths import get_magi_home
    from magi.utils.worker_instance import WorkerInstance

    parent_value = os.environ.pop("MAGI_SERVER_PARENT_PID", None)
    parent_pid = int(parent_value) if parent_value is not None else None
    # Acquire ownership before importing modules that open runtime logs or stores.
    with WorkerInstance(get_magi_home(), parent_pid):
        from magi.bootstrap.process_roles import PROCESS_ROLE_ENV_VAR, PROCESS_ROLE_VALUE
        from magi.bootstrap.worker_app import main as run_ipc_worker

        os.environ[PROCESS_ROLE_ENV_VAR] = PROCESS_ROLE_VALUE
        run_ipc_worker()


def run() -> int:
    """Run the desktop worker and convert startup failures into an exit code."""
    try:
        main()
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
