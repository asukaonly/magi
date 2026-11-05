"""Native memory reads pass through the actual public route boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from _shared.memory_api import MemoryApiStub
from magi.api.routers.memory import memory_router, library_routes
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.memory.evidence import USER_VISIBLE_L1_RETRIEVAL_SCOPES


@pytest.fixture
def client(monkeypatch):
    l1 = SimpleNamespace(query_events=AsyncMock(return_value=[{
        "event_id": "event-1", "content": "Walked today", "source": "apple_health",
        "timestamp": 100.0, "embedding": [1.0], "metadata_json": {"private": "hidden"},
    }]), count_events=AsyncMock(return_value=1))
    memory = MemoryApiStub(l1=l1)
    monkeypatch.setattr(library_routes.dependencies, "_resolve_unified_memory", lambda: memory)
    monkeypatch.setattr(library_routes, "canonical_self_id", lambda _: "local_user")
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    with TestClient(app) as client:
        yield client, l1


def test_events_expose_only_product_fields_and_governed_scope(client):
    http, l1 = client
    response = http.get("/api/memory/library?view=events")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["text"] == "Walked today" and item["can_delete"]
    assert "embedding" not in item and "metadata_json" not in item
    assert l1.query_events.call_args.kwargs["l1_retrieval_scopes"] == list(USER_VISIBLE_L1_RETRIEVAL_SCOPES)
    assert l1.count_events.call_args.kwargs["l1_retrieval_scopes"] == list(USER_VISIBLE_L1_RETRIEVAL_SCOPES)


def test_evidence_missing_is_not_a_fabricated_record(client):
    http, l1 = client
    l1.query_events.return_value = []
    assert http.get("/api/memory/library/evidence/forgotten").status_code == 404
    assert l1.query_events.call_args.kwargs["event_id"] == "forgotten"


def test_portrait_preserves_review_and_correction_identity(client, monkeypatch):
    http, _ = client
    monkeypatch.setattr(library_routes, "_get_self_portrait", AsyncMock(return_value={
        "self_view": {"world": {"groups": []}, "recent": {"items": []}, "review": {"items": [
            {"id": "fact-1", "assertion_id": "assertion-1", "text": "Prefers mornings", "updated_at": 12.0,
             "correction_value": "mornings", "basis_refs": ["event-1"]}]}}, "is_stale": True,
    }))
    page = http.get("/api/memory/library").json()
    assert page["stale"] and page["items"][0]["needs_review"]
    assert page["items"][0]["assertion_id"] == "assertion-1"
    assert page["items"][0]["evidence_ids"] == ["event-1"]


def test_search_uses_governed_retrieval_and_deduplicates(client, monkeypatch):
    http, _ = client
    event = {"event_id": "same", "content": "Found", "source": "chat"}
    query = AsyncMock(return_value={"l1_events": [event, event], "l2_assertions": []})
    monkeypatch.setattr(library_routes, "search_memory", query)
    page = http.get("/api/memory/library?query=walk").json()
    assert page["total"] == 1 and query.call_args.args[0].query == "walk"
    assert http.get("/api/memory/library?limit=101").status_code == 422
