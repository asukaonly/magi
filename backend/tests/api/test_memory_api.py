from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

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


class _FakeL2Store:
    db_path = "/tmp/l2.db"

    async def get_relationships(self, limit: int = 100):
        return []

    async def list_tom_assertions(self, limit: int = 100):
        return []

    async def list_tom_snapshots(self, limit: int = 100):
        _ = limit
        return [
            {
                "snapshot_id": "snapshot-1",
                "entity_id": "user:u1",
                "entity_type": "user",
                "core_traits": {"stress_level": "high"},
            }
        ]

    async def get_tom_snapshot(self, *, entity_id: str, entity_type: str):
        if entity_id == "user:u1" and entity_type == "user":
            return {"snapshot_id": "snapshot-1", "entity_id": entity_id, "entity_type": entity_type}
        return None

    async def list_graph_conflict_rules(self):
        return [
            {
                "predicate": "LIKES",
                "opposite_predicates": ["DISLIKES"],
                "opposite_resolution": "mark_deprecated",
                "exclusive_group": None,
                "exclusive_scope": "same_subject",
                "exclusive_resolution": "mark_deprecated",
            }
        ]

    async def upsert_graph_conflict_rule(self, payload):
        return {
            "predicate": payload["predicate"],
            "opposite_predicates": payload.get("opposite_predicates", []),
            "opposite_resolution": payload.get("opposite_resolution", "mark_deprecated"),
            "exclusive_group": payload.get("exclusive_group"),
            "exclusive_scope": payload.get("exclusive_scope", "same_subject"),
            "exclusive_resolution": payload.get("exclusive_resolution", "mark_deprecated"),
        }


class _FakeL2EntityCatalog:
    async def list_entities(self, limit: int = 100):
        _ = limit
        return [{"entity_id": "user:u1", "canonical_name": "User U1", "entity_type": "user", "aliases": []}]

    async def list_mentions(self, limit: int = 100):
        _ = limit
        return [{"mention_id": 1, "mention_text": "魔都", "resolved_entity_id": "place:shanghai"}]


class _FakeL3Store:
    db_path = "/tmp/l3.db"

    async def list_summaries(self, limit: int = 100):
        return []


class _FakeL4Store:
    db_path = "/tmp/l4.db"

    async def get_all_skills(self, limit: int = 100):
        _ = limit
        return [
            {
                "skill_id": "skill-1",
                "skill_name": "browser.open",
                "skill_category": "tool",
                "success_rate": 0.75,
                "total_attempts": 8,
                "circuit_breaker_state": "closed",
            }
        ]


class _FakeUnifiedMemory:
    def __init__(self):
        self.l0 = _FakeL0Store()
        self.l1 = _FakeL1Store()
        self.l2 = _FakeL2Store()
        self.l2_entity_catalog = _FakeL2EntityCatalog()
        self.l3 = _FakeL3Store()
        self.l4 = _FakeL4Store()

    async def get_statistics(self):
        return {
            "l0": {"checkpoint_db_path": "/tmp/l0.db"},
            "l1": {"event_count": 12},
            "l2": {"db_path": "/tmp/l2.db"},
            "l3": {"db_path": "/tmp/l3.db"},
            "l4": {"db_path": "/tmp/l4.db"},
        }

    async def ingest_manual_l2_event(self, request):
        return {"event_id": "evt-manual-1", "queued": True, "source": request.source}

    async def replay_l2_extraction(self, event_id: str):
        return event_id == "evt-manual-1"

    async def reconcile_entities(self, entity_ids: list[str]):
        return bool(entity_ids)

    async def refresh_l2_snapshots(self, entity_ids: list[str]):
        return bool(entity_ids)


def test_memory_statistics_api_reports_new_layers(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: _FakeUnifiedMemory())
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get("/api/memory/statistics")

    assert response.status_code == 200
    body = response.json()
    assert body["l1"]["event_count"] == 12
    assert "l4" in body


def test_memory_procedures_api_lists_skills(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: _FakeUnifiedMemory())
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get("/api/memory/procedures")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["skill_name"] == "browser.open"
    assert body[0]["success_rate"] == 0.75


def test_memory_l2_lab_api_exposes_entities_and_manual_actions(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: _FakeUnifiedMemory())
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)

    entities_response = client.get("/api/memory/l2/entities")
    mentions_response = client.get("/api/memory/l2/mentions")
    snapshots_response = client.get("/api/memory/l2/snapshots")
    rules_response = client.get("/api/memory/l2/conflict-rules")
    manual_response = client.post(
        "/api/memory/l2/manual-event",
        json={"text": "I like Shanghai.", "user_id": "u1", "source": "l2_lab"},
    )
    replay_response = client.post("/api/memory/l2/extract/evt-manual-1")
    reconcile_response = client.post("/api/memory/l2/reconcile", json={"entity_ids": ["user:u1"]})
    materialize_response = client.post("/api/memory/l2/snapshot-refresh", json={"entity_ids": ["user:u1"]})
    update_rule_response = client.put(
        "/api/memory/l2/conflict-rules/ENDORSES",
        json={
            "opposite_predicates": ["REJECTS"],
            "opposite_resolution": "mark_conflicted",
            "exclusive_group": "stance",
            "exclusive_resolution": "mark_conflicted",
        },
    )

    assert entities_response.status_code == 200
    assert entities_response.json()[0]["entity_id"] == "user:u1"
    assert mentions_response.status_code == 200
    assert mentions_response.json()[0]["mention_text"] == "魔都"
    assert snapshots_response.status_code == 200
    assert snapshots_response.json()[0]["snapshot_id"] == "snapshot-1"
    assert rules_response.status_code == 200
    assert rules_response.json()[0]["predicate"] == "LIKES"
    assert manual_response.status_code == 200
    assert manual_response.json()["event_id"] == "evt-manual-1"
    assert replay_response.status_code == 200
    assert reconcile_response.status_code == 200
    assert materialize_response.status_code == 200
    assert update_rule_response.status_code == 200
    assert update_rule_response.json()["predicate"] == "ENDORSES"
    assert update_rule_response.json()["exclusive_group"] == "stance"


def test_memory_l2_conflict_rule_api_rejects_invalid_combinations(monkeypatch):
    class _RejectingL2Store(_FakeL2Store):
        async def upsert_graph_conflict_rule(self, payload):
            raise ValueError("exclusive_group is required when exclusive_resolution overrides the default")

    class _RejectingUnifiedMemory(_FakeUnifiedMemory):
        def __init__(self):
            super().__init__()
            self.l2 = _RejectingL2Store()

    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: _RejectingUnifiedMemory())
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.put(
        "/api/memory/l2/conflict-rules/STANCE",
        json={
            "opposite_predicates": [],
            "opposite_resolution": "mark_deprecated",
            "exclusive_group": None,
            "exclusive_scope": "same_subject",
            "exclusive_resolution": "mark_conflicted",
        },
    )

    assert response.status_code == 422
    assert "exclusive_group" in response.json()["detail"]
