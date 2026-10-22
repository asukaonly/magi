from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router, register_api_routes
from magi.api.routers.memory import memory_router
from magi.api.routers.memory.overview_routes import _collect_post_clear_diagnostics
from magi.i18n import language_context
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.evidence import L1RetrievalScope
from magi.memory.hybrid_retrieval import RetrievalPayload
from magi.memory.operation_barrier import AsyncOperationBarrier
from magi.memory.portability.errors import MemoryPortabilityError
from magi.plugins.user_content_clear import PluginUserContentClearRecoveryError
from magi.identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID

from _shared.memory_api import MemoryApiStub

FULL_CLEAR_TRANSACTION_ID = "clear-backend-test-transaction"
FULL_CLEAR_HEADERS = {
    "X-Magi-Full-Clear-Transaction": FULL_CLEAR_TRANSACTION_ID,
}


@pytest.mark.asyncio
async def test_post_clear_diagnostics_report_remaining_non_content_counts() -> None:
    l1 = SimpleNamespace(count_events=AsyncMock(return_value=0))
    jobs = [SimpleNamespace(imported_count=0), SimpleNamespace(imported_count=0)]
    history_import_service = SimpleNamespace(list_jobs=AsyncMock(return_value=jobs))

    result = await _collect_post_clear_diagnostics(
        unified_memory=MemoryApiStub(l1=l1),
        history_import_service=history_import_service,
    )

    assert result == (0, 2, 0)
    l1.count_events.assert_awaited_once_with()
    history_import_service.list_jobs.assert_awaited_once_with(limit=100)


@pytest.fixture(autouse=True)
def _isolate_batch_store(monkeypatch):
    store = SimpleNamespace(clear_all=AsyncMock(return_value={"batch_jobs": 0, "batch_items": 0}))
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_batch_store",
        lambda: store,
    )
    return store


@pytest.fixture(autouse=True)
def _isolate_diagnostic_log_cleanup(monkeypatch):
    cleanup = AsyncMock(return_value=SimpleNamespace(cleared_entries=4, failed_entries=0))
    monkeypatch.setattr(
        "magi.api.routers.memory.overview_routes.clear_diagnostic_log_history",
        cleanup,
    )
    return cleanup


@pytest.fixture(autouse=True)
def _isolate_chat_read_service(monkeypatch):
    class _FakeChatReadService:
        async def aclear_all_sessions(self) -> int:
            return 0

        async def acomplete_global_clear(self) -> bool:
            return True

        async def areset_user_turn_delivery_after_failed_clear(self) -> int:
            return 0

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service",
        lambda: _FakeChatReadService(),
    )


@pytest.fixture(autouse=True)
def _isolate_runtime_projection_clear_dependencies(monkeypatch):
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_runtime_trace_subscriber",
        lambda: None,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_llm_usage_subscriber",
        lambda: None,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_llm_usage_store",
        lambda: None,
    )


@pytest.fixture(autouse=True)
def _isolate_memory_portability_clear(monkeypatch):
    clear_private_data = AsyncMock(return_value={})

    class _PortabilityService:
        active = False

        @asynccontextmanager
        async def user_content_clear_boundary(self):
            self.active = True
            try:
                yield clear_private_data
            finally:
                self.active = False

    service = _PortabilityService()
    monkeypatch.setattr(
        "magi.api.routers.memory.overview_routes.get_memory_portability_service",
        lambda: service,
    )
    return service, clear_private_data


@pytest.fixture(autouse=True)
def _isolate_user_message_clear_boundary(monkeypatch):
    class _FakeRuntimeCommandQueue:
        def __init__(self) -> None:
            self.barrier = AsyncOperationBarrier()
            self.generation = 0
            self.advance_calls = 0
            self.full_clear_transaction_id: str | None = None
            self.full_clear_completed_transaction_id: str | None = None

        @asynccontextmanager
        async def user_message_clear_boundary(self):  # type: ignore[no-untyped-def]
            async with self.barrier.exclusive():
                yield

        @asynccontextmanager
        async def user_message_global_clear_boundary(self):  # type: ignore[no-untyped-def]
            async with self.user_message_clear_boundary():
                yield

        async def advance_user_message_generation_and_purge(self) -> tuple[int, int]:
            self.advance_calls += 1
            self.generation += 1
            return self.generation, 0

        async def begin_full_user_content_clear(self, transaction_id: str) -> None:
            self.full_clear_transaction_id = transaction_id
            self.full_clear_completed_transaction_id = None

        async def complete_full_user_content_clear(
            self,
            *,
            transaction_id: str,
        ) -> None:
            if self.full_clear_transaction_id != transaction_id:
                raise RuntimeError("unexpected full-clear transaction")
            self.full_clear_completed_transaction_id = transaction_id

    queue = _FakeRuntimeCommandQueue()
    source_hub = SimpleNamespace(discard_stale_user_messages=AsyncMock(return_value=0))
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_runtime_command_queue",
        lambda: queue,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_source_hub",
        lambda: source_hub,
    )
    return queue, source_hub


@pytest.fixture(autouse=True)
def _isolate_external_conversation_clear_dependencies(monkeypatch):
    class _FakeChannelSessionMapper:
        async def clear_conversation_state(self) -> dict[str, int]:
            return {}

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_outreach_service",
        lambda: None,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_channel_session_mapper",
        lambda: _FakeChannelSessionMapper(),
    )


@pytest.fixture(autouse=True)
def _isolate_chat_memory_projection_clear(monkeypatch):
    @asynccontextmanager
    async def boundary():
        yield

    lifecycle = SimpleNamespace(user_content_clear_boundary=boundary)
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_chat_memory_projection_clear",
        lambda: lifecycle,
    )
    return lifecycle


@pytest.fixture(autouse=True)
def _isolate_background_task_history_cleanup(monkeypatch):
    @asynccontextmanager
    async def boundary(**_kwargs):  # type: ignore[no-untyped-def]
        yield

    manager = SimpleNamespace(
        conversation_scope_boundary=boundary,
        clear_all_history=AsyncMock(
            return_value={
                "tool_effect_attempts": 0,
                "background_tasks": 0,
                "background_task_events": 0,
                "background_task_completion_intents": 0,
            }
        ),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_background_task_manager",
        lambda: manager,
    )
    return manager


@pytest.fixture(autouse=True)
def _isolate_scheduler_clear_boundary(monkeypatch):
    @asynccontextmanager
    async def boundary():
        yield

    service = SimpleNamespace(
        user_data_clear_boundary=boundary,
        clear_user_data=AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_scheduler_service",
        lambda: service,
    )
    return service


@pytest.fixture(autouse=True)
def _isolate_control_user_content_clear_boundary(monkeypatch):
    @asynccontextmanager
    async def boundary():
        yield

    coordinator = SimpleNamespace(user_content_clear_boundary=boundary)
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_control_user_content_clear",
        lambda: coordinator,
    )
    return coordinator


@pytest.fixture(autouse=True)
def _isolate_plugin_user_content_clear_boundary(monkeypatch):
    session = SimpleNamespace(
        mark_surrounding_clear_failed=Mock(),
        clear_user_content=AsyncMock(
            return_value=SimpleNamespace(
                clear_generation=1,
                attempted=0,
                cleared=0,
                failures=(),
            )
        ),
    )

    @asynccontextmanager
    async def boundary():
        yield session

    coordinator = SimpleNamespace(user_content_clear_boundary=boundary)
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_plugin_user_content_clear",
        lambda: coordinator,
    )
    return coordinator, session


class _FakeL0Store:
    checkpoint_db_path = "/tmp/l0.db"
    _sessions: dict = {}
    _attention_items: dict = {}

    async def clear(self):
        return 3

    async def get_session_index_snapshot(self):
        return {
            "sessions": dict(self._sessions),
            "attention_by_session": dict(self._attention_items),
        }

    async def get_workbench(self, session_id: str):
        return {
            "session": self._sessions.get(session_id),
            "attention_items": list(self._attention_items.get(session_id, {}).values()),
        }


class _FakeL1Store:
    db_path = "/tmp/l1.db"

    def __init__(self):
        self.last_query_kwargs = None
        self.last_count_kwargs = None
        self.deleted_event_ids: list[str] = []
        self._deleted_event_id_set: set[str] = set()
        self.bulk_deleted_entity: str | None = None
        self.bulk_deleted_range: tuple[float, float] | None = None

    async def count_events(self, **kwargs):
        self.last_count_kwargs = kwargs
        return 12

    async def query_events(
        self,
        *,
        session_id=None,
        user_id=None,
        event_id=None,
        event_type=None,
        exclude_event_types=None,
        query=None,
        source_filters=None,
        source_item_id=None,
        idempotency_key=None,
        start_time=None,
        end_time=None,
        l1_retrieval_scopes=None,
        limit=50,
        offset=0,
        include_metadata_json=True,
        include_embedding_fields=True,
    ):
        self.last_query_kwargs = {
            "session_id": session_id,
            "user_id": user_id,
            "event_id": event_id,
            "event_type": event_type,
            "exclude_event_types": exclude_event_types,
            "query": query,
            "source_filters": source_filters,
            "source_item_id": source_item_id,
            "idempotency_key": idempotency_key,
            "start_time": start_time,
            "end_time": end_time,
            "l1_retrieval_scopes": l1_retrieval_scopes,
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
                metadata_json={"activity_snapshot": {"source_app": "Chrome", "title": "hello"}},
                embedding_status="ready",
                embedding_profile_id="profile-a",
            )
        ]

    async def clear(self):
        return 12


    async def get_event(self, event_id: str):
        if event_id != "evt-1":
            return None
        return {
            "event_id": event_id,
            "source": "chat",
            "deleted_at": 1.0 if event_id in self._deleted_event_id_set else None,
        }

    async def get_active_event(self, event_id: str):
        event = await self.get_event(event_id)
        if event is None or event["deleted_at"] is not None:
            return None
        return event


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

    def __init__(self):
        self.forgotten_entities: list[str] = []
        self.forgotten_ranges: list[tuple[float, float]] = []
        self.forgotten_source_events: list[str] = []
        self.tombstoned_source_events: list[str] = []
        self.source_event_tombstones: set[str] = set()
        self.relationship_kwargs: dict | None = None
        self.assertion_kwargs: dict | None = None
        self.snapshot_kwargs: dict | None = None
        self.relationship_count_kwargs: dict | None = None
        self.assertion_count_kwargs: dict | None = None
        self.snapshot_count_kwargs: dict | None = None

    async def count_relationships(self, **kwargs):
        self.relationship_count_kwargs = kwargs
        return 0

    async def count_tom_assertions(self, **kwargs):
        self.assertion_count_kwargs = kwargs
        return 0

    async def get_relationships(self, limit: int = 100, offset: int = 0, **kwargs):
        self.relationship_kwargs = {"limit": limit, "offset": offset, **kwargs}
        return []

    async def list_tom_assertions(self, limit: int = 100, offset: int = 0, **kwargs):
        self.assertion_kwargs = {"limit": limit, "offset": offset, **kwargs}
        return []

    async def count_tom_snapshots(self, **kwargs):
        self.snapshot_count_kwargs = kwargs
        return 1

    async def list_tom_snapshots(self, limit: int = 100, offset: int = 0, **kwargs):
        self.snapshot_kwargs = {"limit": limit, "offset": offset, **kwargs}
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
    def __init__(self):
        self.entity_kwargs: dict | None = None
        self.entity_count_kwargs: dict | None = None

    async def count_entities(self, **kwargs):
        self.entity_count_kwargs = kwargs
        return 1

    async def list_entities(self, limit: int = 100, offset: int = 0, **kwargs):
        self.entity_kwargs = {"limit": limit, "offset": offset, **kwargs}
        return [
            {
                "entity_id": "user:u1",
                "canonical_name": "User U1",
                "entity_type": "user",
                "aliases": [],
            }
        ]

    async def count_mentions(self):
        return 1

    async def list_mentions(self, limit: int = 100, offset: int = 0):
        _ = limit
        return [{"mention_id": 1, "mention_text": "魔都", "resolved_entity_id": "place:shanghai"}]

    async def clear(self):
        return 5


class _FakeL3Store:
    db_path = "/tmp/l3.db"

    def __init__(self):
        self.summary_kwargs: dict | None = None
        self.summary_count_kwargs: dict | None = None
        self.forgotten_source_events: list[str] = []

    async def count_summaries(self, **kwargs):
        self.summary_count_kwargs = kwargs
        return 3

    async def list_summaries(self, limit: int = 100, offset: int = 0, **kwargs):
        self.summary_kwargs = {"limit": limit, "offset": offset, **kwargs}
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

    def __init__(self):
        self.skill_kwargs: dict | None = None
        self.skill_count_kwargs: dict | None = None
        self.forgotten_source_events: list[str] = []

    async def count_skills(self, **kwargs):
        self.skill_count_kwargs = kwargs
        return 1

    async def get_all_skills(self, limit: int = 100, offset: int = 0, **kwargs):
        self.skill_kwargs = {"limit": limit, "offset": offset, **kwargs}
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
        self._operation_barrier = AsyncOperationBarrier()
        self.l0 = _FakeL0Store()
        self.l1 = _FakeL1Store()
        self.l2 = _FakeL2Store()
        self.l2_entity_catalog = _FakeL2EntityCatalog()
        self.l3 = _FakeL3Store()
        self.l4 = _FakeL4Store()
        self.ingested_events: list = []
        self.flush_l2_projection_jobs_calls = 0
        self.drain_l2_edge_embedding_calls = 0

    def memory_operation_guard(self):
        return self._operation_barrier.operation()


    async def get_statistics(self):
        return {
            "l0": {"checkpoint_db_path": "/tmp/l0.db"},
            "l1": {"event_count": 12},
            "l2": {"db_path": "/tmp/l2.db"},
            "l3": {"db_path": "/tmp/l3.db"},
            "l4": {"db_path": "/tmp/l4.db"},
        }

    async def clear_all_memory(
        self,
        *,
        auxiliary_clearers=(),
        context_clearer=None,
        user_content_clear_boundaries=(),
    ):
        _ = user_content_clear_boundaries
        l2_count = await self.l2.clear()
        l2_count += await self.l2_entity_catalog.clear()
        for clearer in auxiliary_clearers:
            result = clearer()
            if hasattr(result, "__await__"):
                await result
        chat_context_count = context_clearer() if context_clearer is not None else 0
        if hasattr(chat_context_count, "__await__"):
            chat_context_count = await chat_context_count
        return {
            "l0": await self.l0.clear(),
            "l1": await self.l1.clear(),
            "l2": l2_count,
            "l3": await self.l3.clear(),
            "l4": await self.l4.clear(),
            "chat_context": int(chat_context_count or 0),
        }

    async def ingest_event(self, event):
        self.ingested_events.append(event)
        return {
            "event_id": f"evt-{len(self.ingested_events)}",
            "ingest_target": "l1_only",
            "l1_written": True,
        }


    async def flush_l2_projection_jobs(self):
        self.flush_l2_projection_jobs_calls += 1
        return 2

    async def drain_l2_edge_embeddings(self):
        self.drain_l2_edge_embedding_calls += 1
        return 5

    async def get_l2_edge_embedding_backlog(self):
        return {"pending": 0}

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


def test_memory_statistics_api_reports_new_layers(monkeypatch, tmp_path):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")

    fake_memory = _FakeUnifiedMemory()
    l0_path = tmp_path / "l0.db"
    l1_path = tmp_path / "l1.db"
    memory_path = tmp_path / "memory.db"
    memory_wal_path = tmp_path / "memory.db-wal"
    memory_shm_path = tmp_path / "memory.db-shm"
    l0_path.write_bytes(b"12")
    l1_path.write_bytes(b"123")
    memory_path.write_bytes(b"12345")
    memory_wal_path.write_bytes(b"1234567")
    memory_shm_path.write_bytes(b"12345678901")
    fake_memory.l0.checkpoint_db_path = str(l0_path)
    fake_memory.l1.db_path = str(l1_path)
    fake_memory.l2.db_path = str(memory_path)
    fake_memory.l3.db_path = str(memory_path)
    fake_memory.l4.db_path = str(memory_path)
    fake_memory.l0._sessions = {
        "session-1": {
            "session_id": "session-1",
            "status": "active",
        }
    }
    fake_memory.l0._attention_items = {
        "session-1": {
            "active": {
                "item_id": "active",
                "status": "active",
                "expires_at": None,
            },
            "background": {
                "item_id": "background",
                "status": "background",
                "expires_at": None,
            },
            "resolved": {
                "item_id": "resolved",
                "status": "resolved",
                "expires_at": None,
            },
            "expired": {
                "item_id": "expired",
                "status": "active",
                "expires_at": 1,
            },
        }
    }

    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: fake_memory)
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get("/api/memory/statistics")

    assert response.status_code == 200
    body = response.json()
    assert body["l1"]["event_count"] == 12
    assert body["l0"]["total_attention_items"] == 3
    assert body["l0"]["active_attention_items"] == 1
    assert body["l0"]["background_attention_items"] == 1
    assert body["l0"]["resolved_attention_items"] == 1
    assert "l4" in body
    assert body["stored_records"] == 16
    assert body["disk_usage_bytes"] == 28


def test_memory_search_unavailable_returns_localized_detail(monkeypatch):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_hybrid_retrieval_service", lambda: None)

    client = TestClient(app)
    with language_context("zh-CN"):
        response = client.post("/api/memory/search", json={"query": "hello"})

    assert response.status_code == 503
    assert response.json()["detail"] == "混合检索服务未初始化"


def test_l2_episode_empty_annotation_returns_localized_detail(monkeypatch):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: _FakeUnifiedMemory()
    )

    client = TestClient(app)
    with language_context("zh-CN"):
        response = client.patch("/api/memory/l2/episodes/episode-1", json={})

    assert response.status_code == 400
    assert response.json()["detail"] == "没有可更新的字段"


@pytest.mark.parametrize(
    "title,with_attention,expected_title,expected_subtitle",
    [
        ("记忆设置整理", True, "记忆设置整理", "把通用记忆设置里的 UUID 展示优化掉"),
        (
            "New Session",
            False,
            "把通用记忆设置里的 UUID 展示优化掉",
            "magi",
        ),
        (
            "New Session",
            True,
            "The user is reorganizing memory settings.",
            "把通用记忆设置里的 UUID 展示优化掉",
        ),
    ],
)
def test_l0_sessions_api_prefers_chat_summary_titles_and_short_ids(
    monkeypatch, title, with_attention, expected_title, expected_subtitle
):
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )

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
    fake_memory.l0._attention_items = {
        "379f666d-aee9-48fb-ab88-50690496297b": {
            "focus": {
                "item_id": "focus",
                "kind": "focus",
                "summary": "The user is reorganizing memory settings.",
                "status": "active",
                "expires_at": 4102444800,
            },
            "background": {
                "item_id": "background",
                "kind": "open_loop",
                "summary": "A secondary layout question is paused.",
                "status": "background",
                "expires_at": 4102444800,
            },
            "expired": {
                "item_id": "expired",
                "kind": "situation",
                "summary": "Expired context",
                "status": "active",
                "expires_at": 1,
            },
        }
    }

    if not with_attention:
        fake_memory.l0._attention_items = {}

    last_preview = (
        "把列表和工作台做成可展开的单列结构"
        if with_attention
        else "把通用记忆设置里的 UUID 展示优化掉"
    )

    class _FakeChatReadService:
        async def aget_session_summaries_batch(self, user_id: str, session_ids: list):
            assert user_id == "local_user"
            assert "379f666d-aee9-48fb-ab88-50690496297b" in session_ids
            return {
                "379f666d-aee9-48fb-ab88-50690496297b": SimpleNamespace(
                    title=title,
                    last_message_preview=last_preview,
                    last_user_message_preview="把通用记忆设置里的 UUID 展示优化掉",
                    workspace_path="/tmp/magi",
                    message_count=12,
                    title_overridden=True,
                    history_version=3,
                ),
            }

    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: fake_memory)
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service", lambda: _FakeChatReadService()
    )

    client = TestClient(app)
    response = client.get("/api/memory/l0/sessions")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["display_title"] == expected_title
    assert body["items"][0]["display_subtitle"] == expected_subtitle
    assert body["items"][0]["short_session_id"] == "379f666d"
    assert body["items"][0]["workspace_path"] == "/tmp/magi"
    assert body["items"][0]["message_count"] == 12
    assert body["items"][0]["last_message_preview"] == last_preview
    assert body["items"][0]["last_user_message_preview"] == "把通用记忆设置里的 UUID 展示优化掉"
    assert body["items"][0]["title_overridden"] is True
    assert body["items"][0]["history_version"] == 3
    assert body["items"][0]["attention_count"] == (2 if with_attention else 0)
    assert body["items"][0]["active_attention_count"] == (1 if with_attention else 0)
    assert body["items"][0]["background_attention_count"] == (1 if with_attention else 0)
    assert body["stats"]["total_attention_items"] == (2 if with_attention else 0)
    assert body["total"] == 1


def test_l0_sessions_api_filters_before_pagination(monkeypatch):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")

    fake_memory = _FakeUnifiedMemory()
    fake_memory.l0._sessions = {
        "session-newest": {
            "session_id": "session-newest",
            "user_id": "local_user",
            "status": "active",
            "started_at": 2.0,
            "last_active_at": 2.0,
        },
        "session-match": {
            "session_id": "session-match",
            "user_id": "local_user",
            "status": "active",
            "started_at": 1.0,
            "last_active_at": 1.0,
        },
    }
    fake_memory.l0._attention_items = {
        "session-newest": {},
        "session-match": {
            "attention-match": {
                "item_id": "attention-match",
                "kind": "focus",
                "summary": "Needle project",
                "status": "active",
                "expires_at": None,
            }
        },
    }
    fake_memory.l0.get_workbench = AsyncMock(
        side_effect=AssertionError("The session list must use its governed index snapshot")
    )

    class _FakeChatReadService:
        async def aget_session_summaries_batch(
            self,
            user_id: str,
            session_ids: list[str],
        ):
            assert user_id == "local_user"
            assert session_ids == ["session-newest", "session-match"]
            return {
                "session-newest": SimpleNamespace(title="Unrelated"),
                "session-match": SimpleNamespace(title="Another conversation"),
            }

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: fake_memory,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service",
        lambda: _FakeChatReadService(),
    )

    response = TestClient(app).get(
        "/api/memory/l0/sessions",
        params={"query": "needle", "limit": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["session_id"] for item in body["items"]] == ["session-match"]
    assert body["stats"]["active_sessions"] == 1
    fake_memory.l0.get_workbench.assert_not_awaited()


def test_l0_workbench_composes_durable_context_usage(monkeypatch):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")

    class _FakeL0:
        async def get_workbench(self, session_id: str):
            assert session_id == "session-1"
            return {
                "session": {
                    "session_id": session_id,
                    "user_id": "local_user",
                },
                "attention_items": [
                    {
                        "item_id": "attention-1",
                        "kind": "focus",
                        "summary": "The user is checking context usage.",
                        "status": "active",
                    }
                ],
            }

    class _FakeChatReadService:
        async def aget_latest_context_usage(self, user_id: str, session_id: str):
            assert (user_id, session_id) == ("local_user", "session-1")
            return SimpleNamespace(
                to_dict=lambda: {
                    "turn_id": "turn-1",
                    "used_tokens": 123,
                    "window_size": 4096,
                }
            )

    fake_memory = MemoryApiStub(l0=_FakeL0())
    fake_memory_barrier = AsyncOperationBarrier()
    fake_memory.memory_operation_guard = fake_memory_barrier.operation
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: fake_memory,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service",
        lambda: _FakeChatReadService(),
    )

    client = TestClient(app)
    response = client.get("/api/memory/l0/workbench/session-1")

    assert response.status_code == 200
    assert response.json()["context_usage"] == {
        "turn_id": "turn-1",
        "used_tokens": 123,
        "window_size": 4096,
    }


@pytest.mark.asyncio
async def test_eval_replay_persists_namespace_role_and_content(monkeypatch, tmp_path):
    from _shared.memory_schema import apply_memory_shared_schema
    from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore

    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        enable_l0=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
        tuning=MemoryStoreTuning(enable_l1_vectors=False),
    )
    await memory.initialize()
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: memory)
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    namespaces = ["benchmark/replay/run-a/q-1", "benchmark/replay/run-a/q-2"]
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for index, namespace in enumerate(namespaces):
                records = [
                    {
                        "namespace": namespace,
                        "session_id": f"session-{index}",
                        "turn_id": f"turn-{index}-{role}",
                        "timestamp": 100.0 + index + offset,
                        "role": role,
                        "content": f"{namespace}:{role}:private",
                        "metadata": {"source_dataset": "replay-test"},
                    }
                    for offset, role in enumerate(["user", "assistant"])
                ]
                response = await client.post(
                    "/api/memory/eval/replay", json={"namespace": namespace, "records": records}
                )
                assert response.status_code == 200
                assert response.json()["written"] == 2
                assert response.json()["namespace"] == namespace
            for index, namespace in enumerate(namespaces):
                rows = await memory.l1.query_events(user_id=namespace, limit=10)
                assert len(rows) == 2
                assert {
                    (
                        row["user_id"],
                        row["session_id"],
                        row["turn_id"],
                        row["author_type"],
                        row["content"],
                        row["timestamp"],
                    )
                    for row in rows
                } == {
                    (
                        namespace,
                        f"session-{index}",
                        f"turn-{index}-{role}",
                        role,
                        f"{namespace}:{role}:private",
                        100.0 + index + offset,
                    )
                    for offset, role in enumerate(["user", "assistant"])
                }
                assert {row["source"] for row in rows} == {"benchmark.eval_support"}
    finally:
        await memory.shutdown()


def test_memory_eval_query_api_returns_normalized_hits(monkeypatch):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")

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

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_hybrid_retrieval_service",
        lambda: _FakeHybridRetrievalService(),
    )

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


@pytest.mark.parametrize(
    "mode,query_mode,show_prompt,log_content",
    [
        ("auto", None, True, False),
        ("detail", "exact_fact", False, False),
        ("auto", None, False, True),
        ("detail", "exact_fact", True, True),
    ],
)
def test_eval_answer_boundary_respects_scope_prompt_visibility_and_log_policy(
    monkeypatch, mode, query_mode, show_prompt, log_content
):
    from magi.config import get_config
    from magi.utils import diagnostic_logging

    get_config()

    monkeypatch.setattr(diagnostic_logging, "_FULL_CONTENT_LOGGING_ENABLED", log_content)
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    question = "What is my private-food-canary?"
    evidence = "Evidence-canary: my favorite food is sushi."
    answer = "answer-canary-sushi"
    retrieve = AsyncMock(
        return_value=SimpleNamespace(
            l1_events=[
                {
                    "event_id": "evt-1",
                    "session_id": "sess-1",
                    "turn_id": "turn-1",
                    "content": evidence,
                    "score": 0.9,
                }
            ],
            trace={"intent_source": "rule"},
        )
    )
    messages_seen = []

    class Adapter:
        async def chat(self, messages, **kwargs):
            messages_seen.extend(messages)
            return answer

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_hybrid_retrieval_service",
        lambda: SimpleNamespace(query=retrieve),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_scenario_llm_pool",
        lambda: SimpleNamespace(get=lambda _: Adapter()),
    )
    log = Mock()
    monkeypatch.setattr("magi.api.routers.memory.dependencies.logger.info", log)
    response = TestClient(app).post(
        "/api/memory/eval/query",
        json={
            "namespace": "benchmark/case-1",
            "query": question,
            "top_k": 7,
            "mode": mode,
            "answer_with_llm": True,
            "show_prompt": show_prompt,
        },
    )
    assert response.status_code == 200
    request = retrieve.await_args.args[0]
    assert request.user_id == "benchmark/case-1"
    assert request.query == question
    assert request.query_mode == query_mode
    assert request.limit == 7
    prompt = messages_seen[-1]["content"]
    assert question in prompt and evidence in prompt
    body = response.json()
    assert body["answer"] == answer
    assert body["answer_trace"]["answer_source"] == "llm"
    if show_prompt:
        assert body["answer_trace"]["prompt"] == prompt
    else:
        assert "prompt" not in body["answer_trace"]
    logged_fields = [call.kwargs for call in log.call_args_list]
    timing = [fields for fields in logged_fields if "duration_ms" in fields]
    assert len(timing) == 1
    assert timing[0]["duration_ms"] >= 0
    assert timing[0]["hit_count"] == 1
    assert timing[0]["mode"] == mode
    serialized_logs = str(logged_fields)
    for canary in [question, evidence, answer]:
        assert (canary in serialized_logs) is log_content
    assert any("llm_messages" in fields for fields in logged_fields) is log_content


def test_memory_eval_query_api_uses_evidence_bundles_for_answer_synthesis(monkeypatch):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")

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

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_hybrid_retrieval_service",
        lambda: _FakeHybridRetrievalService(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_scenario_llm_pool", lambda: _FakeLLMPool()
    )

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
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")

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

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_hybrid_retrieval_service",
        lambda: _FakeHybridRetrievalService(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_scenario_llm_pool", lambda: _FakeLLMPool()
    )

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


def test_memory_eval_query_api_supports_l1_only_fast_path(monkeypatch):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")

    class _ExplodingHybridRetrievalService:
        async def query(self, request):
            _ = request
            raise AssertionError("hybrid retrieval should not be used")

    fake_memory = _FakeUnifiedMemory()

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_hybrid_retrieval_service",
        lambda: _ExplodingHybridRetrievalService(),
    )
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: fake_memory)

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


@pytest.mark.parametrize(
    "mode_fields,expected_mode", [({}, None), ({"query_mode": "summary"}, "summary")]
)
def test_memory_search_api_uses_runtime_hybrid_retrieval_service(
    monkeypatch, mode_fields, expected_mode
):
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )

    class _FakeHybridRetrievalService:
        async def query(self, request):
            assert request.query == "switch jobs"
            assert request.user_id == DEFAULT_USER_ID
            assert request.query_mode == expected_mode
            assert request.limit == 5
            return RetrievalPayload(
                l0_workbench=[
                    {
                        "session": {"session_id": "session-1"},
                        "attention_items": [
                            {
                                "kind": "focus",
                                "summary": "The user is considering a job change.",
                                "status": "active",
                            }
                        ],
                    }
                ],
                l1_events=[],
                l2_entity_cards=[],
                l2_relationships=[],
                l2_assertions=[],
                l3_reflections=[{"summary_id": "sum-1"}],
                l4_procedures=[],
                trace={"intent_source": "rule"},
            )

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_hybrid_retrieval_service",
        lambda: _FakeHybridRetrievalService(),
    )

    client = TestClient(app)
    response = client.post(
        "/api/memory/search",
        json={"query": "switch jobs", "limit": 5, **mode_fields},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["l0_workbench"][0]["attention_items"][0]["kind"] == "focus"
    assert body["l3_reflections"][0]["summary_id"] == "sum-1"
    assert body["trace"]["intent_source"] == "rule"


def test_memory_eval_finalize_replay_api_generates_summaries_and_returns_l2_stats(monkeypatch):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")

    fake_memory = _FakeUnifiedMemory()

    async def _generate_summary(period_type: str):
        return {"summary_id": f"sum-{period_type}-1", "summary_category": period_type}

    fake_memory.generate_summary = _generate_summary
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: fake_memory)
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.post(
        "/api/memory/eval/finalize-replay",
        json={"period_types": ["hour", "day", "week", "month"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summaries"]["hour"]["summary_id"] == "sum-hour-1"
    assert body["summaries"]["month"]["summary_id"] == "sum-month-1"
    assert body["l2_projection_batch_count"] == 2
    assert body["l2_edge_embedding_count"] == 5
    assert body["l2_pipeline_stats"]["extract_completed"] == 3
    assert body["l2_pipeline_stats"]["projection_backlog"]["claimed"] == 2
    assert fake_memory.flush_l2_projection_jobs_calls == 1
    assert fake_memory.drain_l2_edge_embedding_calls == 1


def test_memory_eval_finalize_replay_api_can_split_l2_flush_from_post_l2_work(monkeypatch):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")

    fake_memory = _FakeUnifiedMemory()

    async def _generate_summary(period_type: str):
        return {"summary_id": f"sum-{period_type}-1", "summary_category": period_type}

    fake_memory.generate_summary = _generate_summary
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: fake_memory)
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.post(
        "/api/memory/eval/finalize-replay",
        json={
            "period_types": ["hour"],
            "generate_summaries": False,
            "flush_l2_projection_jobs": True,
            "drain_l2_edge_embeddings": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summaries"] == {}
    assert body["l2_projection_batch_count"] == 2
    assert body["l2_edge_embedding_count"] == 0
    assert fake_memory.flush_l2_projection_jobs_calls == 1
    assert fake_memory.drain_l2_edge_embedding_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filters,expected",
    [
        ({"summary_type": "insight"}, ["new-insight", "other-category", "old-insight"]),
        ({"summary_category": "state_change"}, ["new-insight", "other-type", "old-insight"]),
        (
            {"summary_type": "insight", "summary_category": "state_change"},
            ["new-insight", "old-insight"],
        ),
        (
            {"summary_type": "insight", "summary_category": "state_change", "query": "old"},
            ["old-insight"],
        ),
        ({"summary_category": "missing"}, []),
    ],
)
async def test_summary_filters_apply_before_pagination_and_count(
    monkeypatch, tmp_path, filters, expected
):
    from _shared.memory_schema import apply_memory_shared_schema
    from magi.memory.l3.summary_store import L3SummaryStore
    from magi.memory.l3.models import L3Candidate

    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = L3SummaryStore(db_path=db_path, vector_enabled=False)
    rows = [
        ("old-insight", "insight", "state_change"),
        ("other-type", "temporal", "state_change"),
        ("other-category", "insight", "trend_shift"),
        ("new-insight", "insight", "state_change"),
        ("newest-unrelated", "thematic", "topic"),
    ]
    for index, (content, summary_type, summary_category) in enumerate(rows):
        await store.upsert_candidate(
            candidate=L3Candidate(
                content=content,
                source_event_ids=[],
                summary_type=summary_type,
                summary_category=summary_category,
            ),
            summary_overrides={"updated_at": 100.0 + index},
        )
    memory = SimpleNamespace(l3=store, memory_operation_guard=AsyncOperationBarrier().operation)
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: memory)
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for offset in range(len(expected) + 1):
            response = await client.get(
                "/api/memory/l3/summaries", params={**filters, "limit": 1, "offset": offset}
            )
            assert response.status_code == 200
            body = response.json()
            assert [row["content"] for row in body["items"]] == expected[offset : offset + 1]
            assert body["total"] == len(expected)
            assert body["limit"] == 1 and body["offset"] == offset


def test_public_l2_mentions_forward_pagination(monkeypatch):
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    rows = [{"mention_id": 1, "mention_text": "魔都", "resolved_entity_id": "place:shanghai"}]
    catalog = SimpleNamespace(
        list_mentions=AsyncMock(return_value=rows), count_mentions=AsyncMock(return_value=12)
    )
    memory = SimpleNamespace(
        l2_entity_catalog=catalog, memory_operation_guard=AsyncOperationBarrier().operation
    )
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: memory)
    response = TestClient(app).get("/api/memory/l2/mentions", params={"limit": 3, "offset": 4})
    assert response.status_code == 200
    assert response.json() == {"items": rows, "total": 12, "limit": 3, "offset": 4}
    catalog.list_mentions.assert_awaited_once_with(limit=3, offset=4)
    catalog.count_mentions.assert_awaited_once_with()


def test_public_l2_conflict_rules_forward_normalized_values(monkeypatch):
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    expected = {
        "predicate": "ENDORSES",
        "opposite_predicates": ["REJECTS"],
        "opposite_resolution": "mark_conflicted",
        "exclusive_group": "stance",
        "exclusive_scope": "same_subject",
        "exclusive_resolution": "mark_conflicted",
    }
    l2 = SimpleNamespace(
        list_graph_conflict_rules=AsyncMock(return_value=[expected]),
        upsert_graph_conflict_rule=AsyncMock(return_value=expected),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: SimpleNamespace(l2=l2, memory_operation_guard=AsyncOperationBarrier().operation),
    )
    client = TestClient(app)
    body = {key: value for key, value in expected.items() if key != "predicate"}
    body["opposite_predicates"] = [" REJECTS ", " "]
    response = client.put("/api/memory/l2/conflict-rules/ENDORSES", json=body)
    assert response.status_code == 200
    assert response.json() == expected
    l2.upsert_graph_conflict_rule.assert_awaited_once_with(expected)
    listed = client.get("/api/memory/l2/conflict-rules")
    assert listed.status_code == 200
    assert listed.json() == [expected]
    l2.list_graph_conflict_rules.assert_awaited_once_with()


def test_public_l2_projection_flush_returns_scheduled_count(monkeypatch):
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    flush = AsyncMock(return_value=2)
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: SimpleNamespace(
            flush_l2_projection_jobs=flush, memory_operation_guard=AsyncOperationBarrier().operation
        ),
    )
    response = TestClient(app).post("/api/memory/l2/projection-flush")
    assert response.status_code == 200
    assert response.json() == {"queued": True, "batch_count": 2}
    flush.assert_awaited_once_with()


def test_memory_object_list_apis_forward_query_to_selected_category(monkeypatch):
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )

    fake_memory = _FakeUnifiedMemory()
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: fake_memory)
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_memory_integration", lambda: None)

    client = TestClient(app)

    endpoints = [
        "/api/memory/l2/relations",
        "/api/memory/l2/assertions",
        "/api/memory/l2/entities",
        "/api/memory/l2/snapshots",
        "/api/memory/l3/summaries",
        "/api/memory/procedures",
    ]
    for endpoint in endpoints:
        response = client.get(endpoint, params={"query": "codex", "limit": 20, "offset": 40})
        assert response.status_code == 200
        if endpoint == "/api/memory/procedures":
            assert response.json()["items"][0]["skill_name"] == "browser.open"
            assert response.json()["items"][0]["success_rate"] == 0.75
            assert response.json()["total"] == 1

    assert fake_memory.l2.relationship_kwargs == {
        "limit": 20,
        "offset": 40,
        "query": "codex",
        "include_inactive": False,
        "status_group": None,
        "entity_type": None,
        "triple_id": None,
    }
    assert fake_memory.l2.relationship_count_kwargs == {
        "query": "codex",
        "include_inactive": False,
        "status_group": None,
        "entity_type": None,
        "triple_id": None,
    }
    assert fake_memory.l2.assertion_kwargs == {
        "limit": 20,
        "offset": 40,
        "query": "codex",
        "include_inactive": False,
        "status_group": None,
        "entity_type": None,
        "assertion_id": None,
    }
    assert fake_memory.l2.assertion_count_kwargs == {
        "query": "codex",
        "include_inactive": False,
        "status_group": None,
        "entity_type": None,
        "assertion_id": None,
    }
    assert fake_memory.l2_entity_catalog.entity_kwargs == {
        "limit": 20,
        "offset": 40,
        "query": "codex",
        "entity_type": None,
    }
    assert fake_memory.l2_entity_catalog.entity_count_kwargs == {"query": "codex", "entity_type": None}
    assert fake_memory.l2.snapshot_kwargs == {"limit": 20, "offset": 40, "query": "codex"}
    assert fake_memory.l2.snapshot_count_kwargs == {"query": "codex"}
    assert fake_memory.l3.summary_kwargs == {
        "limit": 20,
        "offset": 40,
        "query": "codex",
        "summary_type": None,
        "summary_category": None,
    }
    assert fake_memory.l3.summary_count_kwargs == {
        "query": "codex",
        "summary_type": None,
        "summary_category": None,
    }
    assert fake_memory.l4.skill_kwargs == {"limit": 20, "offset": 40, "query": "codex"}
    assert fake_memory.l4.skill_count_kwargs == {"query": "codex"}

    relations_with_history = client.get(
        "/api/memory/l2/relations",
        params={"include_inactive": True},
    )
    assertions_with_history = client.get(
        "/api/memory/l2/assertions",
        params={"include_inactive": True},
    )

    assert relations_with_history.status_code == 200
    assert assertions_with_history.status_code == 200
    assert fake_memory.l2.relationship_kwargs["include_inactive"] is True
    assert fake_memory.l2.relationship_count_kwargs["include_inactive"] is True
    assert fake_memory.l2.assertion_kwargs["include_inactive"] is True
    assert fake_memory.l2.assertion_count_kwargs["include_inactive"] is True


def test_memory_relation_api_hydrates_endpoint_names(monkeypatch):
    import magi.api.routers.memory.l2.knowledge_routes as knowledge_routes

    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")

    fake_memory = _FakeUnifiedMemory()

    async def _get_relationships(**_kwargs):
        return [
            {
                "triple_id": "triple-1",
                "subject_id": "user:local_user",
                "subject_type": "user",
                "predicate": "LIKES",
                "object_id": "concept:c6052b702d6e",
                "object_type": "concept",
                "confidence": 0.3,
                "evidence_event_ids": ["evt-1"],
                "observation_count": 1,
                "status": "active",
            }
        ]

    async def _get_canonical_names(_db_path, entity_ids):
        assert set(entity_ids) == {"user:local_user", "concept:c6052b702d6e"}
        return {
            "concept:c6052b702d6e": "没有人声或者人声比较远的音乐",
        }

    fake_memory.l2.get_relationships = _get_relationships
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: fake_memory)
    monkeypatch.setattr(
        knowledge_routes,
        "get_canonical_names",
        _get_canonical_names,
        raising=False,
    )

    response = TestClient(app).get("/api/memory/l2/relations")

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "triple_id": "triple-1",
            "subject_id": "user:local_user",
            "subject_type": "user",
            "subject_name": None,
            "predicate": "LIKES",
            "object_id": "concept:c6052b702d6e",
            "object_type": "concept",
            "object_name": "没有人声或者人声比较远的音乐",
            "confidence": 0.3,
            "evidence_event_ids": ["evt-1"],
            "observation_count": 1,
            "status": "active",
        }
    ]


def test_memory_identity_links_api_returns_empty_payload_when_identity_mapping_is_unavailable(
    monkeypatch,
    tmp_path,
):
    from magi.memory.unified_store import UnifiedMemoryStore

    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        enable_l0=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )

    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: memory)
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get("/api/memory/identity/links")

    assert response.status_code == 200
    assert response.json() == {
        "canonical_self_id": "user:local_user",
        "links": [],
    }


def test_memory_background_pending_api_reports_embedding_backlog(monkeypatch):
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: _FakeUnifiedMemory()
    )
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get("/api/memory/background/pending")

    assert response.status_code == 200
    body = response.json()
    assert body["l2"]["extract_pending"] == 7
    assert body["l2"]["projection_pending"] == 5
    assert body["l2"]["projection_claimed"] == 2
    assert body["l1_embeddings"]["pending"] == 7
    assert body["l2_edge_embeddings"]["pending"] == 0
    assert body["l3_embeddings"]["pending"] == 3
    assert body["l4_embeddings"]["pending"] == 0
    assert body["all_idle"] is False
    assert body["l2"]["reconcile_pending"] == 0
    assert body["l2"]["snapshot_pending"] == 0
    assert body["l2"]["projection_failed"] == 1

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


def test_memory_clear_api_clears_all_layers(
    monkeypatch,
    _isolate_batch_store,
    _isolate_diagnostic_log_cleanup,
    _isolate_memory_portability_clear,
    _isolate_user_message_clear_boundary,
):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    clear_order: list[str] = []
    received_history_boundaries: list = []
    portability_service, _ = _isolate_memory_portability_clear
    queue, _ = _isolate_user_message_clear_boundary
    complete_full_clear = queue.complete_full_user_content_clear

    async def complete_while_portability_is_blocked(*, transaction_id: str) -> None:
        assert portability_service.active is True
        await complete_full_clear(transaction_id=transaction_id)

    queue.complete_full_user_content_clear = complete_while_portability_is_blocked

    @asynccontextmanager
    async def history_import_boundary():
        yield

    class _OrderedUnifiedMemory(_FakeUnifiedMemory):
        async def clear_all_memory(
            self,
            *,
            auxiliary_clearers=(),
            context_clearer=None,
            user_content_clear_boundaries=(),
        ):
            received_history_boundaries.extend(user_content_clear_boundaries)
            result = await super().clear_all_memory(
                auxiliary_clearers=auxiliary_clearers,
                context_clearer=context_clearer,
                user_content_clear_boundaries=user_content_clear_boundaries,
            )
            clear_order.append("memory-finished")
            return result

    class _FakeChatReadService:
        async def aclear_all_sessions(self) -> int:
            assert clear_order == [
                "chat-projection-enter",
                "scheduler-enter",
                "background-enter",
                "control-enter",
                "plugin-enter",
                "tools-enter",
                "plugin-clear",
                "scheduler-clear",
            ]
            clear_order.append("chat")
            return 4

    @asynccontextmanager
    async def background_scope_boundary(**kwargs):  # type: ignore[no-untyped-def]
        assert kwargs == {"reason": "user_clear_all_memory"}
        assert clear_order == ["chat-projection-enter", "scheduler-enter"]
        clear_order.append("background-enter")
        try:
            yield
        finally:
            clear_order.append("background-exit")

    @asynccontextmanager
    async def scheduler_scope_boundary():
        assert clear_order == ["chat-projection-enter"]
        clear_order.append("scheduler-enter")
        try:
            yield
        finally:
            clear_order.append("scheduler-exit")

    async def clear_scheduler_data():
        assert clear_order == [
            "chat-projection-enter",
            "scheduler-enter",
            "background-enter",
            "control-enter",
            "plugin-enter",
            "tools-enter",
            "plugin-clear",
        ]
        clear_order.append("scheduler-clear")

    @asynccontextmanager
    async def control_content_boundary():
        assert clear_order == [
            "chat-projection-enter",
            "scheduler-enter",
            "background-enter",
        ]
        clear_order.append("control-enter")
        try:
            yield
        finally:
            clear_order.append("control-exit")

    @asynccontextmanager
    async def tool_content_boundary():
        assert clear_order == [
            "chat-projection-enter",
            "scheduler-enter",
            "background-enter",
            "control-enter",
            "plugin-enter",
        ]
        clear_order.append("tools-enter")
        try:
            yield
        finally:
            clear_order.append("tools-exit")

    class _PluginClearSession:
        def mark_surrounding_clear_failed(self, _error):  # type: ignore[no-untyped-def]
            return None

        async def clear_user_content(self, request):  # type: ignore[no-untyped-def]
            assert request.clear_generation == 1
            assert clear_order == [
                "chat-projection-enter",
                "scheduler-enter",
                "background-enter",
                "control-enter",
                "plugin-enter",
                "tools-enter",
            ]
            clear_order.append("plugin-clear")

    @asynccontextmanager
    async def plugin_content_boundary():
        assert clear_order == [
            "chat-projection-enter",
            "scheduler-enter",
            "background-enter",
            "control-enter",
        ]
        clear_order.append("plugin-enter")
        try:
            yield _PluginClearSession()
        finally:
            clear_order.append("plugin-exit")

    @asynccontextmanager
    async def chat_projection_boundary():
        assert clear_order == []
        clear_order.append("chat-projection-enter")
        try:
            yield
        finally:
            clear_order.append("chat-projection-exit")

    background_task_manager = SimpleNamespace(
        conversation_scope_boundary=background_scope_boundary,
        clear_all_history=AsyncMock(
            side_effect=lambda: clear_order.append("background-history-cleared") or {}
        ),
    )
    scheduler_service = SimpleNamespace(
        user_data_clear_boundary=scheduler_scope_boundary,
        clear_user_data=clear_scheduler_data,
    )

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: _OrderedUnifiedMemory(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service", lambda: _FakeChatReadService()
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_background_task_manager",
        lambda: background_task_manager,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_scheduler_service",
        lambda: scheduler_service,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_control_user_content_clear",
        lambda: SimpleNamespace(user_content_clear_boundary=control_content_boundary),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_plugin_user_content_clear",
        lambda: SimpleNamespace(user_content_clear_boundary=plugin_content_boundary),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_chat_memory_projection_clear",
        lambda: SimpleNamespace(user_content_clear_boundary=chat_projection_boundary),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_tool_registry",
        lambda: SimpleNamespace(user_content_clear_boundary=tool_content_boundary),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_history_import_service",
        lambda: SimpleNamespace(user_content_clear_boundary=history_import_boundary),
    )

    client = TestClient(app)
    response = client.delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["results"]["l0"]["count"] == 3
    assert body["results"]["l1"]["count"] == 12
    assert body["results"]["l2"]["count"] == 10
    assert body["results"]["l3"]["count"] == 2
    assert body["results"]["l4"]["count"] == 1
    assert body["results"]["chat_context"]["count"] == 4
    assert received_history_boundaries == [history_import_boundary]
    assert queue.full_clear_transaction_id == FULL_CLEAR_TRANSACTION_ID
    assert queue.full_clear_completed_transaction_id == FULL_CLEAR_TRANSACTION_ID
    assert portability_service.active is False
    _isolate_batch_store.clear_all.assert_awaited_once()
    _isolate_diagnostic_log_cleanup.assert_awaited_once_with()
    _, clear_portability_private_data = _isolate_memory_portability_clear
    clear_portability_private_data.assert_awaited_once_with()
    assert clear_order == [
        "chat-projection-enter",
        "scheduler-enter",
        "background-enter",
        "control-enter",
        "plugin-enter",
        "tools-enter",
        "plugin-clear",
        "scheduler-clear",
        "chat",
        "background-history-cleared",
        "memory-finished",
        "tools-exit",
        "plugin-exit",
        "control-exit",
        "background-exit",
        "scheduler-exit",
        "chat-projection-exit",
    ]


def test_memory_clear_rejects_active_portability_operation_before_begin(
    monkeypatch,
    _isolate_user_message_clear_boundary,
) -> None:
    @asynccontextmanager
    async def busy_boundary():
        raise MemoryPortabilityError(
            "operation_in_progress",
            "Another memory data operation is still running.",
            status_code=409,
        )
        yield  # pragma: no cover

    unified = _FakeUnifiedMemory()
    unified.clear_all_memory = AsyncMock()  # type: ignore[method-assign]
    monkeypatch.setattr(
        "magi.api.routers.memory.overview_routes.get_memory_portability_service",
        lambda: SimpleNamespace(user_content_clear_boundary=busy_boundary),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: unified,
    )
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")

    response = TestClient(app).delete(
        "/api/memory/clear",
        headers=FULL_CLEAR_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "operation_in_progress"
    queue, _ = _isolate_user_message_clear_boundary
    assert queue.full_clear_transaction_id is None
    unified.clear_all_memory.assert_not_awaited()


def test_memory_clear_requires_a_desktop_transaction_header(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )

    response = TestClient(app).delete("/api/memory/clear")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_memory_clear_api_rejects_old_control_waiters_and_reopens(
    monkeypatch,
) -> None:
    from magi.chat.control_transcript_subscriber import ControlTranscriptSubscriber
    from magi.control.ask_service import ControlAskRequest, ControlAskService
    from magi.control.common import InteractionBroker, InteractionClosedError
    from magi.control.permission.brokered_prompter import (
        BrokeredPermissionPrompter,
        PendingPermissionRegistry,
    )
    from magi.control.permission.contracts import (
        PermissionRequest,
        RiskLevel,
        ToolOrigin,
    )
    from magi.control.session_store import ControlSessionStore
    from magi.control.user_content_clear import ControlUserContentClearCoordinator

    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    store = ControlSessionStore()
    broker = InteractionBroker()
    registry = PendingPermissionRegistry()
    coordinator = ControlUserContentClearCoordinator(
        session_store=store,
        pending_permissions=registry,
        interaction_broker=broker,
    )
    coordinator.bind_transcript_subscriber(ControlTranscriptSubscriber(event_bus=SimpleNamespace()))
    ask_service = ControlAskService(
        session_store=store,
        interaction_broker=broker,
    )
    prompter = BrokeredPermissionPrompter(
        broker=broker,
        registry=registry,
    )

    def ask_request(session_id: str, question: str) -> ControlAskRequest:
        return ControlAskRequest(
            session_id=session_id,
            user_id="user-1",
            turn_id="turn-1",
            question=question,
            options=["yes", "no"],
            allow_free_text=False,
            timeout_seconds=30,
        )

    def permission_request(request_id: str, session_id: str) -> PermissionRequest:
        return PermissionRequest(
            request_id=request_id,
            tool_name="bash",
            arguments={"command": "private command"},
            risk_level=RiskLevel.HIGH,
            origin=ToolOrigin.CHAT,
            agent_id="chat",
            session_id=session_id,
            turn_id="turn-1",
            workspace=None,
        )

    async def wait_until(predicate) -> None:
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(0)

    await store.enter_plan_mode("session-old")
    await store.mutate_run_plan(
        "session-old",
        run_id="run-old",
        plan_id=None,
        expected_version=0,
        item_mutations=[{"title": "private todo"}],
    )
    old_ask_task = asyncio.create_task(
        ask_service.ask(ask_request("session-old", "private question"))
    )
    old_permission = permission_request("same-id", "session-old")
    old_permission_task = asyncio.create_task(prompter(old_permission, timeout_seconds=30))
    await wait_until(
        lambda: store.ask_state("session-old") is not None
        and registry.get("same-id") is old_permission
        and broker.pending_count() == 2
    )
    old_ask = store.ask_state("session-old")
    assert old_ask is not None

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        _FakeUnifiedMemory,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_control_user_content_clear",
        lambda: coordinator,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)

    assert response.status_code == 200
    assert store.plan_state("session-old").active is False
    assert store.current_run_plan("session-old") is None
    assert store.ask_state("session-old") is None
    assert registry.snapshot(session_id="*") == []
    assert (
        await broker.resolve(
            interaction_id=old_ask.request_id,
            kind="ask",
            response="late answer",
        )
        is False
    )
    assert (
        await broker.resolve(
            interaction_id="same-id",
            kind="permission",
            response={"outcome": "allowed"},
        )
        is False
    )
    with pytest.raises(InteractionClosedError):
        await old_ask_task
    with pytest.raises(InteractionClosedError):
        await old_permission_task

    fresh_ask_task = asyncio.create_task(
        ask_service.ask(ask_request("session-fresh", "fresh question"))
    )
    await wait_until(lambda: store.ask_state("session-fresh") is not None)
    fresh_ask = store.ask_state("session-fresh")
    assert fresh_ask is not None
    assert await broker.resolve(
        interaction_id=fresh_ask.request_id,
        kind="ask",
        response="yes",
    )
    assert (await fresh_ask_task).answer == "yes"

    fresh_permission = permission_request("same-id", "session-fresh")
    fresh_permission_task = asyncio.create_task(prompter(fresh_permission, timeout_seconds=30))
    await wait_until(lambda: registry.get("same-id") is fresh_permission)
    assert await broker.resolve(
        interaction_id="same-id",
        kind="permission",
        response={"outcome": "allowed"},
    )
    assert (await fresh_permission_task).allow is True


@pytest.mark.asyncio
async def test_memory_clear_waits_for_source_command_and_purges_source_queue(
    monkeypatch,
    tmp_path,
) -> None:
    import asyncio

    from magi.api.routers.memory.embedding_routes import _embedding_rebuild_manager
    from magi.api.routers.memory.overview_routes import clear_memory_layers
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.events.contracts import (
        RefreshLLMConfigCommand,
        RuntimeCommandType,
        SourceStateFlushCommand,
        SourceSyncCommand,
    )
    from magi.events.lifecycle import RuntimeCommandProcessorModule
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(tmp_path / "runtime_commands.db"))
    await queue.start()
    command_started = asyncio.Event()
    release_command = asyncio.Event()
    memory_clear_started = asyncio.Event()
    sync_writes: list[str] = []
    flush_writes: list[str] = []

    class _BlockingSourceScheduler:
        async def queue_manual_sync(self, source_name: str, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            command_started.set()
            await release_command.wait()
            sync_writes.append(source_name)

    class _RecordingSourceExecutor:
        async def flush_source_state(self, source_name: str) -> None:
            flush_writes.append(source_name)

    class _ObservedUnifiedMemory(_FakeUnifiedMemory):
        async def clear_all_memory(self, **kwargs):  # type: ignore[no-untyped-def]
            memory_clear_started.set()
            return await super().clear_all_memory(**kwargs)

    context = RuntimeBootstrapContext()
    context.agent_runtime.source_scheduler_contrib = _BlockingSourceScheduler()
    context.agent_runtime.source_sync_executor = _RecordingSourceExecutor()
    processor = RuntimeCommandProcessorModule(context, poll_interval_seconds=0.01)

    await queue.enqueue_source_sync(
        SourceSyncCommand(
            source="api",
            source_name="chrome_history",
            connection_id="chrome-work",
            sync_mode="backfill",
        )
    )
    await queue.enqueue_source_state_flush(
        SourceStateFlushCommand(source="api", source_name="screen_time", connection_id="screen-work")
    )
    refresh_id = await queue.enqueue_refresh_llm_config(
        RefreshLLMConfigCommand(source="api", reason="settings_saved")
    )
    processing = asyncio.create_task(processor._run_next_command(queue=queue, message_bus=object()))
    clearing: asyncio.Task[dict] | None = None

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_runtime_command_queue",
        lambda: queue,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: _ObservedUnifiedMemory(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_task_agent_manager",
        lambda: None,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_source_hub",
        lambda: None,
    )
    monkeypatch.setattr(
        _embedding_rebuild_manager,
        "pause_starts_and_cancel_all",
        AsyncMock(),
    )
    monkeypatch.setattr(
        _embedding_rebuild_manager,
        "resume_starts",
        AsyncMock(),
    )

    try:
        await asyncio.wait_for(command_started.wait(), timeout=1)
        clearing = asyncio.create_task(clear_memory_layers(FULL_CLEAR_TRANSACTION_ID))
        await asyncio.sleep(0.02)
        assert memory_clear_started.is_set() is False

        release_command.set()
        await asyncio.wait_for(processing, timeout=1)
        result = await asyncio.wait_for(clearing, timeout=2)

        assert result["success"] is True
        assert sync_writes == ["chrome_history"]
        assert flush_writes == []
        assert (await queue.get_stats()) == {
            "pending_count": 1,
            "claimed_count": 0,
            "completed_count": 0,
            "failed_count": 0,
        }
        refresh = await queue.claim_next(
            consumer_name="runtime-worker",
            command_types=(RuntimeCommandType.REFRESH_LLM_CONFIG,),
        )
        assert refresh is not None
        assert refresh.command_id == refresh_id
    finally:
        release_command.set()
        if clearing is not None:
            await asyncio.gather(clearing, return_exceptions=True)
        if not processing.done():
            processing.cancel()
        await asyncio.gather(processing, return_exceptions=True)
        await queue.stop()


@pytest.mark.parametrize(
    "resolver_path,unavailable_message",
    [
        pytest.param(
            "magi.api.routers.memory.dependencies._resolve_scheduler_service",
            "Scheduler service not initialized",
            id="memory_clear_rejects_when_scheduler_is_unavailable",
        ),
        pytest.param(
            "magi.api.routers.memory.dependencies._resolve_control_user_content_clear",
            "Control plane not initialized",
            id="memory_clear_rejects_when_control_boundary_is_unavailable",
        ),
        pytest.param(
            "magi.api.routers.memory.dependencies._resolve_plugin_user_content_clear",
            "Plugin runtime not initialized",
            id="memory_clear_rejects_when_plugin_boundary_is_unavailable",
        ),
        pytest.param(
            "magi.api.routers.memory.dependencies._resolve_chat_memory_projection_clear",
            "Chat recovery service not initialized",
            id="memory_clear_rejects_when_chat_recovery_boundary_is_unavailable",
        ),
    ],
)
def test_memory_clear_requires_all_runtime_boundaries(
    monkeypatch, resolver_path, unavailable_message
):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    unified = _FakeUnifiedMemory()
    unified.clear_all_memory = AsyncMock()
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: unified)
    monkeypatch.setattr(resolver_path, lambda: None)
    with language_context("en"):
        response = TestClient(app).delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)
    assert response.status_code == 503
    assert response.json()["detail"] == unavailable_message
    unified.clear_all_memory.assert_not_awaited()


def test_plugin_clear_failure_does_not_skip_scheduler_chat_or_log_cleanup(
    monkeypatch,
    _isolate_scheduler_clear_boundary,
    _isolate_diagnostic_log_cleanup,
) -> None:
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    chat_clear = AsyncMock(return_value=2)
    chat_complete = AsyncMock(return_value=True)

    class _ChatReadService:
        aclear_all_sessions = chat_clear
        acomplete_global_clear = chat_complete

    class _FailedPluginClearSession:
        def mark_surrounding_clear_failed(self, _error):  # type: ignore[no-untyped-def]
            return None

        async def clear_user_content(self, request):  # type: ignore[no-untyped-def]
            assert request.clear_generation == 1
            raise RuntimeError("plugin cache unavailable")

    @asynccontextmanager
    async def plugin_boundary():
        yield _FailedPluginClearSession()

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        _FakeUnifiedMemory,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service",
        lambda: _ChatReadService(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_plugin_user_content_clear",
        lambda: SimpleNamespace(user_content_clear_boundary=plugin_boundary),
    )

    response = TestClient(app, raise_server_exceptions=False).delete(
        "/api/memory/clear", headers=FULL_CLEAR_HEADERS
    )

    assert response.status_code == 500
    _isolate_scheduler_clear_boundary.clear_user_data.assert_awaited_once_with()
    chat_clear.assert_awaited_once_with()
    chat_complete.assert_awaited_once_with()
    _isolate_diagnostic_log_cleanup.assert_awaited_once_with()


def test_plugin_clear_recovery_failure_is_not_reported_as_success(
    monkeypatch,
    _isolate_diagnostic_log_cleanup,
) -> None:
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")

    @asynccontextmanager
    async def plugin_boundary():
        yield SimpleNamespace(clear_user_content=AsyncMock(return_value=None))
        raise PluginUserContentClearRecoveryError(
            clear_error=None,
            recovery_error=RuntimeError("executor restart failed"),
        )

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        _FakeUnifiedMemory,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_plugin_user_content_clear",
        lambda: SimpleNamespace(user_content_clear_boundary=plugin_boundary),
    )

    response = TestClient(app, raise_server_exceptions=False).delete(
        "/api/memory/clear", headers=FULL_CLEAR_HEADERS
    )

    assert response.status_code == 500
    _isolate_diagnostic_log_cleanup.assert_awaited_once_with()


@pytest.fixture
async def durable_clear_queue(
    monkeypatch, runtime_paths_with_schema, _isolate_user_message_clear_boundary
):
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    queue = SQLiteRuntimeCommandQueue(db_path=str(runtime_paths_with_schema.message_queue_db_path))
    await queue.start()
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_runtime_command_queue", lambda: queue)
    try:
        yield queue
    finally:
        await queue.stop()


async def _assert_full_clear_pending_after_restart(queue):
    from magi.events.runtime_queue import (
        FullUserContentClearConflictError,
        SQLiteRuntimeCommandQueue,
    )

    await queue.stop()
    reopened = SQLiteRuntimeCommandQueue(db_path=queue.db_path)
    await reopened.start()
    try:
        state = await reopened.read_full_user_content_clear_state()
        assert state.status == "pending"
        assert state.transaction_id == FULL_CLEAR_TRANSACTION_ID
        assert state.started_at is not None
        with pytest.raises(
            FullUserContentClearConflictError, match="Another full user-content clear"
        ):
            await reopened.begin_full_user_content_clear("different-clear-transaction")
    finally:
        await reopened.stop()


@pytest.mark.asyncio
async def test_memory_clear_keeps_global_intent_when_background_history_cleanup_fails(
    monkeypatch,
    durable_clear_queue,
) -> None:
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    finalize = AsyncMock(return_value=True)

    class _ChatReadService:
        async def aclear_all_sessions(self) -> int:
            return 1

        acomplete_global_clear = finalize

    @asynccontextmanager
    async def boundary(**_kwargs):  # type: ignore[no-untyped-def]
        yield

    background_task_manager = SimpleNamespace(
        conversation_scope_boundary=boundary,
        clear_all_history=AsyncMock(side_effect=OSError("background task database unavailable")),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service",
        lambda: _ChatReadService(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_background_task_manager",
        lambda: background_task_manager,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(RuntimeError, match="background_task_history_cleanup_failed"):
            await client.delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)
    await _assert_full_clear_pending_after_restart(durable_clear_queue)
    background_task_manager.clear_all_history.assert_awaited_once()
    finalize.assert_not_awaited()


def test_memory_clear_resumes_rebuild_starts_when_pause_fails(monkeypatch):
    from magi.api.routers.memory.embedding_routes import _embedding_rebuild_manager

    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    pause = AsyncMock(side_effect=RuntimeError("cancel persistence failed"))
    resume = AsyncMock(side_effect=RuntimeError("rebuild resume failed"))
    task_agent_manager = SimpleNamespace(
        pause_chat_work_and_cancel_all=AsyncMock(),
        resume_chat_work=AsyncMock(),
    )
    monkeypatch.setattr(_embedding_rebuild_manager, "pause_starts_and_cancel_all", pause)
    monkeypatch.setattr(_embedding_rebuild_manager, "resume_starts", resume)
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_task_agent_manager",
        lambda: task_agent_manager,
    )

    with pytest.raises(RuntimeError, match="cancel persistence failed"):
        TestClient(app).delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)

    pause.assert_awaited_once()
    resume.assert_awaited_once()
    task_agent_manager.pause_chat_work_and_cancel_all.assert_not_awaited()
    task_agent_manager.resume_chat_work.assert_not_awaited()


def test_memory_clear_recovers_all_dependencies_when_chat_pause_fails(monkeypatch):
    from magi.api.routers.memory.embedding_routes import _embedding_rebuild_manager

    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    unified = _FakeUnifiedMemory()
    unified.clear_all_memory = AsyncMock()  # type: ignore[method-assign]
    task_agent_manager = SimpleNamespace(
        pause_chat_work_and_cancel_all=AsyncMock(side_effect=RuntimeError("chat pause failed")),
        resume_chat_work=AsyncMock(side_effect=RuntimeError("chat resume failed")),
    )
    rebuild_pause = AsyncMock()
    rebuild_resume = AsyncMock(side_effect=RuntimeError("rebuild resume failed"))
    monkeypatch.setattr(_embedding_rebuild_manager, "pause_starts_and_cancel_all", rebuild_pause)
    monkeypatch.setattr(_embedding_rebuild_manager, "resume_starts", rebuild_resume)
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: unified,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_task_agent_manager",
        lambda: task_agent_manager,
    )

    with pytest.raises(RuntimeError, match="chat pause failed"):
        TestClient(app).delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)

    rebuild_pause.assert_awaited_once()
    task_agent_manager.pause_chat_work_and_cancel_all.assert_awaited_once()
    unified.clear_all_memory.assert_not_awaited()
    task_agent_manager.resume_chat_work.assert_awaited_once()
    rebuild_resume.assert_awaited_once()


def test_memory_clear_resumes_services_when_queue_generation_advance_fails(
    monkeypatch,
    _isolate_user_message_clear_boundary,
):
    from magi.api.routers.memory.embedding_routes import _embedding_rebuild_manager

    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    queue, _ = _isolate_user_message_clear_boundary
    queue.advance_user_message_generation_and_purge = AsyncMock(
        side_effect=OSError("queue generation write failed")
    )
    unified = _FakeUnifiedMemory()
    unified.clear_all_memory = AsyncMock()  # type: ignore[method-assign]
    task_agent_manager = SimpleNamespace(
        pause_chat_work_and_cancel_all=AsyncMock(),
        resume_chat_work=AsyncMock(),
    )
    rebuild_resume = AsyncMock()
    monkeypatch.setattr(_embedding_rebuild_manager, "resume_starts", rebuild_resume)
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: unified,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_task_agent_manager",
        lambda: task_agent_manager,
    )

    with pytest.raises(OSError, match="queue generation write failed"):
        TestClient(app).delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)

    unified.clear_all_memory.assert_not_awaited()
    task_agent_manager.resume_chat_work.assert_awaited_once()
    rebuild_resume.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_memory_clear_resets_surviving_turn_for_real_retry(
    monkeypatch,
    runtime_paths_with_schema,
):
    import sqlite3

    from magi.api.routers.memory.embedding_routes import _embedding_rebuild_manager
    from magi.api.routers.memory.overview_routes import clear_memory_layers
    from magi.chat import first_context_projection as projection_confirmation
    from magi.chat import ingress as ingress_service
    from magi.chat.projector import ChatProjector
    from magi.chat.store import ChatStore
    from magi.chat.read_service import ChatReadService
    from magi.events.events import Event
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue
    from magi.memory.event_translation import translate
    from magi.memory.l1.event_store import L1EventStore
    from magi.utils import runtime as runtime_module

    class _PersistingBus:
        def __init__(self) -> None:
            self.calls = 0

        async def publish(self, event: Event) -> bool:
            self.calls += 1
            memory_event = translate(event)
            assert memory_event is not None
            await l1.store(memory_event)
            return True

    class _FailingUnifiedMemory:
        async def clear_all_memory(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            await l1.clear(restart_workers=False)
            raise OSError("memory database failed midway")

    monkeypatch.setattr(runtime_module, "_runtime_paths", runtime_paths_with_schema)

    queue = SQLiteRuntimeCommandQueue(db_path=str(runtime_paths_with_schema.message_queue_db_path))
    await queue.start()
    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    l1 = L1EventStore(
        db_path=str(runtime_paths_with_schema.l1_memory_db_path),
        vector_enabled=False,
    )
    await l1.initialize()
    bus = _PersistingBus()
    projector = ChatProjector(event_bus=bus)
    # This fixture enables L1 only; confirmation must read its committed receipt.
    projection_memory = MemoryApiStub(
        l1=l1,
        l2=None,
        _chat_projection_has_forget_receipt=AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        projection_confirmation,
        "_resolve_projection_memory",
        lambda: projection_memory,
    )
    monkeypatch.setattr(
        projection_confirmation,
        "_memory_layer_enabled",
        lambda layer: layer == "l1",
    )
    read_service = ChatReadService(runtime_paths=runtime_paths_with_schema)
    read_service.aclear_all_sessions = AsyncMock(
        side_effect=AssertionError("Failed memory clear must not reach chat deletion")
    )

    monkeypatch.setattr(
        ingress_service,
        "require_runtime_command_queue",
        lambda: queue,
    )
    monkeypatch.setattr(ingress_service, "get_chat_store", lambda: store)
    monkeypatch.setattr(ingress_service, "get_chat_projector", lambda: projector)
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_runtime_command_queue",
        lambda: queue,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: _FailingUnifiedMemory(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_task_agent_manager",
        lambda: None,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_source_hub",
        lambda: None,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_manual_entry_asset_store",
        lambda: None,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service",
        lambda: read_service,
    )
    monkeypatch.setattr(
        _embedding_rebuild_manager,
        "pause_starts_and_cancel_all",
        AsyncMock(),
    )
    monkeypatch.setattr(
        _embedding_rebuild_manager,
        "resume_starts",
        AsyncMock(),
    )

    request = {
        "source": "api",
        "user_id": "u1",
        "message": "survive a partial clear",
        "session_id": "session-clear-retry",
        "client_turn_id": "turn-clear-retry",
    }
    try:
        initial = await ingress_service.dispatch_user_message(**request)
        assert initial.success is True
        assert await l1.count_events() == 1
        initial_delivery = await store.get_user_turn_delivery(turn_id=request["client_turn_id"])
        assert initial_delivery is not None and initial_delivery.projection_completed is True

        with pytest.raises(OSError, match="memory database failed midway"):
            await clear_memory_layers(FULL_CLEAR_TRANSACTION_ID)
        assert await l1.count_events() == 0
        read_service.aclear_all_sessions.assert_not_awaited()

        with sqlite3.connect(runtime_paths_with_schema.chat_db_path) as conn:
            assert conn.execute("""
                SELECT projection_completed, delivery_attempt_no,
                       delivery_state, current_command_id
                FROM chat_user_turn_delivery
                WHERE turn_id = 'turn-clear-retry'
                """).fetchone() == (0, 1, "ready", None)
        with sqlite3.connect(runtime_paths_with_schema.message_queue_db_path) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM runtime_commands WHERE command_type = 'user_message'"
            ).fetchone() == (0,)
            assert conn.execute(
                "SELECT COUNT(*) FROM runtime_user_message_idempotency"
            ).fetchone() == (0,)

        retried = await ingress_service.dispatch_user_message(**request)
        assert retried.success is True
        assert retried.message_id == initial.message_id
        assert bus.calls == 2
        with sqlite3.connect(runtime_paths_with_schema.l1_memory_db_path) as conn:
            assert conn.execute(
                "SELECT content FROM fact_events WHERE idempotency_key = ?",
                (initial.message_id,),
            ).fetchall() == [(request["message"],)]
        with sqlite3.connect(runtime_paths_with_schema.chat_db_path) as conn:
            assert conn.execute("""
                SELECT projection_completed, delivery_attempt_no,
                       delivery_state, current_command_id
                FROM chat_user_turn_delivery
                WHERE turn_id = 'turn-clear-retry'
                """).fetchone() == (1, 1, "queued", 2)
        assert (await queue.get_stats())["pending_count"] == 1
    finally:
        read_service.close()
        await l1.shutdown()
        await queue.stop()


def test_memory_clear_finishes_data_clear_when_source_queue_cleanup_fails(
    monkeypatch,
    _isolate_user_message_clear_boundary,
):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    queue, source_hub = _isolate_user_message_clear_boundary
    source_hub.discard_stale_user_messages = AsyncMock(
        side_effect=RuntimeError("source queue cleanup failed")
    )
    unified = _FakeUnifiedMemory()
    unified.clear_all_memory = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "l0": 0,
            "l1": 0,
            "l2": 0,
            "l3": 0,
            "l4": 0,
            "chat_context": 0,
        }
    )
    task_agent_manager = SimpleNamespace(
        pause_chat_work_and_cancel_all=AsyncMock(),
        resume_chat_work=AsyncMock(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: unified,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_task_agent_manager",
        lambda: task_agent_manager,
    )

    response = TestClient(app, raise_server_exceptions=False).delete(
        "/api/memory/clear", headers=FULL_CLEAR_HEADERS
    )

    assert response.status_code == 500
    assert queue.full_clear_transaction_id == FULL_CLEAR_TRANSACTION_ID
    assert queue.full_clear_completed_transaction_id is None
    unified.clear_all_memory.assert_awaited_once()
    task_agent_manager.resume_chat_work.assert_awaited_once()


def test_memory_clear_fails_when_diagnostic_logs_cannot_be_fully_erased(
    monkeypatch,
    _isolate_diagnostic_log_cleanup,
) -> None:
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    _isolate_diagnostic_log_cleanup.return_value = SimpleNamespace(
        cleared_entries=3,
        failed_entries=1,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )
    boundary_failures: list[BaseException] = []

    class _LogFailureSession:
        clear_user_content = AsyncMock(return_value=None)

        def mark_surrounding_clear_failed(self, error):  # type: ignore[no-untyped-def]
            boundary_failures.append(error)

    @asynccontextmanager
    async def plugin_boundary():
        yield _LogFailureSession()

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_plugin_user_content_clear",
        lambda: SimpleNamespace(user_content_clear_boundary=plugin_boundary),
    )

    response = TestClient(app, raise_server_exceptions=False).delete(
        "/api/memory/clear", headers=FULL_CLEAR_HEADERS
    )

    assert response.status_code == 500
    assert len(boundary_failures) == 1


@pytest.mark.asyncio
async def test_memory_clear_remains_pending_when_physical_chat_cleanup_is_pending(
    monkeypatch,
    durable_clear_queue,
) -> None:
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )

    class _PendingChatClear:
        async def aclear_all_sessions(self) -> int:
            raise OSError("simulated asset cleanup failure")

        async def aget_interrupted_global_clear_count(self) -> int:
            return 3

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service",
        lambda: _PendingChatClear(),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(RuntimeError, match="chat_asset_cleanup_pending"):
            await client.delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)
    await _assert_full_clear_pending_after_restart(durable_clear_queue)


def test_memory_clear_blocks_outreach_and_clears_channel_conversation_state(
    monkeypatch,
) -> None:
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    outreach_boundary_active = False
    channel_boundary_active = False
    events: list[str] = []

    class _OutreachService:
        @asynccontextmanager
        async def conversation_clear_boundary(self):
            nonlocal outreach_boundary_active
            outreach_boundary_active = True
            events.append("outreach-paused")
            try:
                yield
            finally:
                events.append("outreach-resumed")
                outreach_boundary_active = False

    class _ChannelsModule:
        @asynccontextmanager
        async def conversation_clear_boundary(self):
            nonlocal channel_boundary_active
            channel_boundary_active = True
            events.append("channel-delivery-paused")
            try:
                yield
            finally:
                events.append("channel-delivery-resumed")
                channel_boundary_active = False

    class _ChatReadService:
        async def aclear_all_sessions(self) -> int:
            assert outreach_boundary_active is True
            assert channel_boundary_active is True
            events.append("chat-cleared")
            return 2

        async def acomplete_global_clear(self) -> bool:
            assert outreach_boundary_active is True
            assert channel_boundary_active is True
            events.append("conversation-clear-finalized")
            return True

    class _ChannelSessionMapper:
        async def clear_conversation_state(self) -> dict[str, int]:
            assert outreach_boundary_active is True
            assert channel_boundary_active is True
            events.append("channel-state-cleared")
            return {"channel_session_mappings": 1, "outreach_outbox": 1}

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_outreach_service",
        lambda: _OutreachService(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_channels_module",
        lambda: _ChannelsModule(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_channel_session_mapper",
        lambda: _ChannelSessionMapper(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service",
        lambda: _ChatReadService(),
    )

    response = TestClient(app).delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)

    assert response.status_code == 200
    assert response.json()["results"]["chat_context"]["count"] == 2
    assert events == [
        "outreach-paused",
        "channel-delivery-paused",
        "chat-cleared",
        "channel-state-cleared",
        "conversation-clear-finalized",
        "channel-delivery-resumed",
        "outreach-resumed",
    ]


@pytest.mark.asyncio
async def test_memory_clear_keeps_global_barrier_when_finalization_is_declined(
    monkeypatch,
    durable_clear_queue,
) -> None:
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    finalize = AsyncMock(return_value=False)

    class _ChatReadService:
        async def aclear_all_sessions(self) -> int:
            return 1

        acomplete_global_clear = finalize

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service",
        lambda: _ChatReadService(),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(RuntimeError, match="conversation_clear_finalization_failed"):
            await client.delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)
    await _assert_full_clear_pending_after_restart(durable_clear_queue)
    finalize.assert_awaited_once()


def test_memory_clear_warns_when_channel_conversation_cleanup_fails(
    monkeypatch,
) -> None:
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    finalize = AsyncMock(return_value=True)

    class _ChannelSessionMapper:
        async def clear_conversation_state(self) -> dict[str, int]:
            raise OSError("channels database is unavailable")

    class _ChatReadService:
        async def aclear_all_sessions(self) -> int:
            return 1

        acomplete_global_clear = finalize

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_channel_session_mapper",
        lambda: _ChannelSessionMapper(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service",
        lambda: _ChatReadService(),
    )

    response = TestClient(app, raise_server_exceptions=False).delete(
        "/api/memory/clear", headers=FULL_CLEAR_HEADERS
    )

    assert response.status_code == 500
    finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_memory_clear_remains_pending_when_memory_writers_fail_to_resume(
    monkeypatch,
    durable_clear_queue,
) -> None:
    from magi.memory.store_lifecycle import MemoryClearCompletedWithRecoveryError

    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )

    class _ClearThenFailResume:
        async def clear_all_memory(
            self,
            *,
            auxiliary_clearers=(),
            context_clearer=None,
            user_content_clear_boundaries=(),
        ) -> dict[str, int]:
            _ = user_content_clear_boundaries
            for clearer in auxiliary_clearers:
                result = clearer()
                if hasattr(result, "__await__"):
                    await result
            chat_count = await context_clearer()
            failure = RuntimeError("memory writer restart failed")
            raise MemoryClearCompletedWithRecoveryError(
                counts={
                    "l0": 1,
                    "l1": 2,
                    "l2": 3,
                    "l3": 4,
                    "l4": 5,
                    "chat_context": chat_count,
                },
                recovery_error=failure,
            )

    class _FakeChatReadService:
        async def aclear_all_sessions(self) -> int:
            return 2

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: _ClearThenFailResume(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service",
        lambda: _FakeChatReadService(),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(RuntimeError, match="memory_writer_resume_failed"):
            await client.delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)
    await _assert_full_clear_pending_after_restart(durable_clear_queue)


def test_memory_clear_keeps_clear_error_when_both_recovery_steps_fail(monkeypatch):
    from magi.api.routers.memory.embedding_routes import _embedding_rebuild_manager

    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    unified = _FakeUnifiedMemory()
    unified.clear_all_memory = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("clear failed")
    )
    task_agent_manager = SimpleNamespace(
        pause_chat_work_and_cancel_all=AsyncMock(),
        resume_chat_work=AsyncMock(side_effect=RuntimeError("chat resume failed")),
    )
    rebuild_pause = AsyncMock()
    rebuild_resume = AsyncMock(side_effect=RuntimeError("rebuild resume failed"))
    monkeypatch.setattr(_embedding_rebuild_manager, "pause_starts_and_cancel_all", rebuild_pause)
    monkeypatch.setattr(_embedding_rebuild_manager, "resume_starts", rebuild_resume)
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: unified,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_task_agent_manager",
        lambda: task_agent_manager,
    )

    with pytest.raises(RuntimeError, match="clear failed"):
        TestClient(app).delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)

    task_agent_manager.resume_chat_work.assert_awaited_once()
    rebuild_resume.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_clear_remains_pending_when_chat_resume_fails(
    monkeypatch, durable_clear_queue
):
    from magi.api.routers.memory.embedding_routes import _embedding_rebuild_manager

    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    task_agent_manager = SimpleNamespace(
        pause_chat_work_and_cancel_all=AsyncMock(),
        resume_chat_work=AsyncMock(side_effect=RuntimeError("chat resume failed")),
    )
    rebuild_pause = AsyncMock()
    rebuild_resume = AsyncMock()
    monkeypatch.setattr(_embedding_rebuild_manager, "pause_starts_and_cancel_all", rebuild_pause)
    monkeypatch.setattr(_embedding_rebuild_manager, "resume_starts", rebuild_resume)
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_task_agent_manager",
        lambda: task_agent_manager,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(
            RuntimeError, match="chat_resume_failed"
        ):
            await client.delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)
    await _assert_full_clear_pending_after_restart(durable_clear_queue)
    task_agent_manager.resume_chat_work.assert_awaited_once()
    rebuild_resume.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_clear_remains_pending_when_rebuild_resume_fails(
    monkeypatch, durable_clear_queue
):
    from magi.api.routers.memory.embedding_routes import _embedding_rebuild_manager

    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    task_agent_manager = SimpleNamespace(
        pause_chat_work_and_cancel_all=AsyncMock(),
        resume_chat_work=AsyncMock(),
    )
    rebuild_pause = AsyncMock()
    rebuild_resume = AsyncMock(side_effect=RuntimeError("rebuild resume failed"))
    monkeypatch.setattr(_embedding_rebuild_manager, "pause_starts_and_cancel_all", rebuild_pause)
    monkeypatch.setattr(_embedding_rebuild_manager, "resume_starts", rebuild_resume)
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_task_agent_manager",
        lambda: task_agent_manager,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(
            RuntimeError, match="embedding_rebuild_resume_failed"
        ):
            await client.delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)
    await _assert_full_clear_pending_after_restart(durable_clear_queue)
    task_agent_manager.resume_chat_work.assert_awaited_once()
    rebuild_resume.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_clear_keeps_global_intent_when_batch_cleanup_fails(
    monkeypatch, durable_clear_queue
):
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    finalize = AsyncMock(return_value=True)

    class _FakeChatReadService:
        async def aclear_all_sessions(self) -> int:
            return 1

        acomplete_global_clear = finalize

    batch_store = SimpleNamespace(clear_all=AsyncMock(side_effect=OSError("batch disk full")))
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_batch_store",
        lambda: batch_store,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service",
        lambda: _FakeChatReadService(),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(RuntimeError, match="batch_cleanup_failed"):
            await client.delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)
    await _assert_full_clear_pending_after_restart(durable_clear_queue)
    batch_store.clear_all.assert_awaited_once_with()
    finalize.assert_not_awaited()


@pytest.mark.parametrize(
    "resolver,method,is_async",
    [
        ("_resolve_manual_entry_weather_fetcher", "clear", True),
        ("_resolve_self_memory", "clear_learned_state", True),
    ],
)
def test_full_clear_invokes_auxiliary_content_owners(monkeypatch, resolver, method, is_async):
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    clear = AsyncMock(return_value=2) if is_async else Mock(return_value=2)
    owner = SimpleNamespace(**{method: clear}) if method else clear
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", _FakeUnifiedMemory)
    monkeypatch.setattr(f"magi.api.routers.memory.dependencies.{resolver}", lambda: owner)
    response = TestClient(app).delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)
    assert response.status_code == 200
    if is_async:
        clear.assert_awaited_once_with()
    else:
        clear.assert_called_once_with()


@pytest.mark.parametrize(
    "resolver,boundary_method",
    [
        ("_resolve_chat_portrait_service", "global_data_clear_boundary"),
        ("_resolve_runtime_trace_store", "plugin_ingress_global_clear_boundary"),
    ],
)
@pytest.mark.parametrize("clear_fails", [False, True])
def test_full_clear_holds_and_releases_external_boundaries(
    monkeypatch, resolver, boundary_method, clear_fails
):
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    sequence = []
    active = False

    @asynccontextmanager
    async def boundary():
        nonlocal active
        active = True
        sequence.append("enter")
        try:
            yield
        finally:
            active = False
            sequence.append("exit")

    class Memory(_FakeUnifiedMemory):
        async def clear_all_memory(self, **kwargs):
            assert active
            sequence.append("clear")
            if clear_fails:
                raise RuntimeError("clear failed")
            return await super().clear_all_memory(**kwargs)

    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", Memory)
    monkeypatch.setattr(
        f"magi.api.routers.memory.dependencies.{resolver}",
        lambda: SimpleNamespace(**{boundary_method: boundary}),
    )
    response = TestClient(app, raise_server_exceptions=False).delete(
        "/api/memory/clear", headers=FULL_CLEAR_HEADERS
    )
    assert response.status_code == (500 if clear_fails else 200)
    assert sequence == ["enter", "clear", "exit"]
    assert active is False


def test_memory_clear_holds_runtime_projection_boundaries_and_erases_usage(
    monkeypatch,
) -> None:
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    runtime_trace_active = False
    llm_usage_active = False

    class _RuntimeTraceSubscriber:
        @asynccontextmanager
        async def user_content_clear_boundary(self):
            nonlocal runtime_trace_active
            runtime_trace_active = True
            try:
                yield
            finally:
                runtime_trace_active = False

    class _LLMUsageSubscriber:
        @asynccontextmanager
        async def user_content_clear_boundary(self):
            nonlocal llm_usage_active
            llm_usage_active = True
            try:
                yield
            finally:
                llm_usage_active = False

    async def clear_usage() -> int:
        assert runtime_trace_active is True
        assert llm_usage_active is True
        return 3

    llm_usage_store = SimpleNamespace(clear_user_content=AsyncMock(side_effect=clear_usage))
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        _FakeUnifiedMemory,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_runtime_trace_subscriber",
        _RuntimeTraceSubscriber,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_llm_usage_subscriber",
        _LLMUsageSubscriber,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_llm_usage_store",
        lambda: llm_usage_store,
    )

    response = TestClient(app).delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)

    assert response.status_code == 200
    llm_usage_store.clear_user_content.assert_awaited_once_with()
    assert runtime_trace_active is False
    assert llm_usage_active is False


def test_registered_memory_clear_api_is_public(monkeypatch):
    app = FastAPI()
    register_api_routes(app)

    class _FakeChatReadService:
        async def aclear_all_sessions(self) -> int:
            return 4

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: _FakeUnifiedMemory()
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies.get_chat_read_service", lambda: _FakeChatReadService()
    )

    client = TestClient(app)
    response = client.delete("/api/memory/clear", headers=FULL_CLEAR_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["results"]["l1"]["count"] == 12
    assert body["results"]["chat_context"]["count"] == 4


def test_memory_l1_events_api_returns_canonical_user_and_content(monkeypatch):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: _FakeUnifiedMemory()
    )
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_memory_integration", lambda: None)

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
    assert body["items"][0]["metadata_json"] == {
        "activity_snapshot": {"source_app": "Chrome", "title": "hello"}
    }
    assert body["items"][0]["embedding_status"] == "ready"
    assert body["items"][0]["embedding_profile_id"] == "profile-a"
    assert body["total"] == 12


def test_memory_l1_events_api_excludes_audit_only_records(monkeypatch):
    app = FastAPI()
    register_api_routes(app)

    memory = _FakeUnifiedMemory()
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: memory)
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_memory_integration", lambda: None)

    response = TestClient(app).get("/api/memory/l1/events")

    assert response.status_code == 200
    expected_scopes = [
        scope.label for scope in L1RetrievalScope if scope != L1RetrievalScope.AUDIT_ONLY
    ]
    assert memory.l1.last_query_kwargs["l1_retrieval_scopes"] == expected_scopes
    assert memory.l1.last_count_kwargs["l1_retrieval_scopes"] == expected_scopes
    assert L1RetrievalScope.AUDIT_ONLY.label not in expected_scopes


def test_memory_route_and_request_guard_share_dependency(monkeypatch):
    calls = []

    @asynccontextmanager
    async def guard():
        calls.append("enter")
        yield
        calls.append("exit")

    async def search(**kwargs):
        assert calls == ["enter"]
        calls.append("read")
        return []

    memory = MemoryApiStub(
        l2=SimpleNamespace(list_episodes=search, count_episodes=AsyncMock(return_value=0)),
        memory_operation_guard=guard,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: memory
    )
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]),
        prefix="/api/memory",
    )

    response = TestClient(app).get("/api/memory/l2/episodes")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert calls == ["enter", "read", "exit"]


def test_memory_episode_lists_do_not_expose_invalidated_content(monkeypatch):
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")
    l2 = SimpleNamespace(
        list_episodes=AsyncMock(),
        count_episodes=AsyncMock(),
        list_experiences=AsyncMock(),
    )
    unified = MemoryApiStub(l2=l2)
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory",
        lambda: unified,
    )

    client = TestClient(app)
    episodes = client.get("/api/memory/l2/episodes", params={"status": "invalidated"})
    experiences = client.get(
        "/api/memory/l2/experiences",
        params={"status": "invalidated"},
    )

    assert episodes.status_code == 200
    assert episodes.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
    assert experiences.status_code == 200
    assert experiences.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
    l2.list_episodes.assert_not_awaited()
    l2.count_episodes.assert_not_awaited()
    l2.list_experiences.assert_not_awaited()


@pytest.mark.parametrize(
    "identity",
    [
        {},
        {"event_id": "evt-worker-1"},
        {"source_item_id": "chrome:181979-181982", "idempotency_key": "default:181979-181982"},
    ],
)
def test_memory_l1_events_api_forwards_search_filters(monkeypatch, identity):
    from datetime import datetime

    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )

    memory = _FakeUnifiedMemory()
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: memory)
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_memory_integration", lambda: None)

    client = TestClient(app)
    response = client.get(
        "/api/memory/l1/events",
        params={
            **identity,
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
    assert memory.l1.last_query_kwargs["exclude_event_types"] is None
    assert memory.l1.last_query_kwargs["limit"] == 50
    assert memory.l1.last_query_kwargs["include_metadata_json"] is True
    assert memory.l1.last_query_kwargs["include_embedding_fields"] is True
    assert memory.l1.last_query_kwargs["start_time"] == datetime(2026, 3, 1).timestamp()
    assert (
        memory.l1.last_query_kwargs["end_time"]
        == datetime(2026, 3, 2, 23, 59, 59, 999999).timestamp()
    )
    assert memory.l1.last_count_kwargs == {
        key: value
        for key, value in memory.l1.last_query_kwargs.items()
        if key not in {"limit", "offset", "include_metadata_json", "include_embedding_fields"}
    }

    for key in ["event_id", "source_item_id", "idempotency_key"]:
        assert memory.l1.last_query_kwargs[key] == identity.get(key)


@pytest.mark.parametrize("l2_enabled", [True, False])
@pytest.mark.parametrize(
    "event,deleted,status_code",
    [
        ({"event_id": "evt-1", "source": "chat", "deleted_at": None}, True, 200),
        ({"event_id": "evt-1", "source": "chat", "deleted_at": 123.0}, True, 200),
        (None, False, 404),
    ],
)
def test_event_delete_maps_governed_result_and_accepts_hidden_chat_retries(
    monkeypatch, l2_enabled, event, deleted, status_code
):
    app = FastAPI()
    register_api_routes(app)
    memory = MemoryApiStub(
        l1=SimpleNamespace(get_event=AsyncMock(return_value=event)),
        l2=object() if l2_enabled else None,
        forget_source_event=AsyncMock(return_value=deleted),
    )
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: memory)
    response = TestClient(app).delete("/api/memory/l1/events/evt-1")
    assert response.status_code == status_code
    memory.l1.get_event.assert_awaited_once_with("evt-1")
    memory.forget_source_event.assert_awaited_once_with("evt-1", reason="user_delete_event")
    if deleted:
        assert response.json() == {
            "event_id": "evt-1",
            "deleted": True,
            "deletion_scope": "projected_memory_only",
        }


@pytest.mark.parametrize("event_id,deleted_at", [("evt-1", None), ("evt-old", 123.0)])
def test_manual_entry_projection_cannot_bypass_source_owned_deletion(
    monkeypatch, event_id, deleted_at
):
    app = FastAPI()
    register_api_routes(app)
    memory = MemoryApiStub(
        l1=SimpleNamespace(
            get_event=AsyncMock(
                return_value={
                    "event_id": event_id,
                    "source": "manual_entry",
                    "source_item_id": "manual-1",
                    "deleted_at": deleted_at,
                }
            )
        ),
        forget_source_event=AsyncMock(return_value=True),
    )
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: memory)
    response = TestClient(app).delete(f"/api/memory/l1/events/{event_id}")
    assert response.status_code == 409
    memory.l1.get_event.assert_awaited_once_with(event_id)
    memory.forget_source_event.assert_not_awaited()


def test_memory_governance_action_routes_are_publicly_allowlisted():
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    route_methods = {
        route.path: route.methods for route in public.routes if hasattr(route, "methods")
    }

    assert "DELETE" in route_methods["/l1/events/{event_id}"]
    assert "/l2/edges/{triple_id}/reject" not in route_methods
    assert "POST" in route_methods["/forget/entity"]
    assert "POST" in route_methods["/forget/time-range"]
    assert "POST" in route_methods["/forget/episode"]
    assert not set(route_methods).intersection(
        {
            "/l2/manual-event",
            "/l2/extract/{event_id}",
            "/l2/reconcile",
            "/l2/snapshot-refresh",
        }
    )


@pytest.mark.parametrize(
    "path,method,selector",
    [
        ("entity", "forget_entity_memory", {"entity_id": "user:u1"}),
        ("time-range", "forget_time_range_memory", {"start": 100.0, "end": 200.0}),
    ],
)
@pytest.mark.parametrize("delete_l1", [False, True])
def test_forget_route_forwards_scope_and_source_deletion_choice(
    monkeypatch, path, method, selector, delete_l1
):
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    result = {"l2_counts": {"relations": 2}, "l1_events_deleted": 3 if delete_l1 else 0}
    forget = AsyncMock(return_value=result)
    memory = MemoryApiStub(l1=object(), l2=object(), **{method: forget})
    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: memory
    )
    response = TestClient(app).post(
        f"/api/memory/forget/{path}", json={**selector, "delete_l1_events": delete_l1}
    )
    assert response.status_code == 200
    assert response.json() == result
    forget.assert_awaited_once_with(**selector, delete_l1_events=delete_l1)


def test_memory_l2_conflict_rule_api_rejects_invalid_combinations(monkeypatch):
    class _RejectingL2Store(_FakeL2Store):
        async def upsert_graph_conflict_rule(self, payload):
            raise ValueError(
                "exclusive_group is required when exclusive_resolution overrides the default"
            )

    class _RejectingUnifiedMemory(_FakeUnifiedMemory):
        def __init__(self):
            super().__init__()
            self.l2 = _RejectingL2Store()

    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory")

    monkeypatch.setattr(
        "magi.api.routers.memory.dependencies._resolve_unified_memory", lambda: _RejectingUnifiedMemory()
    )
    monkeypatch.setattr("magi.api.routers.memory.dependencies._resolve_memory_integration", lambda: None)

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
