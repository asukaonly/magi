"""The public memory router exposes bounded, redacted diagnostics."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from _shared.memory_api import MemoryApiStub

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory import memory_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router


def test_failure_details_are_reachable_and_redact_secrets(monkeypatch):
    store = SimpleNamespace(get_projection_failure_summary=AsyncMock(return_value={
        "total": 2, "other_count": 0, "retryable_count": 2, "groups": [{
            "source": "chat", "reason": "unknown", "count": 2, "retry_allowed": True,
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


def make_client(monkeypatch, memory):
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: memory)
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    return TestClient(app)


def test_records_show_bounded_previews_and_explicit_originals(monkeypatch):
    row = {"event_id": "event-1", "source": "chat", "status": "failed", "attempt_count": 5,
           "reason": "content_filter", "retry_allowed": True, "error": None,
           "last_failed_at": 10, "updated_at": 20}
    store = SimpleNamespace(list_projection_failure_records=AsyncMock(return_value={"items": [row], "total": 1, "limit": 20, "offset": 0}))
    l1 = SimpleNamespace(get_user_visible_event=AsyncMock(return_value={"content": "原文" * 300, "timestamp": 5}))
    client = make_client(monkeypatch, MemoryApiStub(l2=store, l1=l1))
    response = client.get("/api/memory/l2/failures/records", params={"reason": "content_filter", "source": "chat"})
    assert response.status_code == 200
    assert len(response.json()["items"][0]["content"]) == 400
    assert response.json()["items"][0]["content_truncated"] is True
    l1.get_user_visible_event.assert_awaited_once_with("event-1")
    response = client.get("/api/memory/l2/failures/records", params={"include_content": True, "event_id": "event-1"})
    assert response.json()["items"][0]["content"] == "原文" * 300
    assert response.json()["items"][0]["content_truncated"] is False
    assert client.get("/api/memory/l2/failures/records", params={"include_content": True}).status_code == 422
    l1.get_user_visible_event.return_value = None
    assert client.get("/api/memory/l2/failures/records").json()["items"][0]["content"] is None


@pytest.mark.parametrize("body", [
    {"action": "delete", "selections": []},
    {"action": "ignore", "selections": []},
    {"action": "ignore", "selections": [{"event_id": "event-1"}]},
    {"action": "ignore", "selections": [{"event_id": " event-1", "expected_updated_at": 20}]},
    {"action": "ignore", "selections": [{"event_id": "event-1", "expected_updated_at": 20}] * 2},
])
def test_disposition_rejects_invalid_or_unfenced_selection(monkeypatch, body):
    action = AsyncMock()
    client = make_client(monkeypatch, MemoryApiStub(l2=object(), set_l2_failure_disposition=action))
    assert client.post("/api/memory/l2/failures/disposition", json=body).status_code == 422
    action.assert_not_awaited()


def test_disposition_is_publicly_reachable_without_replay_or_deletion(monkeypatch):
    action = AsyncMock(return_value={"changed_count": 1, "unchanged_count": 0})
    memory = MemoryApiStub(l2=object(), set_l2_failure_disposition=action)
    client = make_client(monkeypatch, memory)
    body = {"action": "ignore", "selections": [{"event_id": "event-1", "expected_updated_at": 20.0}]}
    response = client.post("/api/memory/l2/failures/disposition", json=body)
    assert response.status_code == 200
    action.assert_awaited_once_with(**body)
