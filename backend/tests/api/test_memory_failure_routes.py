"""The public memory router exposes bounded, redacted diagnostics."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from _shared.memory_api import MemoryApiStub

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory import memory_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router


def test_failure_details_are_reachable_and_redact_secrets(monkeypatch):
    store = SimpleNamespace(get_projection_failure_summary=AsyncMock(return_value={
        "total": 2, "other_count": 0, "groups": [{
            "source": "chat", "reason": "unknown", "count": 2,
            "last_failed_at": 12.5, "error": "Authorization: Bearer secret-token-value",
            "source_text": "Private source content",
        }],
    }))
    memory = MemoryApiStub(l2=store)
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: memory)
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    client = TestClient(app)
    response = client.get("/api/memory/l2/failures")
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert "secret-token-value" not in response.text
    assert "Private source content" not in response.text
    assert "source_text" not in response.text
    store.get_projection_failure_summary.assert_awaited_once()
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: None)
    assert client.get("/api/memory/l2/failures").status_code == 503
