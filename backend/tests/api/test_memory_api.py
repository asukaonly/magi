from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory import memory_router
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.hybrid_retrieval import RetrievalPayload


class _FakeL0Store:
    checkpoint_db_path = "/tmp/l0.db"
    _sessions: dict = {}
    _goal_stack: dict = {}
    _active_entities: dict = {}
    _temporary_tactics: dict = {}

    async def clear(self):
        return 3


class _FakeL1Store:
    db_path = "/tmp/l1.db"

    async def count_events(self):
        return 12

    async def query_events(self, *, session_id=None, user_id=None, event_type=None, limit=50):
        _ = (session_id, user_id, event_type, limit)
        return [
            MemoryEvent(
                event_id="evt-1",
                correlation_id="corr-1",
                timestamp=1.0,
                created_at=2.0,
                event_type="UserMessage",
                source="chat",
                source_item_id=None,
                memory_domain=MemoryDomain.INTERACTION,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=True,
                tom_depth=TomDepth.NONE,
                retention_class=RetentionClass.COMPRESSIBLE,
                session_id="session-1",
                turn_id="turn-1",
                user_id="web_user",
                task_id=None,
                content="hello",
                author_type="user",
                content_type="text",
                importance_score=0.8,
                level=20,
                media_path=None,
            )
        ]

    async def clear(self):
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

    async def clear(self):
        return 5


class _FakeL2EntityCatalog:
    async def list_entities(self, limit: int = 100):
        _ = limit
        return [{"entity_id": "user:u1", "canonical_name": "User U1", "entity_type": "user", "aliases": []}]

    async def list_mentions(self, limit: int = 100):
        _ = limit
        return [{"mention_id": 1, "mention_text": "魔都", "resolved_entity_id": "place:shanghai"}]

    async def clear(self):
        return 5


class _FakeL3Store:
    db_path = "/tmp/l3.db"

    async def list_summaries(self, limit: int = 100):
        _ = limit
        return [
            {"summary_id": "sum-1", "summary_type": "insight", "summary_category": "state_change"},
            {"summary_id": "sum-2", "summary_type": "insight", "summary_category": "trend_shift"},
            {"summary_id": "sum-3", "summary_type": "thematic", "summary_category": "topic"},
        ]

    async def clear(self):
        return 2


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

    async def clear(self):
        return 1


class _FakeUnifiedMemory:
    def __init__(self):
        self.l0 = _FakeL0Store()
        self.l1 = _FakeL1Store()
        self.l2 = _FakeL2Store()
        self.l2_entity_catalog = _FakeL2EntityCatalog()
        self.l3 = _FakeL3Store()
        self.l4 = _FakeL4Store()
        self.ingested_events: list = []

    async def get_statistics(self):
        return {
            "l0": {"checkpoint_db_path": "/tmp/l0.db"},
            "l1": {"event_count": 12},
            "l2": {"db_path": "/tmp/l2.db"},
            "l3": {"db_path": "/tmp/l3.db"},
            "l4": {"db_path": "/tmp/l4.db"},
        }

    async def ingest_event(self, event):
        self.ingested_events.append(event)
        return {
            "event_id": f"evt-{len(self.ingested_events)}",
            "ingest_target": "l1_only",
            "l1_written": True,
        }

    async def ingest_manual_l2_event(self, request):
        return {"event_id": "evt-manual-1", "queued": True, "source": request.source}

    async def replay_l2_extraction(self, event_id: str):
        return event_id == "evt-manual-1"

    async def reconcile_entities(self, entity_ids: list[str]):
        return bool(entity_ids)

    async def refresh_l2_snapshots(self, entity_ids: list[str]):
        return bool(entity_ids)

    def get_l2_pipeline_stats(self):
        return {
            "is_running": True,
            "extract_enqueued": 4,
            "extract_completed": 3,
            "extract_failed": 0,
            "extract_skipped": 2,
            "reconcile_enqueued": 1,
            "reconcile_completed": 1,
            "reconcile_failed": 0,
            "snapshot_enqueued": 1,
            "snapshot_completed": 1,
            "snapshot_failed": 0,
            "relations_written": 2,
            "assertions_written": 1,
            "extract_by_evidence_class": {
                "user_self_report": 2,
                "assistant_freeform": 1,
                "assistant_tool_grounded": 1,
            },
            "skip_by_reason": {
                "assistant_freeform": 1,
                "assistant_tool_grounded": 1,
            },
        }


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


def test_memory_eval_replay_api_writes_records(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    fake_memory = _FakeUnifiedMemory()
    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: fake_memory)
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.post(
        "/api/memory/eval/replay",
        json={
            "namespace": "benchmark/longmemeval/run-1/q-1",
            "records": [
                {
                    "namespace": "benchmark/longmemeval/run-1/q-1",
                    "session_id": "sess-1",
                    "turn_id": "sess-1:turn-1",
                    "timestamp": 1.0,
                    "role": "user",
                    "content": "I like pasta.",
                    "metadata": {"source_dataset": "longmemeval"},
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["written"] == 1
    assert body["namespace"] == "benchmark/longmemeval/run-1/q-1"
    assert fake_memory.ingested_events[0].data["turn_id"] == "sess-1:turn-1"


def test_memory_eval_query_api_returns_normalized_hits(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    class _FakeHybridRetrievalService:
        async def query(self, request):
            _ = request
            return SimpleNamespace(
                l1_events=[
                    {
                        "event_id": "evt-1",
                        "session_id": "sess-2",
                        "content": "Actually sushi is my favorite.",
                        "score": 0.99,
                        "turn_id": "sess-2:turn-1",
                    }
                ],
                trace={"intent_source": "rule"},
            )

    monkeypatch.setattr("magi.api.routers.memory._resolve_hybrid_retrieval_service", lambda: _FakeHybridRetrievalService())

    client = TestClient(app)
    response = client.post(
        "/api/memory/eval/query",
        json={
            "namespace": "benchmark/longmemeval/run-1/q-1",
            "query": "What food do I prefer?",
            "top_k": 10,
            "mode": "auto",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["retrieved_session_ids"] == ["sess-2"]
    assert body["retrieved_turn_ids"] == ["sess-2:turn-1"]
    assert body["trace"]["intent_source"] == "rule"


def test_memory_eval_query_api_can_answer_with_llm(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")
    log_calls: list[tuple[str, dict]] = []

    class _FakeHybridRetrievalService:
        async def query(self, request):
            _ = request
            return SimpleNamespace(
                l1_events=[
                    {
                        "event_id": "evt-1",
                        "session_id": "sess-2",
                        "content": "Actually sushi is my favorite.",
                        "score": 0.99,
                        "turn_id": "sess-2:turn-1",
                    }
                ],
                trace={"intent_source": "rule"},
            )

    class _FakeLLMAdapter:
        async def chat(self, messages, max_tokens=None, temperature=0.7, **kwargs):
            _ = (max_tokens, temperature, kwargs)
            assert "What food do I prefer?" in messages[-1]["content"]
            assert "Actually sushi is my favorite." in messages[-1]["content"]
            return "Sushi"

    class _FakeLLMPool:
        def get(self, scenario):
            _ = scenario
            return _FakeLLMAdapter()

    def fake_log(message, **kwargs):
        log_calls.append((message, kwargs))

    monkeypatch.setattr("magi.api.routers.memory._resolve_hybrid_retrieval_service", lambda: _FakeHybridRetrievalService())
    monkeypatch.setattr("magi.api.routers.memory._resolve_scenario_llm_pool", lambda: _FakeLLMPool())
    monkeypatch.setattr("magi.api.routers.memory.logger.info", fake_log)

    client = TestClient(app)
    response = client.post(
        "/api/memory/eval/query",
        json={
            "namespace": "benchmark/longmemeval/run-1/q-1",
            "query": "What food do I prefer?",
            "top_k": 10,
            "mode": "auto",
            "answer_with_llm": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Sushi"
    assert body["answer_trace"]["answer_source"] == "llm"
    assert [message for message, _ in log_calls] == [
        "Eval query answer synthesis started",
        "Eval query answer synthesis completed",
    ]
    assert log_calls[0][1]["evidence_hit_count"] == 1
    assert log_calls[1][1]["answer"] == "Sushi"


def test_memory_search_api_uses_runtime_hybrid_retrieval_service(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    class _FakeHybridRetrievalService:
        async def query(self, request):
            assert request.query == "switch jobs"
            return RetrievalPayload(
                l0_workbench=[{"summary": "Current goal"}],
                l1_events=[],
                l2_entity_cards=[],
                l2_relationships=[],
                l2_assertions=[],
                l3_reflections=[{"summary_id": "sum-1"}],
                l4_procedures=[],
                trace={"intent_source": "rule"},
            )

    monkeypatch.setattr("magi.api.routers.memory._resolve_hybrid_retrieval_service", lambda: _FakeHybridRetrievalService())

    client = TestClient(app)
    response = client.post(
        "/api/memory/search",
        json={"query": "switch jobs", "query_mode": "summary", "limit": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["l0_workbench"][0]["summary"] == "Current goal"
    assert body["l3_reflections"][0]["summary_id"] == "sum-1"
    assert body["trace"]["intent_source"] == "rule"


def test_memory_eval_finalize_replay_api_generates_summaries_and_returns_l2_stats(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    fake_memory = _FakeUnifiedMemory()

    async def _generate_summary(period_type: str):
        return {"summary_id": f"sum-{period_type}-1", "summary_category": period_type}

    fake_memory.generate_summary = _generate_summary
    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: fake_memory)
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.post(
        "/api/memory/eval/finalize-replay",
        json={"period_types": ["hour", "day", "week", "month"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summaries"]["hour"]["summary_id"] == "sum-hour-1"
    assert body["summaries"]["month"]["summary_id"] == "sum-month-1"
    assert body["l2_pipeline_stats"]["extract_completed"] == 3


def test_memory_l3_summaries_api_filters_type_and_category(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: _FakeUnifiedMemory())
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get(
        "/api/memory/l3/summaries",
        params={"summary_type": "insight", "summary_category": "state_change"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["summary_id"] for item in body] == ["sum-1"]


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


def test_memory_l2_statistics_api_exposes_pipeline_breakdown(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: _FakeUnifiedMemory())
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get("/api/memory/l2/statistics")

    assert response.status_code == 200
    body = response.json()
    assert body["is_running"] is True
    assert body["relation_count"] == 0
    assert body["assertion_count"] == 0
    assert body["extract_enqueued"] == 4
    assert body["extract_completed"] == 3
    assert body["extract_failed"] == 0
    assert body["extract_skipped"] == 2
    assert body["reconcile_enqueued"] == 1
    assert body["reconcile_completed"] == 1
    assert body["reconcile_failed"] == 0
    assert body["snapshot_enqueued"] == 1
    assert body["snapshot_completed"] == 1
    assert body["snapshot_failed"] == 0
    assert body["relations_written"] == 2
    assert body["assertions_written"] == 1
    assert body["extract_by_evidence_class"]["assistant_freeform"] == 1
    assert body["skip_by_reason"]["assistant_tool_grounded"] == 1


def test_memory_l2_pending_api_reports_queue_backlog(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: _FakeUnifiedMemory())
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get("/api/memory/l2/pending")

    assert response.status_code == 200
    body = response.json()
    assert body["is_running"] is True
    assert body["extract_pending"] == 0
    assert body["reconcile_pending"] == 0
    assert body["snapshot_pending"] == 0


def test_memory_clear_api_clears_all_layers(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    class _FakeChatReadService:
        def clear_all_sessions(self) -> int:
            return 4

    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: _FakeUnifiedMemory())
    monkeypatch.setattr("magi.api.routers.memory.get_chat_read_service", lambda: _FakeChatReadService())

    client = TestClient(app)
    response = client.delete("/api/memory/clear")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["results"]["l0"]["count"] == 3
    assert body["results"]["l1"]["count"] == 12
    assert body["results"]["l2"]["count"] == 10
    assert body["results"]["l3"]["count"] == 2
    assert body["results"]["l4"]["count"] == 1
    assert body["results"]["chat_context"]["count"] == 4


def test_memory_l1_events_api_returns_canonical_user_and_content(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: _FakeUnifiedMemory())
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get("/api/memory/l1/events")

    assert response.status_code == 200
    body = response.json()
    assert body["events"][0]["user_id"] == "web_user"
    assert body["events"][0]["content"] == "hello"
    assert body["events"][0]["memory_domain"] == "interaction"
    assert body["events"][0]["retention_class"] == "compressible"


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
