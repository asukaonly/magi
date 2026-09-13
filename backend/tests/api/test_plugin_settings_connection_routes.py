import time
from uuid import uuid4
from magi.runtime_trace import RuntimeTraceStore

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


class RequestClient(TestClient):
    def post(self, *args, **kwargs):
        headers = {"x-magi-request-id": f"{int(time.time() * 1000)}-{uuid4()}",
                   "x-magi-client-id": "device", "x-magi-data-epoch": "test-epoch"}
        headers.update(kwargs.pop("headers", {}))
        return super().post(*args, headers=headers, **kwargs)


@pytest.fixture
def api(monkeypatch, tmp_path):
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
    from magi.api.services import plugin_rpc
    from _shared.db_schema import apply_chain_schema
    apply_chain_schema("runtime_trace", tmp_path / "runtime_trace.db")
    receipts = RuntimeTraceStore(db_path=str(tmp_path / "runtime_trace.db"))
    monkeypatch.setenv("MAGI_DATA_EPOCH", "test-epoch")
    monkeypatch.setattr(plugin_rpc, "get_container", lambda: SimpleNamespace(runtime_trace_store=lambda: receipts))
    app = FastAPI()
    public = _build_public_router(
        routes.plugins_core_router, _PUBLIC_ROUTE_METHODS["plugins"]
    )
    app.include_router(public, prefix="/api/plugins")
    return RequestClient(app), service


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


def test_starting_the_same_request_replays_its_session_without_starting_twice(api):
    client, service = api
    headers = {"x-magi-request-id": f"{int(time.time() * 1000)}-{uuid4()}"}
    first = client.post("/api/plugins/connections/work/settings/actions/login/start", json={}, headers=headers)
    second = client.post("/api/plugins/connections/work/settings/actions/login/start", json={}, headers=headers)
    assert first.status_code == 200 and second.json() == first.json()
    assert service.start_plugin_settings_action.await_count == 1
