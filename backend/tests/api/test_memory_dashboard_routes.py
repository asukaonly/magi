from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory import memory_router


class _FakeL0Store:
    checkpoint_db_path = "/tmp/l0.db"
    _sessions: dict = {}
    _attention_items: dict = {}


class _FakeL1Store:
    db_path = "/tmp/l1.db"

    async def count_events(self, **kwargs):
        if kwargs.get("start_time") is not None:
            return 4
        return 12

    async def summarize_event_sources(self, **kwargs):
        assert kwargs["cognition_eligible"] is True
        assert kwargs["exclude_retention_class"] == "disposable"
        return [
            {
                "source": "chrome-history",
                "event_count": 9,
                "avg_importance": 0.6,
                "min_timestamp": 1710000000.0,
                "max_timestamp": 1710003600.0,
            },
            {
                "source": "chat",
                "event_count": 3,
                "avg_importance": 0.8,
                "min_timestamp": 1710000100.0,
                "max_timestamp": 1710000200.0,
            },
        ]


class _FakeL2Store:
    db_path = "/tmp/l2.db"

    def __init__(self):
        self.count_assertion_kwargs: list[dict] = []
        self.list_assertion_kwargs = None
        self.get_assertion_ids: list[str] = []

    async def count_relationships(self):
        return 4

    async def count_tom_assertions(self, **kwargs):
        if kwargs:
            self.count_assertion_kwargs.append(kwargs)
            if "temporal_clause" in kwargs:
                return 3
            return 2
        return 6

    async def list_tom_assertions(self, **kwargs):
        self.list_assertion_kwargs = kwargs
        return [
            {
                "assertion_id": "assert-1",
                "entity_id": "user:self",
                "entity_type": "user",
                "trait_family": "preference_profile",
                "trait_name": "favorite_language",
                "trait_value": "Python",
                "confidence_score": 0.3,
                "evidence_events": ["evt-1"],
                "validation_state": "tentative",
                "volatility_index": 0.4,
                "source_domain": "conversation",
                "inference_depth": "semantic",
                "first_inferred_at": 1710000000.0,
                "last_validated_at": 1710000000.0,
                "user_feedback": None,
                "user_feedback_at": None,
                "status": "tentative",
            }
        ]

    async def get_tom_assertion(self, *, assertion_id: str):
        self.get_assertion_ids.append(assertion_id)
        if assertion_id == "assert-current":
            return {
                "assertion_id": "assert-current",
                "entity_id": "user:self",
                "entity_type": "user",
                "trait_family": "preference_profile",
                "trait_name": "favorite_language",
                "trait_value": "TypeScript",
                "confidence_score": 0.8,
                "evidence_events": ["evt-2"],
                "validation_state": "stable",
                "volatility_index": 0.3,
                "source_domain": "conversation",
                "inference_depth": "semantic",
                "first_inferred_at": 1710001000.0,
                "last_validated_at": 1710001000.0,
                "user_feedback": None,
                "user_feedback_at": None,
                "status": "stable",
            }
        return None


class _FakeL3Store:
    db_path = "/tmp/l3.db"

    async def count_summaries(self, **kwargs):
        if kwargs.get("start_time") is not None:
            return 2
        return 5

    def get_statistics(self):
        return {
            "embedding_queue_size": 3,
            "embedding_worker_running": True,
            "vector_enabled": True,
            "async_embeddings": True,
        }


class _FakeL4Store:
    db_path = "/tmp/l4.db"

    async def count_skills(self):
        return 1


class _FakeUnifiedMemory:
    def __init__(self):
        self.l0 = _FakeL0Store()
        self.l1 = _FakeL1Store()
        self.l2 = _FakeL2Store()
        self.l3 = _FakeL3Store()
        self.l4 = _FakeL4Store()

    @asynccontextmanager
    async def memory_operation_guard(self):  # type: ignore[no-untyped-def]
        yield

    def get_l2_pipeline_stats(self):
        return {
            "reconcile_enqueued": 6,
            "reconcile_completed": 2,
            "reconcile_failed": 1,
            "snapshot_enqueued": 4,
            "snapshot_completed": 1,
            "snapshot_failed": 0,
        }

    async def get_l2_projection_backlog(self):
        return {"pending": 5, "claimed": 2, "completed": 8, "failed": 1}


def test_memory_dashboard_reports_statistics_sources_and_pending(monkeypatch):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    fake_memory = _FakeUnifiedMemory()
    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: fake_memory)
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get("/api/memory/dashboard", params={"pending_limit": 4})

    assert response.status_code == 200
    body = response.json()
    assert body["statistics"]["stored_records"] == 28
    assert body["deltas"] == {
        "today": {
            "stored_records": 9,
            "l1_events": 4,
            "l2_assertions": 3,
            "l3_summaries": 2,
            "disk_usage_bytes": None,
        }
    }
    assert body["source_counts"][0] == {
        "source": "chrome-history",
        "event_count": 9,
        "avg_importance": 0.6,
        "first_event_at": 1710000000.0,
        "last_event_at": 1710003600.0,
    }
    assert body["attention"]["pending_assertions"] == 2
    assert body["pending_assertions"]["total"] == 2
    assert body["pending_assertions"]["items"][0]["assertion_id"] == "assert-1"
    assert body["processing_backlog"] == {
        "all_idle": False,
        "total_pending": 16,
        "l2": {
            "extract_pending": 7,
            "extract_active": 0,
            "reconcile_pending": 3,
            "reconcile_active": 0,
            "snapshot_pending": 3,
            "snapshot_active": 0,
            "projection_pending": 5,
            "projection_claimed": 2,
            "projection_failed": 1,
        },
        "l2_edge_embeddings": {
            "pending": 0,
        },
        "l1_embeddings": {
            "pending": 0,
            "queued": 0,
            "active": 0,
            "worker_running": False,
            "vector_enabled": False,
            "async_embeddings": False,
        },
        "l3_embeddings": {
            "pending": 3,
            "queued": 3,
            "active": 0,
            "worker_running": True,
            "vector_enabled": True,
            "async_embeddings": True,
        },
        "l4_embeddings": {
            "pending": 0,
            "queued": 0,
            "active": 0,
            "worker_running": False,
            "vector_enabled": False,
            "async_embeddings": False,
        },
    }
    assert {
        "validation_states": ["tentative", "contradicted"],
        "include_expired": False,
        "include_inactive": False,
    } in fake_memory.l2.count_assertion_kwargs
    assert any(
        call.get("temporal_clause", (None, []))[0] == "first_inferred_at >= ?"
        and call.get("include_expired") is False
        and call.get("include_inactive") is False
        for call in fake_memory.l2.count_assertion_kwargs
    )
    assert fake_memory.l2.list_assertion_kwargs == {
        "validation_states": ["tentative", "contradicted"],
        "include_expired": False,
        "include_inactive": False,
        "limit": 4,
        "offset": 0,
    }


def test_dashboard_pending_list_excludes_superseded_rows_from_real_store(tmp_path, monkeypatch):
    import asyncio
    import sqlite3
    from _shared.memory_schema import apply_memory_shared_schema
    from magi.memory.l2.store import L2CognitionStore

    db_path = str(tmp_path / "l2.db")
    asyncio.run(apply_memory_shared_schema(db_path))
    store = L2CognitionStore(db_path=db_path)

    async def seed():
        await store.initialize()

        def candidate(value, trait="preferred_language"):
            return {
                "entity_id": "user:local_user",
                "entity_type": "user",
                "trait_family": "technical_profile",
                "trait_name": trait,
                "trait_value": value,
                "confidence_score": 0.4,
                "evidence_events": ["event-" + value],
                "volatility_index": 0.2,
                "source_domain": "user_authored",
                "inference_depth": "explicit",
                "validation_state": "tentative",
                "first_inferred_at": 1710000000.0,
                "last_validated_at": 1710000000.0,
                "target_scope": "entity_bound",
                "target_entity_id": "topic:language",
                "target_entity_type": "topic",
                "temporal_scope": "stable",
                "decay_policy": "evidence_only",
                "decay_anchor_at": 1710000000.0,
            }

        old_id = await store.upsert_assertion_candidate(candidate("Python"))
        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE tom_trait_assertions SET status='superseded', validation_state='contradicted' WHERE assertion_id=?",
                (old_id,),
            )
        current_id = await store.upsert_assertion_candidate(candidate("Rust"))
        pending_id = await store.upsert_assertion_candidate(candidate("Go", "secondary_language"))
        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE tom_trait_assertions SET superseded_by=? WHERE assertion_id=?",
                (current_id, old_id),
            )
            db.execute(
                "UPDATE tom_trait_assertions SET status='stable', validation_state='stable' WHERE assertion_id=?",
                (current_id,),
            )
        historical = await store.list_tom_assertions(
            validation_states=["tentative", "contradicted"],
            include_inactive=True,
            include_expired=False,
            limit=20,
        )
        assert {row["assertion_id"] for row in historical} == {old_id, pending_id}
        return pending_id

    pending_id = asyncio.run(seed())
    memory = _FakeUnifiedMemory()
    memory.l2 = store
    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: memory)
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    with TestClient(app) as client:
        response = client.get("/api/memory/dashboard", params={"pending_limit": 4})
    assert response.status_code == 200
    pending = response.json()["pending_assertions"]
    assert pending["total"] == 1
    assert [item["assertion_id"] for item in pending["items"]] == [pending_id]
    assert pending["items"][0].get("conflict_context") is None
