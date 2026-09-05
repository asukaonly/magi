"""Connection settings APIs are reachable and mint identities in the host."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from magi_plugin_sdk.contracts import (
    PluginSettingsActionResult,
    PluginSettingsResourcePayload,
)
from magi_plugin_sdk.runtime import PluginConnection

from magi.api.routers import plugins_core_routes as routes
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.plugins.settings_service import PluginSettingsActionRun


@pytest.fixture
def api(monkeypatch):
    connections = {
        name: PluginConnection(
            connection_id=name, plugin_id="example", display_name=name
        )
        for name in ("work", "home")
    }
    package = SimpleNamespace(
        contributions=[], manifest=SimpleNamespace(plugin_id="example", plugin_dir="")
    )
    service = SimpleNamespace(
        start_plugin_settings_action=AsyncMock(
            return_value=PluginSettingsActionRun(
                session_id="session",
                result=PluginSettingsActionResult(status="pending"),
            )
        ),
        poll_plugin_settings_action=AsyncMock(
            return_value=PluginSettingsActionRun(
                session_id="session",
                result=PluginSettingsActionResult(status="uncertain"),
            )
        ),
        cancel_plugin_settings_action=AsyncMock(
            return_value=PluginSettingsActionRun(
                session_id="session",
                result=PluginSettingsActionResult(status="cancelled"),
            )
        ),
        read_plugin_settings_resource=AsyncMock(
            return_value=PluginSettingsResourcePayload(
                plugin_id="example", resource_name="qr", data={"qr": "image"}
            )
        ),
    )
    manager = SimpleNamespace(
        connection_store=SimpleNamespace(get=connections.__getitem__),
        get_package=lambda _: package,
        settings_service=service,
    )
    monkeypatch.setattr(routes, "_require_plugin_manager", lambda: manager)
    monkeypatch.setattr(
        routes, "_translate_resource_payload", lambda payload, _id: payload
    )
    app = FastAPI()
    public = _build_public_router(
        routes.plugins_core_router, _PUBLIC_ROUTE_METHODS["plugins"]
    )
    app.include_router(public, prefix="/api/plugins")
    return TestClient(app), service


def test_public_action_routes_use_connection_and_host_identity(api):
    client, service = api
    path = "/api/plugins/connections/work/settings/actions/login"
    response = client.post(
        f"{path}/start",
        json={"field_values": {"account": "user"}, "principal_id": "forged"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["connection_id"] == "work"
    call = service.start_plugin_settings_action.await_args
    assert call.args == ("work", "login")
    assert call.kwargs["identity"].principal_id == "local_user"
    assert call.kwargs["identity"].connection_id == "work"
    assert call.kwargs["identity"].trigger == "user"
    assert (
        client.post(f"{path}/sessions/session/poll", json={}).json()["status"]
        == "uncertain"
    )
    assert (
        client.post(f"{path}/sessions/session/cancel").json()["status"] == "cancelled"
    )
    assert (
        client.post(
            "/api/plugins/example/settings/actions/login/start", json={}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/plugins/connections/example/settings/actions/login/start", json={}
        ).status_code
        == 404
    )


def test_public_resource_route_awaits_the_connection_service(api):
    client, service = api
    response = client.get("/api/plugins/connections/home/settings/resources/qr")
    assert response.status_code == 200, response.text
    assert response.json()["connection_id"] == "home"
    service.read_plugin_settings_resource.assert_awaited_once_with("home", "qr")
    assert client.get("/api/plugins/example/settings/resources/qr").status_code == 404
