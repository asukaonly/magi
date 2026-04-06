"""Shared path helpers for benchmark run outputs."""

from __future__ import annotations

import re
from pathlib import Path


_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000
_GATEWAY_PORT_FILE = Path.home() / ".magi" / "runtime" / "gateway.port"


def resolve_backend_url() -> str:
    """Return the URL of a running Magi gateway.

    Discovery order:
      1. ``~/.magi/runtime/gateway.port`` — written by the Tauri desktop app
         or ``gateway-cli`` on startup.
      2. ``~/.magi/config/agent.yaml``  ``server.host`` / ``server.port``
         (legacy).
      3. Fallback to ``http://127.0.0.1:8000``.
    """
    # Prefer the runtime port file (written by gateway on startup)
    if _GATEWAY_PORT_FILE.exists():
        try:
            port = int(_GATEWAY_PORT_FILE.read_text(encoding="utf-8").strip())
            return f"http://{_DEFAULT_HOST}:{port}"
        except (ValueError, OSError):
            pass

    config_file = Path.home() / ".magi" / "config" / "agent.yaml"
    host = _DEFAULT_HOST
    port = _DEFAULT_PORT
    if config_file.exists():
        try:
            import yaml

            data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            server = data.get("server") or {}
            if server.get("host"):
                raw_host = str(server["host"]).strip()
                host = _DEFAULT_HOST if raw_host == "0.0.0.0" else raw_host
            if server.get("port"):
                port = int(server["port"])
        except Exception:
            pass
    return f"http://{host}:{port}"


def build_run_output_dir(*, root_dir: str | Path, benchmark_name: str, run_id: str) -> Path:
    root = Path(root_dir)
    output_dir = root / _sanitize_component(benchmark_name) / _sanitize_component(run_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _sanitize_component(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "").strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("._-")
    return normalized or "unknown"
