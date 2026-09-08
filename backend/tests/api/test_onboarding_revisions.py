"""Public onboarding preconditions and atomic configuration receipts."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers import config as routes
from magi.api.routers.config_schemas import FullPersonalityConfigModel, LLMProviderConfigModel
from magi.config import loader


def configured_llm(initial):
    import copy
    llm = copy.deepcopy(initial["llm"])
    llm["providers"]["openai"] = LLMProviderConfigModel(api_key="fixture-key").model_dump(mode="json")
    llm["selections"]["core"].update(provider_id="openai", model="fixture-model")
    return llm


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(loader, "get_magi_home", lambda: tmp_path)
    monkeypatch.setattr(loader, "_loader", None)
    monkeypatch.setattr(routes, "_load_full_personality", FullPersonalityConfigModel)
    monkeypatch.setattr(routes, "_refresh_or_initialize_runtime_after_config_update", AsyncMock())
    monkeypatch.setattr(routes, "_enqueue_runtime_channels_refresh_command", AsyncMock())
    app = FastAPI()
    app.include_router(_build_public_router(routes.config_router, _PUBLIC_ROUTE_METHODS["config"]), prefix="/api/config")
    return TestClient(app)


def test_onboarding_scope_ignores_other_settings_and_rejects_stale_drafts(client):
    initial = client.get("/api/config/onboarding-template").json()["data"]["config"]
    payload = {"revision": initial["revision"], "language": "en", "llm": configured_llm(initial)}
    assert len(payload["revision"]) == 64
    routes.save_config({"agent.name": "Other setting"})
    routes.reload_config()
    saved = client.put("/api/config/onboarding-draft", json=payload)
    assert saved.status_code == 200
    assert saved.json()["data"]["revision"] != payload["revision"]
    stale = client.put("/api/config/onboarding-draft", json={**payload, "language": "zh"})
    assert stale.status_code == 409
    assert client.post("/api/config/onboarding-complete", json=payload).status_code == 409
    assert client.get("/api/config/onboarding-status").json()["data"]["completed"] is False
    assert client.put("/api/config/onboarding-draft", json={"language": "zh", "llm": initial["llm"]}).status_code == 428
    assert client.get("/api/config/").json()["data"]["preferences"]["language"] == "en"
    completed = client.post("/api/config/onboarding-complete", json={**payload, "revision": saved.json()["data"]["revision"]})
    assert completed.status_code == 200
    assert client.get("/api/config/onboarding-status").json()["data"]["completed"] is True


@pytest.mark.parametrize("onboarding", [True, False])
def test_save_receipt_is_captured_before_runtime_refresh(client, monkeypatch, onboarding):
    async def later_update(*args, **kwargs):
        routes.save_config({"preferences.language": "zh", "agent.name": "Later writer"})
        routes.reload_config()

    monkeypatch.setattr(routes, "_refresh_or_initialize_runtime_after_config_update", later_update)
    if onboarding:
        initial = client.get("/api/config/onboarding-template").json()["data"]["config"]
        saved = client.put("/api/config/onboarding-draft", json={"revision": initial["revision"], "language": "en", "llm": configured_llm(initial)})
        assert saved.status_code == 200
        assert saved.json()["data"]["preferences"]["language"] == "en"
        current = client.get("/api/config/onboarding-template").json()["data"]["config"]
    else:
        initial = client.get("/api/config/").json()["data"]
        initial["agent"]["name"] = "My saved name"
        saved = client.put("/api/config/", json=initial)
        assert saved.status_code == 200
        assert saved.json()["data"]["agent"]["name"] == "My saved name"
        current = client.get("/api/config/").json()["data"]
    assert current["revision"] != saved.json()["data"]["revision"]
    assert client.get("/api/config/").json()["data"]["agent"]["name"] == "Later writer"
