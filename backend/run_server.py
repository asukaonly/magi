#!/usr/bin/env python3
"""
Magi backend server launcher.
"""
import sys
import os

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import uvicorn
from magi.config import get_config

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000


def _resolve_server_config() -> tuple[str, int, bool, str]:
    """Resolve startup parameters strictly from runtime config file."""
    config = get_config()
    host = str(config.server.host or DEFAULT_HOST).strip() or DEFAULT_HOST
    port = int(config.server.port or DEFAULT_PORT)
    reload_enabled = bool(config.server.reload)
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


def main() -> None:
    host, port, reload_enabled, log_level = _resolve_server_config()
    _print_banner(host=host, port=port, reload_enabled=reload_enabled)

    uvicorn.run(
        "magi.backend_app:create_backend_app",
        host=host,
        port=port,
        reload=reload_enabled,
        log_level=log_level,
        factory=True,
    )


if __name__ == "__main__":
    main()
