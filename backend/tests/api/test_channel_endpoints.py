"""Endpoint routes must be reachable through the product allowlist."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.channels_bindings import channels_bindings_router
from magi.api.routes import _build_public_router, _PUBLIC_ROUTE_METHODS
from magi.api.routers.config_schemas import SystemConfigModel
from magi.api.routers.config_update_paths import _preferences_update_paths


def test_discovery_and_configuration_are_public_router_members(monkeypatch):
    endpoint = dict(connection_id="account", contribution_id="telegram", target_id="group", thread_id="topic", device_id=None)
    catalog = SimpleNamespace(
        list_endpoints=AsyncMock(return_value=[dict(endpoint=endpoint, label="Family", capabilities=["message"], available=True)]),
        delivery_preferences=lambda: [endpoint], set_delivery_preferences=AsyncMock(),
    )
    monkeypatch.setattr("magi.api.routers.channel_endpoints._catalog", lambda: catalog)
    app = FastAPI()
    app.include_router(_build_public_router(channels_bindings_router, _PUBLIC_ROUTE_METHODS["channels_bindings"]), prefix="/api/channels")
    with TestClient(app) as client:
        assert client.get("/api/channels/endpoints").json()["endpoints"][0]["endpoint"] == endpoint
        assert client.get("/api/channels/delivery-preferences").json() == {"targets": [endpoint]}
        assert client.put("/api/channels/delivery-preferences", json={"targets": [endpoint]}).status_code == 200
        catalog.set_delivery_preferences.assert_awaited_once_with([endpoint])
        assert client.put("/api/channels/delivery-preferences", json={"targets": [{**endpoint, "target_id": ""}]}).status_code == 422


def test_general_config_cannot_overwrite_destination_preferences():
    updates = _preferences_update_paths(SystemConfigModel())
    assert "preferences" not in updates
    assert "preferences.delivery_targets" not in updates
    assert "preferences.language" in updates


def test_delivery_status_is_reachable_without_exposing_content(monkeypatch):
    from magi.delivery.outbox import DeliveryStatus
    from magi_plugin_sdk.endpoints import EndpointRef

    item = DeliveryStatus("delivery", "message", "session", EndpointRef("account", "telegram", "group"), "uncertain", 1, 200)
    monkeypatch.setattr("magi.api.routers.channel_endpoints._catalog", lambda: SimpleNamespace(delivery_status=AsyncMock(return_value=[item])))
    app = FastAPI()
    app.include_router(_build_public_router(channels_bindings_router, _PUBLIC_ROUTE_METHODS["channels_bindings"]), prefix="/api/channels")
    with TestClient(app) as client:
        response = client.get("/api/channels/delivery-status")
        assert response.status_code == 200
        row, = response.json()["deliveries"]
        assert row["state"] == "uncertain"
        assert "content" not in row and "receipt" not in row
