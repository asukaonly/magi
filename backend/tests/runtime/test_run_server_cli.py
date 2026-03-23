from __future__ import annotations

from argparse import Namespace
import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _make_config(*, host: str, port: int, reload_enabled: bool, log_level: str):
    return SimpleNamespace(
        server=SimpleNamespace(host=host, port=port, reload=reload_enabled),
        log_level=log_level,
    )


def _load_run_server_module():
    module_path = Path(__file__).resolve().parents[2] / "run_server.py"
    spec = importlib.util.spec_from_file_location("run_server_under_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load run_server module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_server_config_uses_config_defaults(monkeypatch) -> None:
    run_server = _load_run_server_module()

    monkeypatch.setattr(
        run_server,
        "get_config",
        lambda: _make_config(host="0.0.0.0", port=8001, reload_enabled=True, log_level="INFO"),
    )
    args = Namespace(host=None, port=None, reload=None)

    host, port, reload_enabled, log_level = run_server._resolve_server_config(args)

    assert host == "0.0.0.0"
    assert port == 8001
    assert reload_enabled is True
    assert log_level == "info"


def test_resolve_server_config_applies_cli_overrides(monkeypatch) -> None:
    run_server = _load_run_server_module()

    monkeypatch.setattr(
        run_server,
        "get_config",
        lambda: _make_config(host="0.0.0.0", port=8001, reload_enabled=True, log_level="warning"),
    )
    args = Namespace(host="127.0.0.1", port=9000, reload=False)

    host, port, reload_enabled, log_level = run_server._resolve_server_config(args)

    assert host == "127.0.0.1"
    assert port == 9000
    assert reload_enabled is False
    assert log_level == "warning"
