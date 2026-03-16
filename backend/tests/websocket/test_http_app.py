from __future__ import annotations

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient


def test_transport_app_registers_health_and_websocket(monkeypatch) -> None:
    from magi.websocket.http_app import create_transport_app

    monkeypatch.setattr(
        "magi.websocket.http_middleware.get_required_desktop_session_token",
        lambda: None,
    )

    app = create_transport_app()
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    websocket_routes = [route.path for route in app.routes if not isinstance(route, APIRoute)]
    assert "/ws" in websocket_routes
