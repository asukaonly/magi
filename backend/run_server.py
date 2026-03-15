#!/usr/bin/env python3
"""
Magi backend server launcher.
"""
import sys
import os
from argparse import ArgumentParser

# 加载.env文件
from dotenv import load_dotenv
if load_dotenv():
    os.environ["MAGI_ENV_LOADED"] = "1"

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import uvicorn

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000


def _to_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_args():
    parser = ArgumentParser(description="Start Magi backend service.")
    parser.add_argument("--host", default=os.getenv("MAGI_BACKEND_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("MAGI_BACKEND_PORT", str(DEFAULT_PORT))))
    parser.add_argument(
        "--reload",
        action="store_true",
        default=_to_bool(os.getenv("MAGI_BACKEND_RELOAD"), True),
        help="Enable auto-reload (for local development only).",
    )
    parser.add_argument(
        "--no-reload",
        action="store_false",
        dest="reload",
        help="Disable auto-reload.",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("MAGI_BACKEND_LOG_LEVEL", "info"),
    )
    return parser.parse_args()


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


def main() -> None:
    args = _resolve_args()

    # Desktop sidecar mode must always bind localhost and disable reload.
    desktop_mode = _to_bool(os.getenv("MAGI_DESKTOP_MODE"), False)
    host = "127.0.0.1" if desktop_mode else args.host
    reload_enabled = False if desktop_mode else args.reload

    _print_banner(host=host, port=args.port, reload_enabled=reload_enabled)

    uvicorn.run(
        "magi.backend_app:create_backend_app",
        host=host,
        port=args.port,
        reload=reload_enabled,
        log_level=args.log_level,
        factory=True,
    )


if __name__ == "__main__":
    main()
