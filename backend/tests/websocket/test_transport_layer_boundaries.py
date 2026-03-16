from __future__ import annotations

from pathlib import Path


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
