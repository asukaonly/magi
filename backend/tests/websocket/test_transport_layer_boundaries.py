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


def test_backend_app_builds_transport_app() -> None:
    import magi.backend_app as backend_app

    source = Path(backend_app.__file__).read_text(encoding="utf-8")

    assert "from .websocket.http_app import create_transport_app" in source
    assert "from .api.app import create_app" not in source


def test_websocket_bridge_lifecycle_does_not_use_runtime_global_message_bus() -> None:
    from magi.websocket import bridge_lifecycle

    source = Path(bridge_lifecycle.__file__).read_text(encoding="utf-8")

    assert "events.service_access" not in source


def test_websocket_handlers_do_not_use_runtime_global_accessors() -> None:
    from magi.websocket import handlers

    source = Path(handlers.__file__).read_text(encoding="utf-8")

    assert "events.service_access" not in source
    assert "personality.current_state" not in source
