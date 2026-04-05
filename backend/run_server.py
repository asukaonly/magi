#!/usr/bin/env python3
"""
Magi backend server launcher.
"""
import argparse
import sys
import os

# Suppress leaked-semaphore warning from HuggingFace tokenizers in forked processes
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Add src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import uvicorn
from magi.config import get_config
from magi.backend_runtime_worker import main as run_runtime_worker
from magi.process_roles import PROCESS_ROLE_ENV_VAR, ProcessRole, resolve_process_role

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000


def _resolve_server_config(args: argparse.Namespace) -> tuple[str, int, bool, str]:
    """Resolve startup parameters from config with optional CLI overrides."""
    config = get_config()
    host = str(args.host or config.server.host or DEFAULT_HOST).strip() or DEFAULT_HOST
    port = int(args.port or config.server.port or DEFAULT_PORT)
    reload_enabled = bool(config.server.reload) if args.reload is None else bool(args.reload)
    log_level = str(config.log_level or "info").strip().lower() or "info"
    return host, port, reload_enabled, log_level


def _print_banner(host: str, port: int, reload_enabled: bool) -> None:
    protocol = "http"
    ws_protocol = "ws"
    print("=" * 60)
    print("Starting Magi backend server")
    print("=" * 60)
    print(f"API: {protocol}://{host}:{port}")
    print(f"Health: {protocol}://{host}:{port}/api/health")
    print(f"WebSocket: {ws_protocol}://{host}:{port}/ws")
    print(f"Reload: {reload_enabled}")
    print("=" * 60)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Magi backend launcher")
    parser.add_argument(
        "--role",
        dest="process_role",
        help="Backend process role: api or runtime_worker",
    )
    parser.add_argument(
        "--host",
        dest="host",
        help="Override server host for transport roles",
    )
    parser.add_argument(
        "--port",
        dest="port",
        type=int,
        help="Override server port for transport roles",
    )
    reload_group = parser.add_mutually_exclusive_group()
    reload_group.add_argument(
        "--reload",
        dest="reload",
        action="store_true",
        help="Enable auto-reload for transport roles",
    )
    reload_group.add_argument(
        "--no-reload",
        dest="reload",
        action="store_false",
        help="Disable auto-reload for transport roles",
    )
    parser.set_defaults(reload=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    role = resolve_process_role(args.process_role, env=os.environ)
    os.environ[PROCESS_ROLE_ENV_VAR] = role.value

    if role is ProcessRole.RUNTIME_WORKER:
        run_runtime_worker()
        return

    host, port, reload_enabled, log_level = _resolve_server_config(args)
    _print_banner(host=host, port=port, reload_enabled=reload_enabled)

    uvicorn.run(
        "magi.backend_app:create_backend_app",
        host=host,
        port=port,
        reload=reload_enabled if role is ProcessRole.API else False,
        log_level=log_level,
        factory=True,
    )


if __name__ == "__main__":
    main()
