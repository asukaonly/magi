"""Public assertion and pending-review responses share the complete-fact read model."""

from __future__ import annotations

import sqlite3

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory import memory_router
from magi.memory.hybrid_retrieval.models import RetrievalPayload


@pytest.fixture(autouse=True)
def _chinese_display_language():
    from magi.i18n import language_context
    with language_context("zh-CN"):
        yield


def test_public_assertion_search_and_review_share_fact_display(tmp_path, monkeypatch):
    db_path = str(tmp_path / "memory.db")
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE entity_catalog (entity_id TEXT, canonical_name TEXT)")
        db.execute("INSERT INTO entity_catalog VALUES ('food:opaque', '草莓')")
    assertion = {
        "assertion_id": "assert-strawberry", "entity_id": "user:local_user", "entity_type": "user",
        "trait_family": "preference_profile", "trait_name": "preference.affinity", "trait_value": "like",
        "target_entity_id": "food:opaque", "target_entity_type": "food", "natural_summary": "用户喜欢草莓。",
        "status": "tentative", "source_domain": "user_authored", "temporal_scope": "stable",
    }
    store = SimpleNamespace(
        db_path=db_path,
        list_tom_assertions=AsyncMock(return_value=[assertion]),
        count_tom_assertions=AsyncMock(return_value=1),
        list_pending_reviews=AsyncMock(return_value=[{
            "review_id": "review-strawberry", "status": "pending", "version": 1,
            "proposed": {**assertion, "natural_summary": ""},
        }]),
    )
    memory = SimpleNamespace(l2=store, identity_resolver=None)
    monkeypatch.setattr("magi.api.routers.memory.l2.knowledge_routes._resolve_unified_memory", lambda: memory)
    monkeypatch.setattr("magi.api.routers.memory.l2.review_routes._resolve_unified_memory", lambda: memory)
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    client = TestClient(app)

    result = client.get("/api/memory/l2/assertions", params={"query": "草莓"})
    assert result.status_code == 200
    item = result.json()["items"][0]
    assert item["display_text"] == "用户喜欢草莓。"
    assert item["target_entity_name"] == "草莓"
    assert item["trait_value"] == "like"
    assert item["value_options"] == ["like", "dislike"]
    assert store.list_tom_assertions.await_args.kwargs["query"] == "草莓"

    response = client.get("/api/memory/l2/reviews")
    assert response.status_code == 200
    proposed = response.json()["items"][0]["proposed"]
    assert proposed["display_text"] == item["display_text"]
    assert proposed["trait_value"] == "like"
    assert proposed["status"] == "tentative"

    retrieval = SimpleNamespace(query=AsyncMock(return_value=RetrievalPayload(l2_assertions=[assertion])))
    monkeypatch.setattr("magi.api.routers.memory.search_routes._resolve_hybrid_retrieval_service", lambda: retrieval)
    monkeypatch.setattr("magi.api.routers.memory.search_routes._resolve_unified_memory", lambda: memory)
    search = client.post("/api/memory/search", json={"query": "我喜欢什么"})
    assert search.status_code == 200
    assert search.json()["l2_assertions"][0]["display_text"] == "用户喜欢草莓。"
    assert search.json()["l2_assertions"][0]["trait_value"] == "like"
    assert "display_text" not in assertion
