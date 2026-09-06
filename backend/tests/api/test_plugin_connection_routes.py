"""Exercise connection handlers through the actual product route filter."""

from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from magi_plugin_sdk.contracts import ExtensionFieldSpec

from magi.api.routers import plugins_connection_routes as routes
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.plugins.connection_settings import connection_fields, validate_connection_settings
from magi.plugins.connections import PluginConnectionStore
from magi.utils.runtime import RuntimePaths


@pytest.fixture
def api(tmp_path, monkeypatch):
    fields = [ExtensionFieldSpec(key="directory", label="Directory", type="path"),
              ExtensionFieldSpec(key="interval", label="Interval", type="number", minimum=1, maximum=60),
              ExtensionFieldSpec(key="token", label="Token", type="secret")]
    package = SimpleNamespace(manifest=SimpleNamespace(plugin_id="example", kind="plugin", settings_fields=fields), trusted=True,
                              contributions=[SimpleNamespace(fields=fields, metadata={})])
    def require(plugin_id):
        if plugin_id != "example":
            raise HTTPException(404, "Package missing")
        return package
    def authorize(connection):
        if not package.trusted:
            raise PermissionError("Package authorization missing")
    store = PluginConnectionStore(runtime_paths=RuntimePaths(tmp_path / "runtime"), require_package=require,
                                  authorize_enable=authorize,
                                  validate_settings=lambda connection: validate_connection_settings(connection, fields))
    manager = SimpleNamespace(connection_store=store, create_connection=store.create,
                              update_connection=store.update, disconnect_connection=store.disconnect,
                              clear_connection_content=store.clear_content, connection_readiness=store.get_readiness)
    monkeypatch.setattr(routes, "_require_package", lambda plugin_id: (manager, require(plugin_id)))
    app = FastAPI()
    app.include_router(_build_public_router(routes.plugins_connection_router, _PUBLIC_ROUTE_METHODS["plugins"]), prefix="/api/plugins")
    return TestClient(app), store, package


def test_product_allowlist_exposes_all_connection_handlers(api):
    client, _, _ = api
    response = client.get("/api/plugins/example/connections")
    assert response.status_code == 200
    assert response.json() == {"connections": [], "total": 0}
    expected = {
        ("/{plugin_id}/connections", "GET"), ("/{plugin_id}/connections", "POST"),
        ("/{plugin_id}/connections/{connection_id}", "GET"),
        ("/{plugin_id}/connections/{connection_id}", "PATCH"),
        ("/{plugin_id}/connections/{connection_id}", "DELETE"),
        ("/{plugin_id}/connections/{connection_id}/clear", "POST"),
    }
    public = _build_public_router(routes.plugins_connection_router, _PUBLIC_ROUTE_METHODS["plugins"])
    assert expected <= {(route.path, method) for route in public.routes for method in route.methods}


def test_instances_are_independent_write_only_and_conflict_checked(api):
    client, store, _ = api
    def create(name):
        result = client.post("/api/plugins/example/connections", json={"display_name": name,
                             "settings": {"directory": f"/{name}"}, "credentials": {"token": f"{name}-secret"}})
        assert result.status_code == 201, result.text
        assert f"{name}-secret" not in result.text
        return result.json()
    first, second = create("Work"), create("Home")
    path = f"/api/plugins/example/connections/{first['connection_id']}"
    response = client.patch(path, json={"expected_revision": 0, "settings": {"directory": "/updated"}})
    assert response.status_code == 200
    assert response.json()["revision"] == 1
    conflict = client.patch(path, json={"expected_revision": 0, "enabled": True})
    assert conflict.status_code == 409
    assert store.get(second["connection_id"]).settings == {"directory": "/Home"}
    assert client.get(path).status_code == 200
    assert client.delete(path, params={"expected_revision": 0}).status_code == 409
    assert client.delete(path, params={"expected_revision": 1}).status_code == 204
    assert client.get(path).status_code == 404


def test_absent_package_unapproved_enabling_and_extra_fields_fail_closed(api):
    client, store, package = api
    assert client.post("/api/plugins/missing/connections", json={"display_name": "Work"}).status_code == 404
    package.trusted = False
    assert client.post("/api/plugins/example/connections", json={"display_name": "Work", "enabled": True}).status_code == 403
    assert store.list() == []
    assert client.post("/api/plugins/example/connections", json={"display_name": "Work", "connection_id": "chosen"}).status_code == 422
    assert client.post("/api/plugins/example/connections", json={"display_name": "Work", "enabled": "false"}).status_code == 422


@pytest.mark.parametrize("settings", [{"interval": "5"}, {"interval": True}, {"interval": 61},
                                     {"directory": 1}, {"undeclared": "x"}, {"token": "sensitive-value"}])
def test_generic_settings_are_validated_before_persistence(api, settings):
    client, store, _ = api
    response = client.post("/api/plugins/example/connections", json={"display_name": "Work", "settings": settings})
    assert response.status_code == 422
    assert "sensitive-value" not in response.text
    assert store.list() == []


def test_clear_preserves_settings_and_connection(api):
    client, store, _ = api
    connection = store.create("example", display_name="Work", settings={"interval": 10})
    context = store.context(connection.connection_id)
    (context.resources_dir / "content").write_text("content")
    response = client.post(f"/api/plugins/example/connections/{connection.connection_id}/clear", json={"expected_revision": 0})
    assert response.status_code == 200
    assert response.json()["settings"] == {"interval": 10}
    assert store.get(connection.connection_id).revision == 1
    assert not list(context.resources_dir.iterdir())


def test_schema_errors_never_echo_write_only_request_data(api):
    client, store, _ = api
    response = client.post("/api/plugins/example/connections", json={
        "display_name": "Work", "credentials": {"token": {"private": "do-not-echo"}},
    })
    assert response.status_code == 422
    assert "do-not-echo" not in response.text
    assert store.list() == []


def test_connection_changes_refresh_channels_only_after_success(api, monkeypatch):
    from unittest.mock import AsyncMock

    client, store, _ = api
    refresh = AsyncMock()
    monkeypatch.setattr(routes, "_refresh_channels_after_plugin_change", refresh)
    draft = client.post("/api/plugins/example/connections", json={"display_name": "Work"}).json()
    refresh.assert_not_awaited()
    path = f"/api/plugins/example/connections/{draft['connection_id']}"
    assert client.patch(path, json={"expected_revision": 0, "enabled": True}).status_code == 200
    refresh.assert_awaited_once_with("example", "connection_updated")
    assert client.get(path).status_code == 200
    assert client.patch(path, json={"expected_revision": 0, "enabled": False}).status_code == 409
    assert refresh.await_count == 1
    assert client.post(path + "/clear", json={"expected_revision": 1}).status_code == 200
    assert refresh.await_count == 2
    assert client.delete(path, params={"expected_revision": 2}).status_code == 204
    assert refresh.await_count == 3
    assert not store.list()


def test_legacy_package_account_routes_are_absent():
    from magi.api.routers.plugins import plugins_router

    public = _build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"])
    paths = {route.path for route in public.routes}
    assert not {"/{plugin_id}/settings", "/{plugin_id}/enable", "/{plugin_id}/disable"} & paths


def test_public_package_authorization_binds_reviewed_digest(api, monkeypatch):
    from unittest.mock import Mock
    from magi_plugin_sdk import PluginManifest, PluginPackageState

    client, store, package = api
    manager, _ = routes._require_package("example")
    manager.authorize_package = Mock(return_value=PluginPackageState(
        manifest=PluginManifest(id="example", name="Example", version="0.2.0"), trusted=True,
    ))
    response = client.post("/api/plugins/example/trust", json={"expected_package_sha256": "a" * 64})
    assert response.status_code == 200
    manager.authorize_package.assert_called_once_with("example", "a" * 64)
    assert not store.list()
    assert client.post("/api/plugins/example/trust", json={}).status_code == 422
