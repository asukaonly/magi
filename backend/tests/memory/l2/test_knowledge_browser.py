"""Knowledge browsing searches and filters before bounded pagination."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory import memory_router
from magi.api.routers.memory.l2 import knowledge_routes
from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.entities.catalog import L2EntityCatalog


@pytest.fixture
async def knowledge_store(l2_store_with_schema):
    store = l2_store_with_schema
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    for index in range(65):
        await catalog.upsert_entity(
            entity_id=f"entity:{index:02d}", entity_type="place" if index < 5 else "person",
            canonical_name=f"京都旧记录{index}" if index < 5 else f"Recent person {index}",
        )
    async with sqlite_connection_async(store.db_path) as db:
        await db.executemany(
            """INSERT INTO knowledge_graph
            (triple_id, subject_id, subject_type, predicate, object_id, object_type,
             evidence_event_ids, first_observed_at, last_observed_at, created_at, updated_at,
             status, authority_ref)
            VALUES (?, 'user:self', 'person', 'VISITED', ?, ?, '[]', 1, 1, 1, ?, ?, ?)""",
            [(f"relation:{i:02d}", f"entity:{i:02d}", "place" if i < 5 else "person", i,
              "superseded" if i < 5 else "active", "forget:test" if i == 0 else None)
             for i in range(65)],
        )
        await db.executemany(
            """INSERT INTO tom_trait_assertions
            (assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
             confidence_score, evidence_events, volatility_index, source_domain, inference_depth,
             validation_state, first_inferred_at, last_validated_at, created_at, updated_at,
             status, authority_ref, user_feedback, slot_key)
            VALUES (?, ?, ?, 'identity_profile', 'identity.name', 'retained', 0.9, '[]', 0.1,
                    'user_authored', 'direct', ?, 1, 1, 1, ?, ?, ?, ?, ?)""",
            [(f"assertion:{i:02d}", f"entity:{i:02d}", "place" if i < 5 else "person",
              "tentative" if i < 5 else "corroborated", i, "active",
              "forget:test" if i == 0 else None, None, f"slot:{i}") for i in range(65)],
        )
        await db.commit()
    return store, catalog


@pytest.mark.asyncio
async def test_search_and_type_status_counts_include_matches_beyond_first_fifty(knowledge_store):
    store, catalog = knowledge_store
    assert len(await store.get_relationships(include_inactive=True, limit=50)) == 50
    filters = dict(query="京都", entity_type="place", status_group="deprecated", include_inactive=True)
    relations = await store.get_relationships(**filters, limit=2)
    assert [row["triple_id"] for row in relations] == ["relation:04", "relation:03"]
    assert await store.count_relationships(**filters) == 4
    assert [row["triple_id"] for row in await store.get_relationships(**filters, limit=2, offset=2)] == ["relation:02", "relation:01"]
    assert await store.count_relationships(**{**filters, "status_group": "active"}) == 0
    assertion_filters = {**filters, "status_group": "needsReview"}
    assert await store.count_tom_assertions(**assertion_filters) == 4
    assert len(await store.list_tom_assertions(**assertion_filters, limit=2, offset=2)) == 2
    assert await store.count_tom_assertions(**{**assertion_filters, "entity_type": "person"}) == 0
    assert await catalog.count_entities(query="京都", entity_type="place") == 5
    assert [row["entity_id"] for row in await catalog.list_entities(query="京都", entity_type="place", limit=2, offset=2)] == ["entity:02", "entity:03"]


@pytest.mark.asyncio
@pytest.mark.parametrize("validation,status,feedback,group", [
    ("tentative", "active", None, "needsReview"),
    ("tentative", "active", "confirmed", "active"),
    ("corroborated", "active", None, "active"),
    ("corroborated", "superseded", "confirmed", "deprecated"),
    ("conflicted", "active", "confirmed", "conflicted"),
    ("corroborated", "active", "rejected", "deprecated"),
])
async def test_assertion_status_filters_match_display_precedence(knowledge_store, validation, status, feedback, group):
    store, _ = knowledge_store
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("UPDATE tom_trait_assertions SET validation_state=?, status=?, user_feedback=? WHERE assertion_id='assertion:01'", (validation, status, feedback))
        await db.commit()
    filters = dict(query="assertion:01", status_group=group, include_inactive=True)
    assert await store.count_tom_assertions(**filters) == 1
    assert len(await store.list_tom_assertions(**filters)) == 1


@pytest.mark.asyncio
async def test_filtered_knowledge_lists_reachable_through_public_router(knowledge_store, monkeypatch):
    store, catalog = knowledge_store
    monkeypatch.setattr(knowledge_routes, "_resolve_unified_memory", lambda: SimpleNamespace(l2=store, l2_entity_catalog=catalog))
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    with TestClient(app) as client:
        response = client.get("/api/memory/l2/relations", params={"query": "京都", "status_group": "deprecated", "entity_type": "place", "include_inactive": True, "limit": 2, "offset": 2})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 4 and len(body["items"]) == 2
        assert body["items"][0]["object_name"] == "京都旧记录2"
        response = client.get("/api/memory/l2/assertions", params={"query": "京都", "status_group": "needsReview", "entity_type": "place", "include_inactive": True})
        assert response.status_code == 200 and response.json()["total"] == 4
        response = client.get("/api/memory/l2/entities", params={"query": "京都", "entity_type": "place", "limit": 2, "offset": 2})
        assert response.status_code == 200 and response.json()["total"] == 5
        assert len(response.json()["items"]) == 2
        assert client.get("/api/memory/l2/relations", params={"status_group": "invalid"}).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("path,id_field,table,evidence_field,record_id,forgotten_id", [
    ("relations", "triple_id", "knowledge_graph", "evidence_event_ids", "relation:01", "relation:00"),
    ("assertions", "assertion_id", "tom_trait_assertions", "evidence_events", "assertion:01", "assertion:00"),
])
async def test_exact_record_lookup_preserves_evidence_revision_and_governance(
    knowledge_store, monkeypatch, path, id_field, table, evidence_field, record_id, forgotten_id,
):
    store, catalog = knowledge_store
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            f"UPDATE {table} SET {evidence_field}='[\"event:exact\"]', updated_at=42, status='superseded' WHERE {id_field}=?",
            (record_id,),
        )
        await db.commit()
    monkeypatch.setattr(knowledge_routes, "_resolve_unified_memory", lambda: SimpleNamespace(l2=store, l2_entity_catalog=catalog))
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    with TestClient(app) as client:
        endpoint = f"/api/memory/l2/{path}"
        response = client.get(endpoint, params={id_field: record_id, "include_inactive": True, "limit": 1})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1 and len(body["items"]) == 1
        assert body["items"][0][id_field] == record_id
        assert body["items"][0][evidence_field] == ["event:exact"]
        assert body["items"][0]["updated_at"] == 42
        assert body["items"][0]["status"] == "superseded"
        for query_params in (
            {id_field: record_id},
            {id_field: forgotten_id, "include_inactive": True},
            {id_field: record_id[:-1], "include_inactive": True},
            {id_field: "", "include_inactive": True},
            {id_field: record_id, "query": "unrelated text", "include_inactive": True},
        ):
            response = client.get(endpoint, params=query_params)
            assert response.status_code == 200
            assert response.json()["items"] == []
            assert response.json()["total"] == 0
