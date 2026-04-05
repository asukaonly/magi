from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_api_route_registration_does_not_import_transport() -> None:
    from magi.api import routes as api_routes

    source = Path(api_routes.__file__).read_text(encoding="utf-8")

    assert "register_websocket" not in source
    assert "FastAPI(" not in source


def test_legacy_socketio_transport_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("magi.websocket.server")


def test_legacy_backend_app_is_removed() -> None:
    """Verify the HTTP-mode backend_app factory no longer exists."""
    assert not (Path(__file__).resolve().parents[2] / "src/magi/backend_app.py").exists()


def test_legacy_websocket_transport_modules_are_removed() -> None:
    """Verify HTTP-mode WebSocket transport modules are deleted."""
    websocket_dir = Path(__file__).resolve().parents[2] / "src/magi/websocket"
    assert not (websocket_dir / "router.py").exists()
    assert not (websocket_dir / "bridge_lifecycle.py").exists()
    assert not (websocket_dir / "connection_manager.py").exists()
    assert not (websocket_dir / "handlers.py").exists()
