from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory import memory_router


class _FakeL0Store:
    checkpoint_db_path = "/tmp/l0.db"
    _sessions: dict = {}
    _goal_stack: dict = {}
    _active_entities: dict = {}
    _temporary_tactics: dict = {}


class _FakeL1Store:
    db_path = "/tmp/l1.db"

    async def count_events(self):
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
        self.count_assertion_kwargs = None
        self.list_assertion_kwargs = None

    async def count_relationships(self):
        return 4

    async def count_tom_assertions(self, **kwargs):
        if kwargs:
            self.count_assertion_kwargs = kwargs
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


class _FakeL3Store:
    db_path = "/tmp/l3.db"

    async def count_summaries(self):
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


def test_memory_dashboard_route_is_public():
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    assert "/dashboard" in {route.path for route in public.routes}


def test_memory_dashboard_reports_statistics_sources_and_pending(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")
    fake_memory = _FakeUnifiedMemory()
    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: fake_memory)
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get("/api/memory/dashboard", params={"pending_limit": 4})

    assert response.status_code == 200
    body = response.json()
    assert body["statistics"]["total_memories"] == 28
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
            "reconcile_pending": 3,
            "snapshot_pending": 3,
            "projection_pending": 5,
            "projection_claimed": 2,
            "projection_failed": 1,
        },
        "l1_embeddings": {
            "pending": 0,
            "worker_running": False,
            "vector_enabled": False,
            "async_embeddings": False,
        },
        "l3_embeddings": {
            "pending": 3,
            "worker_running": True,
            "vector_enabled": True,
            "async_embeddings": True,
        },
        "l4_embeddings": {
            "pending": 0,
            "worker_running": False,
            "vector_enabled": False,
            "async_embeddings": False,
        },
    }
    assert fake_memory.l2.count_assertion_kwargs == {
        "validation_states": ["tentative", "contradicted"],
        "include_expired": False,
        "include_inactive": False,
    }
    assert fake_memory.l2.list_assertion_kwargs == {
        "validation_states": ["tentative", "contradicted"],
        "include_expired": False,
        "include_inactive": False,
        "limit": 4,
        "offset": 0,
    }
