from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import register_api_routes
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

    def __init__(self):
        self.last_query_kwargs = None

    async def count_events(self):
        return 12

    async def query_events(
        self,
        *,
        session_id=None,
        user_id=None,
        event_type=None,
        query=None,
        source_filters=None,
        source_item_id=None,
        idempotency_key=None,
        start_time=None,
        end_time=None,
        limit=50,
        offset=0,
        include_metadata_json=True,
        include_embedding_fields=True,
    ):
        self.last_query_kwargs = {
            "session_id": session_id,
            "user_id": user_id,
            "event_type": event_type,
            "query": query,
            "source_filters": source_filters,
            "source_item_id": source_item_id,
            "idempotency_key": idempotency_key,
            "start_time": start_time,
            "end_time": end_time,
            "limit": limit,
            "offset": offset,
            "include_metadata_json": include_metadata_json,
            "include_embedding_fields": include_embedding_fields,
        }
        return [
            MemoryEvent(
                id=101,
                event_id="evt-1",
                correlation_id="corr-1",
                timestamp=1.0,
                created_at=2.0,
                event_type="UserMessage",
                source="chat",
                source_item_id=None,
                idempotency_key="chat:session-1:turn-1",
                memory_domain=MemoryDomain.INTERACTION,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=True,
                tom_depth=TomDepth.NONE,
                retention_class=RetentionClass.COMPRESSIBLE,
                session_id="session-1",
                turn_id="turn-1",
                user_id="local_user",
                task_id=None,
                content="hello",
                author_type="user",
                content_type="text",
                importance_score=0.8,
                level=20,
                media_path=None,
                metadata_json={"timeline": {"source_app": "Chrome", "title": "hello"}},
            )
        ]

    async def clear(self):
        return 12

    def get_statistics(self):
        return {
            "db_path": self.db_path,
            "vector_enabled": True,
            "async_embeddings": True,
            "embedding_queue_size": 7,
            "embedding_worker_running": True,
        }


class _FakeL2Store:
    db_path = "/tmp/l2.db"

    async def count_relationships(self):
        return 0

    async def count_tom_assertions(self):
        return 0

    async def get_relationships(self, limit: int = 100, offset: int = 0):
        return []

    async def list_tom_assertions(self, limit: int = 100, offset: int = 0):
        return []

    async def count_tom_snapshots(self):
        return 1

    async def list_tom_snapshots(self, limit: int = 100, offset: int = 0):
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
    async def count_entities(self):
        return 1

    async def list_entities(self, limit: int = 100, offset: int = 0):
        _ = limit
        return [{"entity_id": "user:u1", "canonical_name": "User U1", "entity_type": "user", "aliases": []}]

    async def count_mentions(self):
        return 1

    async def list_mentions(self, limit: int = 100, offset: int = 0):
        _ = limit
        return [{"mention_id": 1, "mention_text": "魔都", "resolved_entity_id": "place:shanghai"}]

    async def clear(self):
        return 5


class _FakeL3Store:
    db_path = "/tmp/l3.db"

    async def count_summaries(self):
        return 3

    async def list_summaries(self, limit: int = 100, offset: int = 0):
        _ = limit
        return [
            {"summary_id": "sum-1", "summary_type": "insight", "summary_category": "state_change"},
            {"summary_id": "sum-2", "summary_type": "insight", "summary_category": "trend_shift"},
            {"summary_id": "sum-3", "summary_type": "thematic", "summary_category": "topic"},
        ]

    async def clear(self):
        return 2

    def get_statistics(self):
        return {
            "db_path": self.db_path,
            "vector_enabled": True,
            "async_embeddings": True,
            "embedding_queue_size": 3,
            "embedding_worker_running": True,
        }


class _FakeL4Store:
    db_path = "/tmp/l4.db"

    async def count_skills(self):
        return 1

    async def get_all_skills(self, limit: int = 100, offset: int = 0):
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

    def get_statistics(self):
        return {
            "db_path": self.db_path,
            "vector_enabled": True,
            "async_embeddings": True,
            "embedding_queue_size": 0,
            "embedding_worker_running": False,
        }


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

    async def flush_l2_microbatches(self):
        return 2

    async def get_l2_projection_backlog(self):
        return {
            "pending": 5,
            "claimed": 2,
            "completed": 9,
            "failed": 1,
        }

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


def test_l0_sessions_api_prefers_chat_summary_titles_and_short_ids(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    fake_memory = _FakeUnifiedMemory()
    fake_memory.l0._sessions = {
        "379f666d-aee9-48fb-ab88-50690496297b": {
            "session_id": "379f666d-aee9-48fb-ab88-50690496297b",
            "user_id": "local_user",
            "status": "active",
            "started_at": 1710000000.0,
            "last_active_at": 1710000300.0,
            "metadata": {},
        }
    }
    fake_memory.l0._goal_stack = {"379f666d-aee9-48fb-ab88-50690496297b": []}
    fake_memory.l0._active_entities = {"379f666d-aee9-48fb-ab88-50690496297b": {}}
    fake_memory.l0._temporary_tactics = {"379f666d-aee9-48fb-ab88-50690496297b": {}}

    class _FakeChatReadService:
        async def aget_session_summaries_batch(self, user_id: str, session_ids: list):
            assert user_id == "local_user"
            assert "379f666d-aee9-48fb-ab88-50690496297b" in session_ids
            return {
                "379f666d-aee9-48fb-ab88-50690496297b": SimpleNamespace(
                    title="记忆设置整理",
                    last_user_message_preview="把通用记忆设置里的 UUID 展示优化掉",
                    workspace_path="/Users/asuka/code/magi",
                ),
            }

    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: fake_memory)
    monkeypatch.setattr("magi.api.routers.memory.get_chat_read_service", lambda: _FakeChatReadService())

    client = TestClient(app)
    response = client.get("/api/memory/l0/sessions")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["display_title"] == "记忆设置整理"
    assert body["items"][0]["display_subtitle"] == "把通用记忆设置里的 UUID 展示优化掉"
    assert body["items"][0]["short_session_id"] == "379f666d"
    assert body["total"] == 1


def test_memory_procedures_api_lists_skills(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: _FakeUnifiedMemory())
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get("/api/memory/procedures")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["skill_name"] == "browser.open"
    assert body["items"][0]["success_rate"] == 0.75
    assert body["total"] == 1


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
            "show_prompt": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Sushi"
    assert body["answer_trace"]["answer_source"] == "llm"
    assert "What food do I prefer?" in body["answer_trace"]["prompt"]
    assert "Actually sushi is my favorite." in body["answer_trace"]["prompt"]
    assert [message for message, _ in log_calls] == [
        "Eval memory query started",
        "Eval memory query completed",
        "Eval query answer synthesis started",
        "Eval query answer synthesis completed",
    ]
    assert log_calls[1][1]["hit_count"] == 1
    assert log_calls[2][1]["evidence_hit_count"] == 1
    assert log_calls[3][1]["answer"] == "Sushi"


def test_memory_eval_query_api_uses_evidence_bundles_for_answer_synthesis(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    class _FakeHybridRetrievalService:
        async def query(self, request):
            _ = request
            return SimpleNamespace(
                l1_events=[
                    {
                        "event_id": "evt-issue",
                        "session_id": "sess-car",
                        "content": "The GPS issue was resolved quickly.",
                        "score": 0.5,
                        "turn_id": "sess-car:turn-5",
                    }
                ],
                l1_evidence_bundles=[
                    {
                        "session_id": "sess-car",
                        "hit_event_ids": ["evt-issue"],
                        "hit_turn_ids": ["sess-car:turn-5"],
                        "neighbor_expansion_applied": True,
                        "events": [
                            {
                                "event_id": "evt-service",
                                "turn_id": "sess-car:turn-1",
                                "timestamp": 1.0,
                                "author_type": "user",
                                "content": "I got my new car serviced for the first time on March 15th.",
                            },
                            {
                                "event_id": "evt-issue",
                                "turn_id": "sess-car:turn-3",
                                "timestamp": 3.0,
                                "author_type": "user",
                                "content": "After the first service, the GPS system stopped working correctly.",
                            },
                        ],
                    }
                ],
                trace={"intent_source": "rule"},
            )

    class _FakeLLMAdapter:
        async def chat(self, messages, max_tokens=None, temperature=0.7, **kwargs):
            _ = (max_tokens, temperature, kwargs)
            prompt = messages[-1]["content"]
            assert "Session Evidence Bundles" in prompt
            assert "After the first service, the GPS system stopped working correctly." in prompt
            return "GPS system not functioning correctly"

    class _FakeLLMPool:
        def get(self, scenario):
            _ = scenario
            return _FakeLLMAdapter()

    monkeypatch.setattr("magi.api.routers.memory._resolve_hybrid_retrieval_service", lambda: _FakeHybridRetrievalService())
    monkeypatch.setattr("magi.api.routers.memory._resolve_scenario_llm_pool", lambda: _FakeLLMPool())

    client = TestClient(app)
    response = client.post(
        "/api/memory/eval/query",
        json={
            "namespace": "benchmark/longmemeval/run-1/q-1",
            "query": "What was the first issue I had with my new car after its first service?",
            "top_k": 10,
            "mode": "auto",
            "answer_with_llm": True,
            "show_prompt": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "GPS system not functioning correctly"
    assert "Session Evidence Bundles" in body["answer_trace"]["prompt"]


def test_memory_eval_query_api_uses_timeline_summary_for_answer_synthesis(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    class _FakeHybridRetrievalService:
        async def query(self, request):
            _ = request
            return SimpleNamespace(
                l1_events=[
                    {
                        "event_id": "evt-issue",
                        "session_id": "sess-car",
                        "content": "After the first service, the GPS system stopped working correctly.",
                        "score": 0.9,
                        "turn_id": "sess-car:turn-3",
                    }
                ],
                l1_evidence_bundles=[
                    {
                        "session_id": "sess-car",
                        "hit_event_ids": ["evt-issue"],
                        "hit_turn_ids": ["sess-car:turn-3"],
                        "neighbor_expansion_applied": True,
                        "events": [
                            {
                                "event_id": "evt-service",
                                "turn_id": "sess-service:turn-1",
                                "timestamp": 1.0,
                                "author_type": "user",
                                "content": "I got my new car serviced for the first time on March 15th.",
                            },
                            {
                                "event_id": "evt-issue",
                                "turn_id": "sess-car:turn-3",
                                "timestamp": 3.0,
                                "author_type": "user",
                                "content": "After the first service, the GPS system stopped working correctly.",
                            },
                        ],
                    }
                ],
                l1_timeline_summary=[
                    {
                        "timestamp": 1.0,
                        "session_id": "sess-service",
                        "turn_id": "sess-service:turn-1",
                        "author_type": "user",
                        "summary": "First service completed for the new car.",
                        "supporting_event_ids": ["evt-service"],
                        "reason_codes": ["temporal_anchor"],
                    },
                    {
                        "timestamp": 3.0,
                        "session_id": "sess-car",
                        "turn_id": "sess-car:turn-3",
                        "author_type": "user",
                        "summary": "GPS system stopped working correctly after the first service.",
                        "supporting_event_ids": ["evt-issue"],
                        "reason_codes": ["event_statement", "quoted_phrase_hit"],
                    },
                ],
                trace={"intent_source": "rule", "l1_timeline_summary_count": 2},
            )

    class _FakeLLMAdapter:
        async def chat(self, messages, max_tokens=None, temperature=0.7, **kwargs):
            _ = (max_tokens, temperature, kwargs)
            prompt = messages[-1]["content"]
            assert "Timeline Summary" in prompt
            assert "First service completed for the new car." in prompt
            assert "GPS system stopped working correctly after the first service." in prompt
            return "GPS system not functioning correctly"

    class _FakeLLMPool:
        def get(self, scenario):
            _ = scenario
            return _FakeLLMAdapter()

    monkeypatch.setattr("magi.api.routers.memory._resolve_hybrid_retrieval_service", lambda: _FakeHybridRetrievalService())
    monkeypatch.setattr("magi.api.routers.memory._resolve_scenario_llm_pool", lambda: _FakeLLMPool())

    client = TestClient(app)
    response = client.post(
        "/api/memory/eval/query",
        json={
            "namespace": "benchmark/longmemeval/run-1/q-1",
            "query": "What was the first issue I had with my new car after its first service?",
            "top_k": 10,
            "mode": "auto",
            "answer_with_llm": True,
            "show_prompt": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "GPS system not functioning correctly"
    assert body["answer_trace"]["evidence_timeline_count"] == 2
    assert "Timeline Summary" in body["answer_trace"]["prompt"]


def test_memory_eval_query_api_guides_llm_to_compare_relative_time_expressions(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    class _FakeHybridRetrievalService:
        async def query(self, request):
            _ = request
            return SimpleNamespace(
                l1_events=[
                    {
                        "event_id": "evt-webinar",
                        "session_id": "sess-webinar",
                        "content": 'I participated in the "Data Analysis using Python" webinar two months ago.',
                        "score": 0.8,
                        "turn_id": "sess-webinar:turn-3",
                    },
                    {
                        "event_id": "evt-workshop",
                        "session_id": "sess-workshop",
                        "content": 'I attended the "Effective Time Management" workshop last Saturday.',
                        "score": 0.8,
                        "turn_id": "sess-workshop:turn-11",
                    },
                ],
                l1_evidence_bundles=[
                    {
                        "session_id": "sess-webinar",
                        "hit_event_ids": ["evt-webinar"],
                        "hit_turn_ids": ["sess-webinar:turn-3"],
                        "neighbor_expansion_applied": True,
                        "events": [
                            {
                                "event_id": "evt-webinar",
                                "turn_id": "sess-webinar:turn-3",
                                "timestamp": 15.0,
                                "author_type": "user",
                                "content": 'I participated in the "Data Analysis using Python" webinar two months ago.',
                            }
                        ],
                    },
                    {
                        "session_id": "sess-workshop",
                        "hit_event_ids": ["evt-workshop"],
                        "hit_turn_ids": ["sess-workshop:turn-11"],
                        "neighbor_expansion_applied": True,
                        "events": [
                            {
                                "event_id": "evt-workshop",
                                "turn_id": "sess-workshop:turn-11",
                                "timestamp": 11.0,
                                "author_type": "user",
                                "content": 'I attended the "Effective Time Management" workshop last Saturday.',
                            }
                        ],
                    },
                ],
                l1_timeline_summary=[
                    {
                        "timestamp": 11.0,
                        "session_id": "sess-workshop",
                        "turn_id": "sess-workshop:turn-11",
                        "author_type": "user",
                        "summary": 'I attended the "Effective Time Management" workshop last Saturday.',
                        "supporting_event_ids": ["evt-workshop"],
                        "reason_codes": ["quoted_span_match", "temporal_anchor"],
                    },
                    {
                        "timestamp": 15.0,
                        "session_id": "sess-webinar",
                        "turn_id": "sess-webinar:turn-3",
                        "author_type": "user",
                        "summary": 'I participated in the "Data Analysis using Python" webinar two months ago.',
                        "supporting_event_ids": ["evt-webinar"],
                        "reason_codes": ["quoted_span_match", "temporal_anchor"],
                    },
                ],
                trace={"intent_source": "rule_fallback", "l1_timeline_summary_count": 2},
            )

    class _FakeLLMAdapter:
        async def chat(self, messages, max_tokens=None, temperature=0.7, **kwargs):
            _ = (max_tokens, temperature, kwargs)
            prompt = messages[-1]["content"]
            assert "Use relative time expressions in the evidence when comparing event order." in prompt
            assert "Do not rely only on replay timestamps if the content itself gives a clearer time relation." in prompt
            return '"Data Analysis using Python" webinar'

    class _FakeLLMPool:
        def get(self, scenario):
            _ = scenario
            return _FakeLLMAdapter()

    monkeypatch.setattr("magi.api.routers.memory._resolve_hybrid_retrieval_service", lambda: _FakeHybridRetrievalService())
    monkeypatch.setattr("magi.api.routers.memory._resolve_scenario_llm_pool", lambda: _FakeLLMPool())

    client = TestClient(app)
    response = client.post(
        "/api/memory/eval/query",
        json={
            "namespace": "benchmark/longmemeval/run-1/q-1",
            "query": "Which event did I attend first, the 'Effective Time Management' workshop or the 'Data Analysis using Python' webinar?",
            "top_k": 10,
            "mode": "auto",
            "answer_with_llm": True,
            "show_prompt": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == '"Data Analysis using Python" webinar'
    assert "Use relative time expressions in the evidence when comparing event order." in body["answer_trace"]["prompt"]


def test_memory_eval_query_api_prioritizes_timeline_over_noisy_bundles(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    noisy_assistant_text = (
        "Here are some top-notch resources to help you learn data visualization in Python: "
        "Matplotlib, Seaborn, Plotly, and many more options for dashboarding and storytelling."
    )

    class _FakeHybridRetrievalService:
        async def query(self, request):
            _ = request
            return SimpleNamespace(
                l1_events=[
                    {
                        "event_id": "evt-webinar",
                        "session_id": "sess-webinar",
                        "content": 'I participated in the "Data Analysis using Python" webinar two months ago.',
                        "score": 0.8,
                        "turn_id": "sess-webinar:turn-3",
                    },
                    {
                        "event_id": "evt-workshop",
                        "session_id": "sess-workshop",
                        "content": 'I attended the "Effective Time Management" workshop last Saturday.',
                        "score": 0.8,
                        "turn_id": "sess-workshop:turn-11",
                    },
                ],
                l1_evidence_bundles=[
                    {
                        "session_id": "sess-webinar",
                        "hit_event_ids": ["evt-webinar"],
                        "hit_turn_ids": ["sess-webinar:turn-3"],
                        "neighbor_expansion_applied": True,
                        "events": [
                            {
                                "event_id": "evt-helper",
                                "turn_id": "sess-webinar:turn-2",
                                "timestamp": 14.0,
                                "author_type": "assistant",
                                "content": noisy_assistant_text,
                            },
                            {
                                "event_id": "evt-webinar",
                                "turn_id": "sess-webinar:turn-3",
                                "timestamp": 15.0,
                                "author_type": "user",
                                "content": 'I participated in the "Data Analysis using Python" webinar two months ago.',
                            },
                        ],
                    },
                    {
                        "session_id": "sess-workshop",
                        "hit_event_ids": ["evt-workshop"],
                        "hit_turn_ids": ["sess-workshop:turn-11"],
                        "neighbor_expansion_applied": True,
                        "events": [
                            {
                                "event_id": "evt-workshop",
                                "turn_id": "sess-workshop:turn-11",
                                "timestamp": 11.0,
                                "author_type": "user",
                                "content": 'I attended the "Effective Time Management" workshop last Saturday.',
                            }
                        ],
                    },
                ],
                l1_timeline_summary=[
                    {
                        "timestamp": 11.0,
                        "session_id": "sess-workshop",
                        "turn_id": "sess-workshop:turn-11",
                        "author_type": "user",
                        "summary": 'I attended the "Effective Time Management" workshop last Saturday.',
                        "supporting_event_ids": ["evt-workshop"],
                        "reason_codes": ["quoted_span_match", "temporal_anchor"],
                    },
                    {
                        "timestamp": 15.0,
                        "session_id": "sess-webinar",
                        "turn_id": "sess-webinar:turn-3",
                        "author_type": "user",
                        "summary": 'I participated in the "Data Analysis using Python" webinar two months ago.',
                        "supporting_event_ids": ["evt-webinar"],
                        "reason_codes": ["quoted_span_match", "temporal_anchor"],
                    },
                ],
                trace={"intent_source": "rule_fallback", "l1_timeline_summary_count": 2},
            )

    class _FakeLLMAdapter:
        async def chat(self, messages, max_tokens=None, temperature=0.7, **kwargs):
            _ = (max_tokens, temperature, kwargs)
            assert messages[0]["role"] == "system"
            assert "retrieved memory evidence only" in messages[0]["content"]
            prompt = messages[-1]["content"]
            assert "Answer from the Timeline Summary first for temporal or comparison questions." in prompt
            assert "t=11.0" not in prompt
            assert "t=15.0" not in prompt
            return '"Data Analysis using Python" webinar'

    class _FakeLLMPool:
        def get(self, scenario):
            _ = scenario
            return _FakeLLMAdapter()

    monkeypatch.setattr("magi.api.routers.memory._resolve_hybrid_retrieval_service", lambda: _FakeHybridRetrievalService())
    monkeypatch.setattr("magi.api.routers.memory._resolve_scenario_llm_pool", lambda: _FakeLLMPool())

    client = TestClient(app)
    response = client.post(
        "/api/memory/eval/query",
        json={
            "namespace": "benchmark/longmemeval/run-1/q-1",
            "query": "Which event did I attend first, the 'Effective Time Management' workshop or the 'Data Analysis using Python' webinar?",
            "top_k": 10,
            "mode": "auto",
            "answer_with_llm": True,
            "show_prompt": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == '"Data Analysis using Python" webinar'


def test_memory_eval_query_api_strips_articles_from_short_choice_answers(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    class _FakeHybridRetrievalService:
        async def query(self, request):
            _ = request
            return SimpleNamespace(
                l1_events=[
                    {
                        "event_id": "evt-bike",
                        "session_id": "sess-bike",
                        "content": "I got my bike repaired back in mid-February.",
                        "score": 0.9,
                        "turn_id": "sess-bike:turn-11",
                    },
                    {
                        "event_id": "evt-car",
                        "session_id": "sess-car",
                        "content": "I washed my current Corolla on Monday, February 27th.",
                        "score": 0.8,
                        "turn_id": "sess-car:turn-1",
                    },
                ],
                l1_evidence_bundles=[],
                l1_timeline_summary=[
                    {
                        "timestamp": 11.0,
                        "session_id": "sess-bike",
                        "turn_id": "sess-bike:turn-11",
                        "author_type": "user",
                        "summary": "I got my bike repaired back in mid-February.",
                        "supporting_event_ids": ["evt-bike"],
                        "reason_codes": ["event_statement", "temporal_anchor"],
                    },
                    {
                        "timestamp": 13.0,
                        "session_id": "sess-car",
                        "turn_id": "sess-car:turn-1",
                        "author_type": "user",
                        "summary": "I washed my current Corolla on Monday, February 27th.",
                        "supporting_event_ids": ["evt-car"],
                        "reason_codes": ["event_statement", "temporal_anchor"],
                    },
                ],
                trace={"intent_source": "rule", "l1_timeline_summary_count": 2},
            )

    class _FakeLLMAdapter:
        async def chat(self, messages, max_tokens=None, temperature=0.7, **kwargs):
            _ = (messages, max_tokens, temperature, kwargs)
            return "the bike"

    class _FakeLLMPool:
        def get(self, scenario):
            _ = scenario
            return _FakeLLMAdapter()

    monkeypatch.setattr("magi.api.routers.memory._resolve_hybrid_retrieval_service", lambda: _FakeHybridRetrievalService())
    monkeypatch.setattr("magi.api.routers.memory._resolve_scenario_llm_pool", lambda: _FakeLLMPool())

    client = TestClient(app)
    response = client.post(
        "/api/memory/eval/query",
        json={
            "namespace": "benchmark/longmemeval/run-1/q-1",
            "query": "Which vehicle did I take care of first in February, the bike or the car?",
            "top_k": 10,
            "mode": "auto",
            "answer_with_llm": True,
            "show_prompt": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "the bike"


def test_memory_eval_query_api_logs_full_answer_llm_messages(monkeypatch):
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
            _ = (max_tokens, temperature)
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"
            assert kwargs["disable_thinking"] is True
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
    synthesis_log = next(kwargs for message, kwargs in log_calls if message == "Eval query answer synthesis started")
    logged_messages = synthesis_log["llm_messages"]
    assert "==== SYSTEM MESSAGE ====" in logged_messages
    assert "==== USER MESSAGE ====" in logged_messages
    assert "retrieved memory evidence only" in logged_messages
    assert "What food do I prefer?" in logged_messages
    completed_log = next(kwargs for message, kwargs in log_calls if message == "Eval query answer synthesis completed")
    assert completed_log["raw_answer"] == "Sushi"
    assert completed_log["answer"] == "Sushi"


def test_memory_eval_query_api_logs_retrieval_timing(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")
    log_calls: list[tuple[str, dict]] = []

    class _FakeHybridRetrievalService:
        async def query(self, request):
            assert request.query_mode == "detail"
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

    def fake_log(message, **kwargs):
        log_calls.append((message, kwargs))

    monkeypatch.setattr("magi.api.routers.memory._resolve_hybrid_retrieval_service", lambda: _FakeHybridRetrievalService())
    monkeypatch.setattr("magi.api.routers.memory.logger.info", fake_log)

    client = TestClient(app)
    response = client.post(
        "/api/memory/eval/query",
        json={
            "namespace": "benchmark/longmemeval/run-1/q-1",
            "query": "What food do I prefer?",
            "top_k": 10,
            "mode": "detail",
        },
    )

    assert response.status_code == 200
    assert [message for message, _ in log_calls] == [
        "Eval memory query started",
        "Eval memory query completed",
    ]
    assert log_calls[0][1]["mode"] == "detail"
    assert log_calls[1][1]["mode"] == "detail"
    assert log_calls[1][1]["hit_count"] == 1
    assert "duration_ms" in log_calls[1][1]


def test_memory_eval_query_api_supports_l1_only_fast_path(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    class _ExplodingHybridRetrievalService:
        async def query(self, request):
            _ = request
            raise AssertionError("hybrid retrieval should not be used")

    fake_memory = _FakeUnifiedMemory()

    monkeypatch.setattr("magi.api.routers.memory._resolve_hybrid_retrieval_service", lambda: _ExplodingHybridRetrievalService())
    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: fake_memory)

    client = TestClient(app)
    response = client.post(
        "/api/memory/eval/query",
        json={
            "namespace": "benchmark/longmemeval/run-1/q-1",
            "query": "hello",
            "top_k": 5,
            "mode": "l1_only",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["hits"][0]["event_id"] == "evt-1"
    assert body["trace"]["intent_source"] == "eval_l1_only"


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
    assert [item["summary_id"] for item in body["items"]] == ["sum-1"]
    assert body["total"] == 3


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
    flush_response = client.post("/api/memory/l2/microbatch-flush")
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
    assert entities_response.json()["items"][0]["entity_id"] == "user:u1"
    assert mentions_response.status_code == 200
    assert mentions_response.json()["items"][0]["mention_text"] == "魔都"
    assert snapshots_response.status_code == 200
    assert snapshots_response.json()["items"][0]["snapshot_id"] == "snapshot-1"
    assert rules_response.status_code == 200
    assert rules_response.json()[0]["predicate"] == "LIKES"
    assert manual_response.status_code == 200
    assert manual_response.json()["event_id"] == "evt-manual-1"
    assert replay_response.status_code == 200
    assert reconcile_response.status_code == 200
    assert materialize_response.status_code == 200
    assert flush_response.status_code == 200
    assert flush_response.json() == {"queued": True, "batch_count": 2}
    assert update_rule_response.status_code == 200
    assert update_rule_response.json()["predicate"] == "ENDORSES"
    assert update_rule_response.json()["exclusive_group"] == "stance"


def test_memory_identity_links_api_returns_empty_payload_when_identity_mapping_is_unavailable(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: _FakeUnifiedMemory())
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get("/api/memory/identity/links")

    assert response.status_code == 200
    assert response.json() == {
        "canonical_self_id": "user:self",
        "links": [],
    }


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
    assert body["projection_backlog"]["pending"] == 5
    assert body["projection_backlog"]["claimed"] == 2


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
    assert body["extract_pending"] == 7
    assert body["reconcile_pending"] == 0
    assert body["snapshot_pending"] == 0
    assert body["projection_pending"] == 5
    assert body["projection_claimed"] == 2
    assert body["projection_failed"] == 1


def test_memory_background_pending_api_reports_embedding_backlog(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: _FakeUnifiedMemory())
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get("/api/memory/background/pending")

    assert response.status_code == 200
    body = response.json()
    assert body["l2"]["extract_pending"] == 7
    assert body["l2"]["projection_pending"] == 5
    assert body["l2"]["projection_claimed"] == 2
    assert body["l1_embeddings"]["pending"] == 7
    assert body["l3_embeddings"]["pending"] == 3
    assert body["l4_embeddings"]["pending"] == 0
    assert body["all_idle"] is False


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


def test_registered_memory_clear_api_is_public(monkeypatch):
    app = FastAPI()
    register_api_routes(app)

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
    assert body["results"]["l1"]["count"] == 12
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
    assert body["items"][0]["user_id"] == "local_user"
    assert body["items"][0]["content"] == "hello"
    assert body["items"][0]["memory_domain"] == "interaction"
    assert body["items"][0]["retention_class"] == "compressible"
    assert body["items"][0]["id"] == 101
    assert body["items"][0]["idempotency_key"] == "chat:session-1:turn-1"
    assert "metadata_json" not in body["items"][0]
    assert "embedding_status" not in body["items"][0]
    assert "embedding_profile_id" not in body["items"][0]
    assert body["total"] == 12


def test_memory_l1_events_api_forwards_search_filters(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    memory = _FakeUnifiedMemory()
    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: memory)
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get(
        "/api/memory/l1/events",
        params={
            "query": "lake",
            "source": "chat_projector",
            "start_date": "2026-03-01",
            "end_date": "2026-03-02",
        },
    )

    assert response.status_code == 200
    assert memory.l1.last_query_kwargs is not None
    assert memory.l1.last_query_kwargs["query"] == "lake"
    assert memory.l1.last_query_kwargs["source_filters"] == ["chat_projector"]
    assert memory.l1.last_query_kwargs["limit"] == 50
    assert memory.l1.last_query_kwargs["include_metadata_json"] is False
    assert memory.l1.last_query_kwargs["include_embedding_fields"] is False
    assert isinstance(memory.l1.last_query_kwargs["start_time"], float)
    assert isinstance(memory.l1.last_query_kwargs["end_time"], float)
    assert memory.l1.last_query_kwargs["end_time"] > memory.l1.last_query_kwargs["start_time"]


def test_memory_l1_events_api_forwards_identity_filters(monkeypatch):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    memory = _FakeUnifiedMemory()
    monkeypatch.setattr("magi.api.routers.memory._resolve_unified_memory", lambda: memory)
    monkeypatch.setattr("magi.api.routers.memory._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get(
        "/api/memory/l1/events",
        params={
            "source_item_id": "chrome:181979-181982",
            "idempotency_key": "default:181979-181982",
        },
    )

    assert response.status_code == 200
    assert memory.l1.last_query_kwargs is not None
    assert memory.l1.last_query_kwargs["source_item_id"] == "chrome:181979-181982"
    assert memory.l1.last_query_kwargs["idempotency_key"] == "default:181979-181982"

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
