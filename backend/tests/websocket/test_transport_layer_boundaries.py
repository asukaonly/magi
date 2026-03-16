from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_connection_manager_lives_in_websocket_layer() -> None:
    from magi.websocket.connection_manager import ConnectionManager

    assert ConnectionManager.__module__ == "magi.websocket.connection_manager"


def test_websocket_bridge_lifecycle_lives_in_websocket_layer() -> None:
    from magi.websocket.bridge_lifecycle import WebSocketBridgeLifecycleModule

    assert WebSocketBridgeLifecycleModule.__module__ == "magi.websocket.bridge_lifecycle"


def test_api_route_registration_does_not_import_transport() -> None:
    from magi.api import routes as api_routes

    source = Path(api_routes.__file__).read_text(encoding="utf-8")

    assert "register_websocket" not in source
    assert "FastAPI(" not in source


def test_legacy_socketio_transport_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("magi.websocket.server")


def test_backend_app_builds_transport_app() -> None:
    import magi.backend_app as backend_app

    source = Path(backend_app.__file__).read_text(encoding="utf-8")

    assert "from .websocket.http_app import create_transport_app" in source
    assert "from .api.app import create_app" not in source
