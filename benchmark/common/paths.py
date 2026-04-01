"""Shared path helpers for benchmark run outputs."""

from __future__ import annotations

import re
from pathlib import Path


_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000


def resolve_backend_url() -> str:
    """Read the backend URL from ~/.magi/config/agent.yaml, falling back to localhost:8000."""
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
