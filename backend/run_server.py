#!/usr/bin/env python3
"""
Magi backend server launcher.

In desktop mode the Rust gateway spawns this script with --role=ipc_worker.
The only supported role is ipc_worker (agent runtime + IPC server, no HTTP).
"""
import sys
import os

# Suppress leaked-semaphore warning from HuggingFace tokenizers in forked processes
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Add src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def main() -> None:
    from magi.utils.log_redaction import install_redacting_standard_streams

    install_redacting_standard_streams()

    from magi.bootstrap.process_roles import PROCESS_ROLE_ENV_VAR, PROCESS_ROLE_VALUE
    from magi.bootstrap.worker_app import main as run_ipc_worker

    os.environ[PROCESS_ROLE_ENV_VAR] = PROCESS_ROLE_VALUE
    run_ipc_worker()


if __name__ == "__main__":
    main()
