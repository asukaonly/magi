"""Validate reflection routes through the product router allowlist."""

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.personality_config import personality_config_router
from magi.identity.defaults import CANONICAL_LOCAL_USER


def test_public_routes_and_owner_are_enforced(monkeypatch):
    service = AsyncMock()
    service.page.return_value = {"items": [], "enabled": False, "sharing_enabled": False}
    monkeypatch.setattr("magi.api.routers.persona_reflections.get_persona_journal_service", lambda: service)
    app = FastAPI()
    app.include_router(_build_public_router(personality_config_router, _PUBLIC_ROUTE_METHODS["personality_config"]))
    with TestClient(app) as client:
        assert client.get("/reflections/p1").status_code == 200
        service.page.assert_awaited_once_with(str(CANONICAL_LOCAL_USER), "p1")
        assert client.delete("/reflections/p1/thought").status_code == 204
        service.dismiss.assert_awaited_once_with(str(CANONICAL_LOCAL_USER), "p1", "thought")
        assert client.post("/journal/reflect", json={}).status_code == 404


def test_unavailable_service_does_not_return_empty_success(monkeypatch):
    monkeypatch.setattr("magi.api.routers.persona_reflections.get_persona_journal_service", lambda: None)
    app = FastAPI()
    app.include_router(_build_public_router(personality_config_router, _PUBLIC_ROUTE_METHODS["personality_config"]))
    with TestClient(app) as client:
        assert client.get("/reflections/p1").status_code == 503
