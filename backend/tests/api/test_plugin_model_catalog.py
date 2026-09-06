"""Public model catalog and persisted plugin model selection coverage."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import config as config_api
from magi.api.routers.config_schemas import LLMSelectionConfigModel, SystemConfigModel
from magi.api.routers.config_update_paths import build_full_update_paths
from magi.api.routers.llm import llm_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.services import llm_plugin_providers
from magi.config import loader as config_loader
from magi.i18n import language_context
from magi.plugins.providers import PluginProviderRegistry
from magi_plugin_sdk.runtime import PluginConnection


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(config_loader, "get_magi_home", lambda: tmp_path)
    monkeypatch.setattr(config_loader, "get_example_config_file", lambda: tmp_path / "absent.yaml")
    loader = config_loader.ConfigLoader()
    monkeypatch.setattr(config_loader, "_loader", loader)
    loader.load()
    connection = PluginConnection(
        connection_id="account-a",
        plugin_id="local-model",
        display_name="Local account",
        enabled=True,
    )
    connections = {connection.connection_id: connection}
    registry = PluginProviderRegistry(get_connection=connections.get)
    dispose = registry.register(
        plugin_id=connection.plugin_id,
        connection_id=connection.connection_id,
        kind="model",
        provider_id="account-a:chat",
        implementation=SimpleNamespace(invoke=AsyncMock(), stream=AsyncMock()),
    )
    monkeypatch.setattr(
        llm_plugin_providers,
        "resolve_plugin_manager",
        lambda: SimpleNamespace(provider_registry=registry),
    )
    monkeypatch.setattr(
        config_api, "_refresh_or_initialize_runtime_after_config_update", AsyncMock()
    )
    monkeypatch.setattr(config_api, "_enqueue_runtime_channels_refresh_command", AsyncMock())
    app = FastAPI()
    app.include_router(
        _build_public_router(llm_router, _PUBLIC_ROUTE_METHODS["llm"]), prefix="/api/llm"
    )
    app.include_router(
        _build_public_router(config_api.config_router, _PUBLIC_ROUTE_METHODS["config"]),
        prefix="/api/config",
    )
    with language_context("en"):
        yield SimpleNamespace(
            client=TestClient(app),
            loader=loader,
            connection=connection,
            connections=connections,
            dispose=dispose,
            root=tmp_path,
        )


def test_public_catalog_exposes_only_live_plugin_choices(runtime):
    expected = [
        {
            "provider_id": "account-a:chat",
            "plugin_id": "local-model",
            "connection_id": "account-a",
            "display_name": "Local account / chat",
            "model_selection": "manual",
        }
    ]
    for response in (
        runtime.client.get("/api/llm/providers/catalog"),
        runtime.client.post("/api/llm/providers/catalog", json={"providers": {}}),
    ):
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["plugin_providers"] == expected
        assert "account-a:chat" not in {provider["id"] for provider in data["providers"]}

    runtime.connections["account-a"] = runtime.connection.model_copy(update={"enabled": False})
    assert runtime.client.get("/api/llm/providers/catalog").json()["data"]["plugin_providers"] == []
    runtime.connections["account-a"] = runtime.connection
    runtime.dispose()
    assert (
        runtime.client.post("/api/llm/providers/catalog", json={"providers": {}}).json()["data"][
            "plugin_providers"
        ]
        == []
    )


def test_public_config_saves_and_reloads_plugin_selection_without_native_credentials(runtime):
    payload = SystemConfigModel()
    payload.llm.selections["core"] = LLMSelectionConfigModel(
        provider_id="account-a:chat", model="local/manual-model"
    )
    response = runtime.client.put("/api/config/", json=payload.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    saved = yaml.safe_load((runtime.root / "config" / "llm.yaml").read_text())
    assert saved["selections"]["core"]["provider_id"] == "account-a:chat"
    assert saved["selections"]["core"]["model"] == "local/manual-model"
    reloaded = runtime.loader.reload()
    assert reloaded.llm.providers == {}
    assert reloaded.llm.selections["core"].provider_id == "account-a:chat"
    public = runtime.client.get("/api/config/").json()["data"]["llm"]
    assert public["providers"] == {}
    assert public["selections"]["core"]["model"] == "local/manual-model"


@pytest.mark.parametrize("scenario", ["embedding", "image_generation"])
def test_plugin_models_cannot_be_assigned_to_unsupported_services(runtime, scenario):
    payload = SystemConfigModel()
    payload.llm.selections[scenario] = LLMSelectionConfigModel(
        provider_id="account-a:chat", model="manual"
    )
    with pytest.raises(ValueError, match="chat scenarios only"):
        build_full_update_paths(payload)


def test_plugin_selection_requires_manual_model_and_live_connection(runtime):
    payload = SystemConfigModel()
    payload.llm.selections["core"] = LLMSelectionConfigModel(
        provider_id="account-a:chat", model="  "
    )
    with pytest.raises(ValueError, match="explicit model ID"):
        build_full_update_paths(payload)
    payload.llm.selections["core"].model = "manual"
    runtime.connections["account-a"] = runtime.connection.model_copy(update={"enabled": False})
    with pytest.raises(ValueError, match="unknown provider"):
        build_full_update_paths(payload)
