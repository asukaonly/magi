from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.evidence import (
    EVIDENCE_RULE_VERSION,
    EvidenceClass,
    EvidenceStatus,
    L1RetrievalScope,
)
from magi.memory.embedding.sqlite_vec_index import VectorSearchHit
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
    author_type_code,
    content_type_code,
    normalize_runtime_event,
)
from magi.memory.l1.chat_sessions import CHAT_SESSIONS_TABLE
from magi.memory.l1.embeddings.common import embedding_status_code


def _migrated_l1_db_path(tmp_path):
    from magi.db.runner import MIGRATION_TARGETS, run_upgrade_head
    from magi.utils.runtime import RuntimePaths

    runtime_paths = RuntimePaths(base_dir=tmp_path / "runtime")
    l1_target = next(target for target in MIGRATION_TARGETS if target.name == "l1")

    run_upgrade_head(runtime_paths, targets=(l1_target,))
    return runtime_paths.l1_memory_db_path


def test_l1_migration_adds_event_evidence_defaults(tmp_path):
    db_path = _migrated_l1_db_path(tmp_path)

    with sqlite3.connect(db_path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(fact_events)")}
        indexes = {row[1] for row in db.execute("PRAGMA index_list(fact_events)")}
        db.execute(
            """
            INSERT INTO fact_events(
                event_id, timestamp, created_at,
                event_type, source, memory_domain, cognition_eligible,
                retention_class, content, author_type, content_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "evt-evidence-defaults",
                1710000000.0,
                1710000000.0,
                "UserMessage",
                "chat",
                int(MemoryDomain.USER_AUTHORED),
                1,
                int(RetentionClass.COMPRESSIBLE),
                "I like tea.",
                author_type_code("user"),
                content_type_code("text"),
            ),
        )
        row = db.execute(
            """
            SELECT evidence_status, evidence_class, l1_retrieval_scope, evidence_rule_version
            FROM fact_events
            WHERE event_id = ?
            """,
            ("evt-evidence-defaults",),
        ).fetchone()

    assert "evidence_status" in columns
    assert "evidence_class" in columns
    assert "l1_retrieval_scope" in columns
    assert "idx_fact_events_l1_retrieval_scope" in indexes
    assert row == (
        int(EvidenceStatus.UNKNOWN),
        int(EvidenceClass.UNKNOWN),
        int(L1RetrievalScope.NONE),
        1,
    )


async def _store_polluted_oolong_events(store) -> None:
    for index in range(12):
        assistant_event = normalize_runtime_event(
            Event(
                type=EventTypes.AI_RESPONSE,
                data={
                    "user_id": "user-1",
                    "session_id": "session-1",
                    "content": "You like oolong tea.",
                    "author_type": "assistant",
                    "content_type": "text",
                },
                source="assistant",
                level=EventLevel.INFO,
                correlation_id=f"corr-assistant-{index}",
                event_id=f"evt-assistant-{index}",
            )
        )
        await store.store(assistant_event)

    user_event = normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "user-1",
                "session_id": "session-1",
                "content": "I like oolong tea.",
                "author_type": "user",
                "content_type": "text",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="corr-user-scope",
            event_id="evt-user-scope",
        )
    )
    await store.store(user_event)


def _external_activity_event(
    *,
    event_id: str,
    source: str,
    content: str,
    timestamp: float,
    created_at: float,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        correlation_id=event_id,
        timestamp=timestamp,
        created_at=created_at,
        event_type="SensorActivity",
        source=source,
        source_item_id=event_id,
        memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
        retention_class=RetentionClass.COMPRESSIBLE,
        session_id=None,
        turn_id=None,
        user_id="local_user",
        task_id=None,
        content=content,
        author_type="external",
        content_type="text",
        importance_score=0.5,
        level=int(EventLevel.INFO),
    )


@pytest.mark.asyncio
async def test_l1_query_events_can_order_by_created_at_for_recent_imports(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        await store.store(
            _external_activity_event(
                event_id="old-written-recent-happened",
                source="chrome_history",
                content="Recently visited news page",
                timestamp=3000.0,
                created_at=1000.0,
            )
        )
        await store.store(
            _external_activity_event(
                event_id="new-written-old-happened",
                source="chrome_history",
                content="Imported older page from history",
                timestamp=100.0,
                created_at=2000.0,
            )
        )

        events = await store.query_events(
            source_filters=["chrome_history"],
            limit=2,
            order_by="created_at_desc",
        )

        assert [event["event_id"] for event in events] == [
            "new-written-old-happened",
            "old-written-recent-happened",
        ]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_get_event_timestamps_returns_original_occurrence_times(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        await store.store(
            _external_activity_event(
                event_id="older-occurrence",
                source="chrome_history",
                content="Older imported event",
                timestamp=100.0,
                created_at=2_000.0,
            )
        )
        await store.store(
            _external_activity_event(
                event_id="newer-occurrence",
                source="chrome_history",
                content="Newer imported event",
                timestamp=300.0,
                created_at=1_000.0,
            )
        )

        timestamps = await store.get_event_timestamps(
            ["newer-occurrence", "missing", "older-occurrence"]
        )

        assert timestamps == {
            "newer-occurrence": 300.0,
            "older-occurrence": 100.0,
        }
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_persists_evidence_annotation(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        user_event = normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "user-1",
                    "session_id": "session-1",
                    "content": "I like oolong tea.",
                    "author_type": "user",
                    "content_type": "text",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id="corr-evidence-user",
                event_id="evt-evidence-user",
            )
        )
        assistant_event = normalize_runtime_event(
            Event(
                type=EventTypes.AI_RESPONSE,
                data={
                    "user_id": "user-1",
                    "session_id": "session-1",
                    "content": "You like oolong tea.",
                    "author_type": "assistant",
                    "content_type": "text",
                },
                source="assistant",
                level=EventLevel.INFO,
                correlation_id="corr-evidence-assistant",
                event_id="evt-evidence-assistant",
            )
        )

        await store.store(user_event)
        await store.store(assistant_event)

        fetched_user = await store.get_event(user_event.event_id)
        fetched_assistant = await store.get_event(assistant_event.event_id)

        assert fetched_user is not None
        assert fetched_user["evidence_status"] == "classified"
        assert fetched_user["evidence_class"] == "user_self_report"
        assert fetched_user["l1_retrieval_scope"] == "fact_authoritative"
        assert fetched_user["evidence_rule_version"] == EVIDENCE_RULE_VERSION

        assert fetched_assistant is not None
        assert fetched_assistant["evidence_status"] == "classified"
        assert fetched_assistant["evidence_class"] == "assistant_freeform"
        assert fetched_assistant["l1_retrieval_scope"] == "conversation_only"
        assert fetched_assistant["evidence_rule_version"] == EVIDENCE_RULE_VERSION
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_keeps_raw_event_when_evidence_classification_fails(
    tmp_path,
    monkeypatch,
):
    from magi.memory.l1 import writes
    from magi.memory.l1.event_store import L1EventStore

    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)

    def _raise_classifier(_event):
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(writes, "classify_event_evidence", _raise_classifier)
    await store.initialize()
    try:
        event = normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "user-1",
                    "session_id": "session-1",
                    "content": "I like jasmine tea.",
                    "author_type": "user",
                    "content_type": "text",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id="corr-evidence-error",
                event_id="evt-evidence-error",
            )
        )

        await store.store(event)
        fetched = await store.get_event(event.event_id)

        assert fetched is not None
        assert fetched["content"] == "I like jasmine tea."
        assert fetched["evidence_status"] == "classification_error"
        assert fetched["evidence_class"] == "unknown"
        assert fetched["l1_retrieval_scope"] == "none"
        assert fetched["evidence_rule_version"] == EVIDENCE_RULE_VERSION
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_bm25_filters_evidence_scope_before_limit(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        await _store_polluted_oolong_events(store)

        unscoped_hits = await store.bm25_search("oolong tea", limit=5, user_id="user-1")
        scoped_hits = await store.bm25_search(
            "oolong tea",
            limit=5,
            user_id="user-1",
            l1_retrieval_scopes=["fact_authoritative"],
        )

        assert len(unscoped_hits) == 5
        assert [event_id for event_id, _score in scoped_hits] == ["evt-user-scope"]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_handler_scopes_polluted_fact_recall_before_rrf_topk(tmp_path):
    from magi.memory.hybrid_retrieval.l1_handler import L1Handler
    from magi.memory.hybrid_retrieval.models import L1Conditions
    from magi.memory.l1.event_store import L1EventStore

    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        await _store_polluted_oolong_events(store)
        handler = L1Handler(store).with_l1_retrieval_scopes(["fact_authoritative"])

        results = await handler.execute(
            L1Conditions(content_query="oolong tea", limit=5),
            user_id="user-1",
        )

        assert [event["event_id"] for event in results] == ["evt-user-scope"]
        assert results[0]["l1_retrieval_scope"] == "fact_authoritative"
    finally:
        await store.shutdown()


class _BatchTrackingEmbeddingService:
    def __init__(self, *, model_name: str = "test-embedding", dimension: int = 4) -> None:
        self.single_calls: list[str] = []
        self.batch_calls: list[list[str]] = []
        self.model_name = model_name
        self.provider_name = "fake"
        self.embedding_dimension = dimension

    async def embed_text(self, text: str):
        self.single_calls.append(text)
        return self._make_result(text)

    async def embed_texts(self, texts: list[str]):
        self.batch_calls.append(list(texts))
        return [self._make_result(text) for text in texts]

    def _make_result(self, text: str):
        from magi.memory.embedding.embedding_service import EmbeddingResult

        lowered = text.lower()
        vector = [0.0] * self.embedding_dimension
        if "stress" in lowered:
            vector[0] = 1.0
        if "calm" in lowered:
            vector[1] = 1.0
        if "career" in lowered:
            vector[2] = 1.0
        if not any(vector):
            vector[min(3, self.embedding_dimension - 1)] = 1.0
        return EmbeddingResult(
            model_name=self.model_name, dimension=self.embedding_dimension, vector=vector
        )

    def get_active_profile(self, *, text_builder_version: str):
        from magi.memory.embedding.embedding_service import EmbeddingProfile

        return EmbeddingProfile.build(
            provider_name=self.provider_name,
            model_name=self.model_name,
            dimension=self.embedding_dimension,
            text_builder_version=text_builder_version,
        )

    def profile_from_result(self, result, *, text_builder_version: str):
        from magi.memory.embedding.embedding_service import EmbeddingProfile

        return EmbeddingProfile.build(
            provider_name=self.provider_name,
            model_name=result.model_name,
            dimension=result.dimension,
            text_builder_version=text_builder_version,
        )


class _RecordingVectorIndex:
    def __init__(self) -> None:
        self.upsert_many_calls: list[list[str]] = []
        self.upsert_calls: list[str] = []

    async def upsert_many(self, items: list[dict[str, object]]) -> None:
        self.upsert_many_calls.append([str(item["entity_id"]) for item in items])

    async def upsert(self, *, entity_id: str, embedding, metadata=None) -> None:
        _ = (embedding, metadata)
        self.upsert_calls.append(entity_id)

    async def close(self) -> None:
        return None


class _ChunkRecordingVectorIndex(_RecordingVectorIndex):
    def __init__(self) -> None:
        super().__init__()
        self.metadata_by_id: dict[str, object] = {}

    async def upsert_many(self, items: list[dict[str, object]]) -> None:
        await super().upsert_many(items)
        for item in items:
            self.metadata_by_id[str(item["entity_id"])] = item.get("metadata")


class _ShortBatchEmbeddingService(_BatchTrackingEmbeddingService):
    def __init__(self, *, returned_count: int) -> None:
        super().__init__()
        self.returned_count = returned_count

    async def embed_texts(self, texts: list[str]):
        self.batch_calls.append(list(texts))
        return [self._make_result(text) for text in texts[: self.returned_count]]


class _BlockingBatchEmbeddingService(_BatchTrackingEmbeddingService):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.active_calls = 0
        self.max_active_calls = 0

    async def embed_texts(self, texts: list[str]):
        self.batch_calls.append(list(texts))
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        self.started.set()
        await self.release.wait()
        self.active_calls -= 1
        return [self._make_result(text) for text in texts]


@pytest.mark.asyncio
async def test_l1_event_store_persists_and_filters_memory_events(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path))
    await store.initialize()
    try:
        event = Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "user-1",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "content": "Remember this",
                "author_type": "user",
                "content_type": "text",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="corr-1",
            event_id="evt-1",
        )
        memory_event = normalize_runtime_event(event)

        stored_event_id = await store.store(memory_event)
        fetched = await store.get_event("evt-1")
        queried = await store.query_events(
            session_id="session-1", memory_domain="user_authored", limit=10
        )

        assert stored_event_id == "evt-1"
        assert fetched is not None
        assert fetched["event_id"] == "evt-1"
        assert fetched["content"] == "Remember this"
        assert fetched["author_type"] == "user"
        assert fetched["content_type"] == "text"
        assert fetched["turn_id"] == "turn-1"
        assert "raw_content" not in fetched
        assert "structured_payload" not in fetched
        assert "metadata" not in fetched
        assert len(queried) == 1
        assert queried[0]["event_id"] == "evt-1"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_query_events_resolves_active_profile_once(tmp_path, monkeypatch):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        for index in range(3):
            event = Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": f"user-{index}",
                    "session_id": "session-1",
                    "turn_id": f"turn-{index}",
                    "content": f"Remember this {index}",
                    "author_type": "user",
                    "content_type": "text",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id=f"corr-{index}",
                event_id=f"evt-{index}",
            )
            await store.store(normalize_runtime_event(event))

        call_count = 0
        original_resolver = store._resolve_active_embedding_profile_id

        def _counted_resolver():
            nonlocal call_count
            call_count += 1
            return original_resolver()

        monkeypatch.setattr(store, "_resolve_active_embedding_profile_id", _counted_resolver)

        queried = await store.query_events(session_id="session-1", limit=10)

        assert len(queried) == 3
        assert call_count == 1
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_assigns_session_local_sequence_numbers(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        for index in range(3):
            event = Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "user-1",
                    "session_id": "session-seq",
                    "turn_id": f"turn_{index}",
                    "content": f"Remember item {index}",
                    "author_type": "user",
                    "content_type": "text",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id=f"corr-session-seq-{index}",
                event_id=f"evt-session-seq-{index}",
            )
            await store.store(normalize_runtime_event(event))

        queried = await store.query_events(
            session_id="session-seq",
            limit=10,
            order_by="timestamp_asc",
        )

        assert [event["session_seq"] for event in queried] == [0, 1, 2]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_queries_session_sequence_window(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        for index in range(5):
            event = Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "user-1",
                    "session_id": "session-window",
                    "turn_id": f"turn_{index}",
                    "content": f"Window item {index}",
                    "author_type": "user",
                    "content_type": "text",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id=f"corr-session-window-{index}",
                event_id=f"evt-session-window-{index}",
            )
            await store.store(normalize_runtime_event(event))

        window = await store.query_session_event_window(
            session_id="session-window",
            center_session_seq=2,
            window=1,
        )

        assert [event["event_id"] for event in window] == [
            "evt-session-window-1",
            "evt-session-window-2",
            "evt-session-window-3",
        ]

        other_user_event = Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "user-2",
                "session_id": "session-window",
                "turn_id": "other-user-turn",
                "content": "Other user window item",
                "author_type": "user",
                "content_type": "text",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="corr-session-window-other-user",
            event_id="evt-session-window-other-user",
        )
        await store.store(normalize_runtime_event(other_user_event))

        scoped_window = await store.query_session_event_window(
            session_id="session-window",
            center_session_seq=2,
            window=2,
            user_id="user-1",
        )

        assert [event["event_id"] for event in scoped_window] == [
            "evt-session-window-0",
            "evt-session-window-1",
            "evt-session-window-2",
            "evt-session-window-3",
            "evt-session-window-4",
        ]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_restores_final_memory_event_shape(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        event = Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "local_user",
                "session_id": "session-1",
                "turn_id": "turn-identity-1",
                "content": "Remember me",
                "author_type": "user",
                "content_type": "text",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="corr-identity-1",
            event_id="evt-identity-1",
        )
        memory_event = normalize_runtime_event(event)

        await store.store(memory_event)
        fetched = await store.get_event("evt-identity-1")
        restored = await store.get_memory_event("evt-identity-1")

        assert fetched is not None
        assert fetched["user_id"] == "local_user"
        assert fetched["turn_id"] == "turn-identity-1"
        assert restored is not None
        assert restored.user_id == "local_user"
        assert restored.content == "Remember me"
        assert restored.author_type == "user"
        assert restored.content_type == "text"
        assert restored.turn_id == "turn-identity-1"
        assert not hasattr(restored, "runtime_user_id")
        assert not hasattr(restored, "memory_owner_id")
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_persists_metadata_json(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        now = time.time()
        event = MemoryEvent(
            event_id="evt-app-usage-1",
            correlation_id="corr-app-usage-1",
            timestamp=1711504800.0,
            created_at=now,
            event_type="APP_USAGE_HOURLY",
            source="active_app_usage",
            source_item_id="app_usage:2026-03-27T10:00:00+08:00:com.apple.Safari",
            memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=False,
            tom_depth=TomDepth.NONE,
            retention_class=RetentionClass.COMPRESSIBLE,
            session_id=None,
            turn_id=None,
            user_id=None,
            task_id=None,
            content="10:00-11:00 Safari used for 38m.",
            author_type="external",
            content_type="observation",
            importance_score=0.3,
            level=1,
            idempotency_key="app_usage:2026-03-27T10:00:00+08:00:com.apple.Safari",
            metadata_json={
                "bucket_start": "2026-03-27T10:00:00+08:00",
                "bucket_end": "2026-03-27T11:00:00+08:00",
                "bundle_id": "com.apple.Safari",
                "app_name": "Safari",
                "duration_seconds": 2280,
            },
        )

        await store.store(event)

        fetched = await store.get_event(event.event_id)
        restored = await store.get_memory_event(event.event_id)

        assert fetched is not None
        assert isinstance(fetched["id"], int)
        assert fetched["id"] > 0
        assert fetched["event_type"] == "APP_USAGE_HOURLY"
        assert fetched["idempotency_key"] == "app_usage:2026-03-27T10:00:00+08:00:com.apple.Safari"
        # _evidence is merged in at write time; original keys must be preserved and no
        # unexpected extra keys should appear.
        assert fetched["metadata_json"] == {
            "bucket_start": "2026-03-27T10:00:00+08:00",
            "bucket_end": "2026-03-27T11:00:00+08:00",
            "bundle_id": "com.apple.Safari",
            "app_name": "Safari",
            "duration_seconds": 2280,
            "_evidence": fetched["metadata_json"]["_evidence"],
        }
        assert restored is not None
        assert restored.metadata_json == fetched["metadata_json"]
    finally:
        await store.shutdown()


def test_l1_event_store_search_text_includes_projection_retrieval_terms():
    from magi.memory.l1.event_store import L1EventStore

    store = L1EventStore(vector_enabled=False)
    event = MemoryEvent(
        event_id="evt-search-1",
        correlation_id="corr-search-1",
        timestamp=1711504800.0,
        created_at=1711504801.0,
        event_type="SENSOR_EVENT",
        source="netease_music",
        source_item_id="track-1",
        memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.COMPRESSIBLE,
        session_id=None,
        turn_id=None,
        user_id="local_user",
        task_id=None,
        content="网易云音乐听了 YOASOBI 的《夜に駆ける》",
        author_type="external",
        content_type="observation",
        importance_score=0.5,
        level=1,
        metadata_json={
            "projection": {
                "retrieval_terms": ["j-pop", "electropop", "J-POP"],
            }
        },
    )

    assert (
        store.get_search_text(event)
        == "网易云音乐听了 YOASOBI 的《夜に駆ける》 j-pop electropop external observation"
    )


@pytest.mark.asyncio
async def test_l1_event_store_backfills_owner_for_legacy_external_events(tmp_path):
    """Removed: _backfill_external_owner_user_ids was deleted in pre-release cleanup."""
    return


@pytest.mark.asyncio
async def test_l1_event_store_deduplicates_by_source_type_and_idempotency_key(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        now = time.time()
        first = MemoryEvent(
            event_id="evt-first",
            correlation_id="corr-first",
            timestamp=now,
            created_at=now,
            event_type="SENSOR_EVENT",
            source="chrome_history",
            source_item_id="181979-181982",
            memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=True,
            tom_depth=TomDepth.NONE,
            retention_class=RetentionClass.COMPRESSIBLE,
            session_id=None,
            turn_id=None,
            user_id=None,
            task_id=None,
            content="Burst one",
            author_type="external",
            content_type="observation",
            importance_score=0.5,
            level=1,
            idempotency_key="default:181979-181982",
        )
        second = MemoryEvent(
            event_id="evt-second",
            correlation_id="corr-second",
            timestamp=now + 1,
            created_at=now + 1,
            event_type="SENSOR_EVENT",
            source="chrome_history",
            source_item_id="181979-181982",
            memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=True,
            tom_depth=TomDepth.NONE,
            retention_class=RetentionClass.COMPRESSIBLE,
            session_id=None,
            turn_id=None,
            user_id=None,
            task_id=None,
            content="Burst one duplicate",
            author_type="external",
            content_type="observation",
            importance_score=0.5,
            level=1,
            idempotency_key="default:181979-181982",
        )

        stored_first = await store.store(first)
        stored_second = await store.store(second)
        fetched = await store.get_event("evt-first")

        conn = sqlite3.connect(str(db_path))
        try:
            event_count = conn.execute("SELECT COUNT(*) FROM fact_events").fetchone()
        finally:
            conn.close()

        assert stored_first == "evt-first"
        assert stored_second == "evt-first"
        assert fetched is not None
        assert fetched["content"] == "Burst one"
        assert event_count == (1,)
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_timeline_view_falls_back_to_idempotency_key(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        now = time.time()
        event = MemoryEvent(
            event_id="evt-app-usage-view",
            correlation_id="corr-app-usage-view",
            timestamp=1711504800.0,
            created_at=now,
            event_type="APP_USAGE_HOURLY",
            source="active_app_usage",
            source_item_id=None,
            memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=False,
            tom_depth=TomDepth.NONE,
            retention_class=RetentionClass.COMPRESSIBLE,
            session_id=None,
            turn_id=None,
            user_id=None,
            task_id=None,
            content="10:00-11:00 Safari used for 38m.",
            author_type="external",
            content_type="observation",
            importance_score=0.3,
            level=1,
            idempotency_key="app_usage:2026-03-27T10:00:00+08:00:com.apple.Safari",
            metadata_json={
                "activity_snapshot": {
                    "source_type": "active_app_usage",
                    "title": "Safari",
                    "summary": "10:00-11:00 Safari used for 38m.",
                }
            },
        )

        await store.store(event)

        fetched = await store.get_timeline_event(event.event_id)
        listed = await store.list_timeline_events(limit=10, source_type="active_app_usage")

        assert fetched is not None
        assert fetched["source_item_id"] == "app_usage:2026-03-27T10:00:00+08:00:com.apple.Safari"
        assert listed[0]["source_item_id"] == "app_usage:2026-03-27T10:00:00+08:00:com.apple.Safari"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_queries_by_content_source_and_time_range(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        base_time = 1710000000.0
        events = [
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "user-1",
                    "session_id": "session-1",
                    "content": "West Lake walk notes",
                    "author_type": "user",
                    "content_type": "text",
                },
                source="chat_projector",
                level=EventLevel.INFO,
                correlation_id="corr-query-1",
                timestamp=base_time,
                event_id="evt-query-1",
            ),
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "user-1",
                    "session_id": "session-1",
                    "content": "Longjing tea hills",
                    "author_type": "user",
                    "content_type": "text",
                },
                source="timeline_importer",
                level=EventLevel.INFO,
                correlation_id="corr-query-2",
                timestamp=base_time + 60,
                event_id="evt-query-2",
            ),
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "user-1",
                    "session_id": "session-1",
                    "content": "West Lake sunset review",
                    "author_type": "user",
                    "content_type": "text",
                },
                source="chat_projector",
                level=EventLevel.INFO,
                correlation_id="corr-query-3",
                timestamp=base_time + 3600,
                event_id="evt-query-3",
            ),
        ]

        for index, event in enumerate(events, start=1):
            await store.store(normalize_runtime_event(event))

        queried = await store.query_events(
            query="west lake",
            source_filters=["chat_projector"],
            start_time=base_time - 1,
            end_time=base_time + 120,
            limit=10,
        )

        assert [event["event_id"] for event in queried] == ["evt-query-1"]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_store_initializes_without_runtime_observations_table(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path))
    await store.initialize()
    try:
        conn = sqlite3.connect(str(db_path))
        table_names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        conn.close()

        assert "fact_events" in table_names
        assert "runtime_observations" not in table_names

        conn = sqlite3.connect(str(db_path))
        try:
            journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        finally:
            conn.close()

        assert journal_mode == "wal"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_query_events_filters_by_source_item_and_idempotency_key(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        first = MemoryEvent(
            event_id="evt-source-1",
            correlation_id="corr-source-1",
            timestamp=100.0,
            created_at=101.0,
            event_type="SENSOR_EVENT",
            source="chrome_history",
            source_item_id="chrome:181979-181982",
            idempotency_key="default:181979-181982",
            memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=True,
            tom_depth=TomDepth.NONE,
            retention_class=RetentionClass.COMPRESSIBLE,
            session_id=None,
            turn_id=None,
            user_id="local_user",
            task_id=None,
            content="first",
            author_type="external",
            content_type="text",
            importance_score=0.5,
            level=20,
        )
        second = MemoryEvent(
            event_id="evt-source-2",
            correlation_id="corr-source-2",
            timestamp=200.0,
            created_at=201.0,
            event_type="SENSOR_EVENT",
            source="chrome_history",
            source_item_id="chrome:190000-190001",
            idempotency_key="default:190000-190001",
            memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=True,
            tom_depth=TomDepth.NONE,
            retention_class=RetentionClass.COMPRESSIBLE,
            session_id=None,
            turn_id=None,
            user_id="local_user",
            task_id=None,
            content="second",
            author_type="external",
            content_type="text",
            importance_score=0.5,
            level=20,
        )

        await store.store(first)
        await store.store(second)

        by_source_item = await store.query_events(source_item_id="chrome:181979-181982", limit=10)
        by_idempotency = await store.query_events(idempotency_key="default:190000-190001", limit=10)

        assert [event["event_id"] for event in by_source_item] == ["evt-source-1"]
        assert [event["event_id"] for event in by_idempotency] == ["evt-source-2"]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_persists_action_events_in_fact_events(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path))
    await store.initialize()
    try:
        event = Event(
            type=EventTypes.ACTION_EXECUTED,
            data={
                "user_id": "user-1",
                "session_id": "session-1",
                "content": "bash succeeded",
                "author_type": "tool",
                "content_type": "tool_result",
                "action_type": "bash",
                "success": True,
            },
            source="runtime",
            level=EventLevel.INFO,
            correlation_id="corr-2",
            event_id="evt-runtime-1",
        )
        memory_event = normalize_runtime_event(event)
        await store.store(memory_event)

        fetched_fact = await store.get_event("evt-runtime-1")

        assert fetched_fact is not None
        assert fetched_fact["event_id"] == "evt-runtime-1"
        assert fetched_fact["event_type"] == EventTypes.ACTION_EXECUTED
        assert fetched_fact["content"] == "bash succeeded"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_projects_user_message_into_chat_session_row(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        event = Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "user-1",
                "session_id": "session-1",
                "content": "First message preview",
                "author_type": "user",
                "content_type": "text",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="corr-chat-session-user",
            event_id="evt-chat-session-user",
        )

        await store.store(normalize_runtime_event(event))

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            f"""
            SELECT title, title_overridden, last_message_preview, last_user_message_preview,
                   message_count, last_message_at, last_user_message_at
            FROM {CHAT_SESSIONS_TABLE}
            WHERE session_id = ?
            """,
            ("session-1",),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == ""
        assert row[1] == 0
        assert row[2] == "First message preview"
        assert row[3] == "First message preview"
        assert row[4] == 1
        assert row[5] is not None
        assert row[6] is not None
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_projects_ai_response_into_existing_chat_session_row(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        await store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "user-1",
                        "session_id": "session-1",
                        "content": "User preview",
                        "author_type": "user",
                        "content_type": "text",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id="corr-chat-session-seed",
                    event_id="evt-chat-session-seed",
                ),
            )
        )
        await store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.AI_RESPONSE,
                    data={
                        "user_id": "user-1",
                        "session_id": "session-1",
                        "content": "Assistant preview",
                        "author_type": "assistant",
                        "content_type": "text",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id="corr-chat-session-ai",
                    event_id="evt-chat-session-ai",
                ),
            )
        )

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            f"""
            SELECT last_message_preview, last_user_message_preview, message_count
            FROM {CHAT_SESSIONS_TABLE}
            WHERE session_id = ?
            """,
            ("session-1",),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "Assistant preview"
        assert row[1] == "User preview"
        assert row[2] == 2
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_store_is_idempotent_for_existing_event_ids(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        memory_event = normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "user-1",
                    "session_id": "session-1",
                    "content": "Repeated message",
                    "author_type": "user",
                    "content_type": "text",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id="corr-idempotent",
                event_id="evt-idempotent",
            ),
        )

        await store.store(memory_event)
        await store.store(memory_event)

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            f"""
            SELECT message_count, last_message_preview
            FROM {CHAT_SESSIONS_TABLE}
            WHERE session_id = ?
            """,
            ("session-1",),
        ).fetchone()
        event_count = conn.execute(
            "SELECT COUNT(*) FROM fact_events WHERE event_id = ?", ("evt-idempotent",)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 1
        assert row[1] == "Repeated message"
        assert event_count == (1,)
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_search_events_falls_back_when_semantic_hits_filter_to_empty(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        await store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "user-1",
                        "session_id": "session-1",
                        "content": "I love sushi in tokyo",
                        "author_type": "user",
                        "content_type": "text",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id="corr-search-fallback",
                    event_id="evt-search-fallback",
                ),
            )
        )

        async def fake_semantic_hits(*, query: str, limit: int):
            _ = (query, limit)
            return [object()]

        async def fake_fetch_ranked_events(**kwargs):
            _ = kwargs
            return []

        store._semantic_search_event_hits = fake_semantic_hits  # type: ignore[method-assign]
        store._fetch_ranked_events = fake_fetch_ranked_events  # type: ignore[method-assign]

        results = await store.search_events(
            query="sushi tokyo",
            session_id="session-1",
            user_id="user-1",
            limit=5,
        )

        assert [item["event_id"] for item in results] == ["evt-search-fallback"]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_decodes_integer_classification_fields(tmp_path):
    import sqlite3

    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path))
    await store.initialize()
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            INSERT INTO fact_events (
                event_id, timestamp, created_at,
                event_type, source, source_item_id, memory_domain,
                cognition_eligible, retention_class, session_id, turn_id, user_id,
                content, author_type, content_type, importance_score,
                media_path, deleted_at, evidence_status, evidence_class, evidence_rule_version,
                l1_retrieval_scope
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "evt-decoded",
                1.0,
                1.0,
                "UserMessage",
                "chat",
                None,
                int(MemoryDomain.USER_AUTHORED),
                1,
                int(RetentionClass.PERMANENT),
                "session-1",
                "turn-1",
                "user-1",
                "hello",
                author_type_code("user"),
                content_type_code("text"),
                0.8,
                None,
                None,
                int(EvidenceStatus.CLASSIFIED),
                int(EvidenceClass.USER_SELF_REPORT),
                1,
                int(L1RetrievalScope.FACT_AUTHORITATIVE),
            ),
        )
        conn.commit()
        conn.close()

        fetched = await store.get_event("evt-decoded")

        assert fetched is not None
        assert fetched["memory_domain"] == "user_authored"
        assert fetched["ingest_target"] == "l1_only"
        assert fetched["tom_depth"] == "none"
        assert fetched["retention_class"] == "permanent"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_async_embeddings_flush_full_batches_via_batch_api(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    embedding_service = _BatchTrackingEmbeddingService()
    store = L1EventStore(
        db_path=str(tmp_path / "l1_events.db"),
        embedding_service=embedding_service,
        async_embeddings=True,
        embedding_worker_count=1,
    )
    store._embedding_batch_wait_seconds = 5.0
    await store.initialize()

    try:
        for idx in range(5):
            await store.store(
                normalize_runtime_event(
                    Event(
                        type=EventTypes.USER_MESSAGE,
                        data={
                            "user_id": "u1",
                            "session_id": "s1",
                            "content": f"career note {idx}",
                            "author_type": "user",
                            "content_type": "text",
                        },
                        source="chat",
                        level=EventLevel.INFO,
                        correlation_id=f"corr-batch-{idx}",
                        event_id=f"evt-batch-{idx}",
                    ),
                )
            )

        assert store._embedding_queue is not None
        await asyncio.wait_for(store._embedding_queue.join(), timeout=2.0)
    finally:
        await store.shutdown()

    assert embedding_service.single_calls == []
    assert len(embedding_service.batch_calls) == 1
    assert len(embedding_service.batch_calls[0]) == 5


@pytest.mark.asyncio
async def test_l1_async_embeddings_flush_partial_batches_after_timeout(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    embedding_service = _BatchTrackingEmbeddingService()
    store = L1EventStore(
        db_path=str(tmp_path / "l1_events.db"),
        embedding_service=embedding_service,
        async_embeddings=True,
        embedding_worker_count=1,
    )
    store._embedding_batch_wait_seconds = 0.05
    await store.initialize()

    started_at = time.monotonic()
    try:
        for idx in range(2):
            await store.store(
                normalize_runtime_event(
                    Event(
                        type=EventTypes.USER_MESSAGE,
                        data={
                            "user_id": "u1",
                            "session_id": "s1",
                            "content": f"stress note {idx}",
                            "author_type": "user",
                            "content_type": "text",
                        },
                        source="chat",
                        level=EventLevel.INFO,
                        correlation_id=f"corr-timeout-{idx}",
                        event_id=f"evt-timeout-{idx}",
                    ),
                )
            )

        assert store._embedding_queue is not None
        await asyncio.wait_for(store._embedding_queue.join(), timeout=1.0)
    finally:
        await store.shutdown()

    assert time.monotonic() - started_at >= 0.04
    assert embedding_service.single_calls == []
    assert embedding_service.batch_calls == [
        [
            "stress note 0",
            "stress note 1",
        ]
    ]


@pytest.mark.asyncio
async def test_l1_embedding_queue_waits_when_full(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    embedding_service = _BlockingBatchEmbeddingService()
    store = L1EventStore(
        db_path=str(tmp_path / "l1_events.db"),
        embedding_service=embedding_service,
        async_embeddings=True,
        embedding_worker_count=1,
    )
    store._embedding_batch_size = 1
    store._embedding_batch_wait_seconds = 5.0
    await store.initialize()

    try:
        assert store._embedding_queue is not None
        assert store._embedding_queue.maxsize > 0

        await store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "career note 1",
                        "author_type": "user",
                        "content_type": "text",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id="corr-queue-1",
                    event_id="evt-queue-1",
                ),
            )
        )

        await asyncio.wait_for(embedding_service.started.wait(), timeout=1.0)

        second_task = asyncio.create_task(
            store.store(
                normalize_runtime_event(
                    Event(
                        type=EventTypes.USER_MESSAGE,
                        data={
                            "user_id": "u1",
                            "session_id": "s1",
                            "content": "career note 2",
                            "author_type": "user",
                            "content_type": "text",
                        },
                        source="chat",
                        level=EventLevel.INFO,
                        correlation_id="corr-queue-2",
                        event_id="evt-queue-2",
                    ),
                )
            )
        )
        await asyncio.wait_for(second_task, timeout=1.0)

        third_task = asyncio.create_task(
            store.store(
                normalize_runtime_event(
                    Event(
                        type=EventTypes.USER_MESSAGE,
                        data={
                            "user_id": "u1",
                            "session_id": "s1",
                            "content": "career note 3",
                            "author_type": "user",
                            "content_type": "text",
                        },
                        source="chat",
                        level=EventLevel.INFO,
                        correlation_id="corr-queue-3",
                        event_id="evt-queue-3",
                    ),
                )
            )
        )
        await asyncio.sleep(0)

        assert not third_task.done()

        embedding_service.release.set()
        await asyncio.wait_for(third_task, timeout=1.0)
    finally:
        embedding_service.release.set()
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_async_embeddings_can_use_multiple_workers(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    embedding_service = _BlockingBatchEmbeddingService()
    store = L1EventStore(
        db_path=str(tmp_path / "l1_events.db"),
        embedding_service=embedding_service,
        async_embeddings=True,
        embedding_worker_count=2,
    )
    store._embedding_batch_size = 1
    store._embedding_batch_wait_seconds = 5.0
    await store.initialize()

    try:
        await store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "career note a",
                        "author_type": "user",
                        "content_type": "text",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id="corr-worker-a",
                    event_id="evt-worker-a",
                ),
            )
        )
        await store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "career note b",
                        "author_type": "user",
                        "content_type": "text",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id="corr-worker-b",
                    event_id="evt-worker-b",
                ),
            )
        )

        async def wait_for_parallel_workers() -> None:
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                if embedding_service.max_active_calls >= 2:
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("expected at least two embedding workers to run concurrently")

        await wait_for_parallel_workers()
    finally:
        embedding_service.release.set()
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_batch_embedding_flush_uses_vector_index_upsert_many(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    embedding_service = _BatchTrackingEmbeddingService()
    store = L1EventStore(
        db_path=str(tmp_path / "l1_events.db"),
        embedding_service=embedding_service,
        async_embeddings=False,
    )
    await store.initialize()
    recording_index = _RecordingVectorIndex()
    store._vector_index = recording_index  # type: ignore[assignment]

    events = [
        normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": f"career note {idx}",
                    "author_type": "user",
                    "content_type": "text",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id=f"corr-many-{idx}",
                event_id=f"evt-many-{idx}",
            ),
        )
        for idx in range(3)
    ]

    store._default_vector_enabled = False
    for event in events:
        await store.store(event)
    store._default_vector_enabled = True
    await store._maybe_upsert_event_embeddings(events)

    assert recording_index.upsert_many_calls == [
        [
            "evt-many-0::chunk-0",
            "evt-many-1::chunk-0",
            "evt-many-2::chunk-0",
        ]
    ]
    assert recording_index.upsert_calls == []
    await store.shutdown()


@pytest.mark.asyncio
async def test_l1_batch_embedding_flush_indexes_chunks_and_updates_chunk_count(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    embedding_service = _BatchTrackingEmbeddingService()
    store = L1EventStore(
        db_path=str(tmp_path / "l1_events.db"),
        embedding_service=embedding_service,
        async_embeddings=False,
    )
    await store.initialize()
    recording_index = _ChunkRecordingVectorIndex()
    store._vector_index = recording_index  # type: ignore[assignment]
    store._schedule_event_embedding = lambda event: asyncio.sleep(0)  # type: ignore[method-assign]

    try:
        long_content = (
            "I worked on the career note section one project for several weeks. " * 5
            + "The career note section two involved complex database migrations. " * 5
            + "Finally the career note section three required integration testing. " * 5
        )
        event = normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": long_content,
                    "author_type": "user",
                    "content_type": "text",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id="corr-chunked",
                event_id="evt-chunked",
            ),
        )
        await store.store(event)

        await store._maybe_upsert_event_embeddings([event])
        fetched = await store.get_event("evt-chunked")
    finally:
        await store.shutdown()

    assert fetched is not None
    assert fetched["embedding_status"] == "ready"
    assert fetched["embedding_chunk_count"] > 1
    assert len(recording_index.upsert_many_calls) == 1
    assert all(
        chunk_id.startswith("evt-chunked::chunk-")
        for chunk_id in recording_index.upsert_many_calls[0]
    )


@pytest.mark.asyncio
async def test_l1_fetch_ranked_events_folds_chunk_hits_to_parent_event(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    embedding_service = _BatchTrackingEmbeddingService()
    store = L1EventStore(
        db_path=str(tmp_path / "l1_events.db"),
        embedding_service=embedding_service,
        async_embeddings=False,
    )
    await store.initialize()
    try:
        long_content = (
            "I planned my career goals for next quarter and set clear milestones. " * 5
            + "After work I practiced calm breathing exercises for stress relief. " * 5
        )
        event = normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": long_content,
                    "author_type": "user",
                    "content_type": "text",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id="corr-ranked",
                event_id="evt-ranked",
            ),
        )
        await store.store(event)
        await store._maybe_upsert_event_embeddings([event])

        hits = [
            VectorSearchHit(entity_id="evt-ranked::chunk-1", distance=0.04),
            VectorSearchHit(entity_id="evt-ranked::chunk-0", distance=0.09),
        ]
        ranked = await store._fetch_ranked_events(
            hits=hits,
            session_id="s1",
            user_id="u1",
            event_type=None,
            source_filters=None,
            domain_filters=None,
            limit=5,
            l1_retrieval_scopes=None,
        )
    finally:
        await store.shutdown()

    assert [item["event_id"] for item in ranked] == ["evt-ranked"]
    assert ranked[0]["distance"] == 0.04
    assert [chunk["chunk_id"] for chunk in ranked[0]["matched_chunks"]] == [
        "evt-ranked::chunk-1",
        "evt-ranked::chunk-0",
    ]


@pytest.mark.asyncio
async def test_l1_event_store_marks_embedding_ready_with_profile_row(tmp_path):
    from magi.memory.l1.event_store import EMBEDDING_PROFILES_TABLE, L1EventStore

    embedding_service = _BatchTrackingEmbeddingService(model_name="embed-a", dimension=8)
    store = L1EventStore(
        db_path=str(tmp_path / "l1_events.db"),
        embedding_service=embedding_service,
        async_embeddings=False,
    )
    await store.initialize()
    try:
        await store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "career note",
                        "author_type": "user",
                        "content_type": "text",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id="corr-ready",
                    event_id="evt-ready",
                ),
            )
        )

        fetched = await store.get_event("evt-ready")
        assert fetched is not None
        assert fetched["embedding_status"] == "ready"
        assert fetched["embedding_profile_id"] is not None

        conn = sqlite3.connect(str(tmp_path / "l1_events.db"))
        profile_row = conn.execute(
            f"SELECT provider_name, model_name, embedding_dim FROM {EMBEDDING_PROFILES_TABLE} WHERE profile_id = ?",
            (fetched["embedding_profile_id"],),
        ).fetchone()
        conn.close()

        assert profile_row == ("fake", "embed-a", 8)
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_marks_ready_embeddings_stale_after_profile_switch(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    embedding_service = _BatchTrackingEmbeddingService(model_name="embed-a", dimension=8)
    store = L1EventStore(
        db_path=str(tmp_path / "l1_events.db"),
        embedding_service=embedding_service,
        async_embeddings=False,
    )
    await store.initialize()
    try:
        await store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "calm note",
                        "author_type": "user",
                        "content_type": "text",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id="corr-stale",
                    event_id="evt-stale",
                ),
            )
        )

        embedding_service.model_name = "embed-b"
        embedding_service.embedding_dimension = 16

        fetched = await store.get_event("evt-stale")

        assert fetched is not None
        assert fetched["embedding_status"] == "stale"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_marks_skipped_and_disabled_embedding_states(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    disabled_store = L1EventStore(db_path=str(tmp_path / "disabled.db"), vector_enabled=False)
    await disabled_store.initialize()
    try:
        await disabled_store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "plain note",
                        "author_type": "user",
                        "content_type": "text",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id="corr-disabled",
                    event_id="evt-disabled",
                ),
            )
        )
        disabled = await disabled_store.get_event("evt-disabled")
        assert disabled is not None
        assert disabled["embedding_status"] == "disabled"
    finally:
        await disabled_store.shutdown()

    embedding_service = _BatchTrackingEmbeddingService()
    skipped_store = L1EventStore(
        db_path=str(tmp_path / "skipped.db"),
        embedding_service=embedding_service,
        async_embeddings=False,
    )
    await skipped_store.initialize()
    try:
        await skipped_store.store(
            normalize_runtime_event(
                Event(
                    type="TRACE_NODE_COMPLETED",
                    data={
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "trace node",
                        "author_type": "system",
                        "content_type": "observation",
                    },
                    source="runtime",
                    level=EventLevel.INFO,
                    correlation_id="corr-skipped",
                    event_id="evt-skipped",
                ),
            )
        )
        skipped = await skipped_store.get_event("evt-skipped")
        assert skipped is not None
        assert skipped["embedding_status"] == "skipped"
    finally:
        await skipped_store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_masks_legacy_failed_status_when_vectors_disabled(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "legacy_failed.db"
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        now = time.time()
        with sqlite3.connect(str(db_path)) as conn:
            conn.executemany(
                """
                INSERT INTO fact_events(
                    event_id, timestamp, created_at, event_type, source,
                    source_item_id, idempotency_key, memory_domain,
                    cognition_eligible, retention_class, session_id, turn_id,
                    user_id, content, author_type, content_type,
                    importance_score, media_path, metadata_json, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "evt-legacy-failed-user",
                        now,
                        now,
                        "USER_MESSAGE",
                        "chat",
                        None,
                        None,
                        int(MemoryDomain.USER_AUTHORED),
                        1,
                        int(RetentionClass.PERMANENT),
                        "s1",
                        None,
                        "u1",
                        "legacy failed user event",
                        author_type_code("user"),
                        content_type_code("text"),
                        0.5,
                        None,
                        None,
                        None,
                    ),
                    (
                        "evt-legacy-failed-runtime",
                        now + 1,
                        now + 1,
                        "TRACE_NODE_COMPLETED",
                        "runtime",
                        None,
                        None,
                        int(MemoryDomain.RUNTIME_TELEMETRY),
                        0,
                        int(RetentionClass.COMPRESSIBLE),
                        None,
                        None,
                        None,
                        "legacy failed runtime event",
                        author_type_code("system"),
                        content_type_code("observation"),
                        0.1,
                        None,
                        None,
                        None,
                    ),
                ],
            )
            conn.executemany(
                """
                INSERT INTO l1_event_embedding_state(
                    event_id, embedding_status, embedding_profile_id,
                    embedding_chunk_count, last_embedded_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    ("evt-legacy-failed-user", embedding_status_code("failed"), None, 0, None, now),
                    (
                        "evt-legacy-failed-runtime",
                        embedding_status_code("failed"),
                        None,
                        0,
                        None,
                        now + 1,
                    ),
                ],
            )
            conn.commit()

        disabled = await store.get_event("evt-legacy-failed-user")
        skipped = await store.get_event("evt-legacy-failed-runtime")

        assert disabled is not None
        assert disabled["embedding_status"] == "disabled"
        assert skipped is not None
        assert skipped["embedding_status"] == "skipped"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_event_store_marks_unreturned_batch_embeddings_failed(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    embedding_service = _ShortBatchEmbeddingService(returned_count=1)
    store = L1EventStore(
        db_path=str(tmp_path / "l1_events.db"),
        embedding_service=embedding_service,
        async_embeddings=False,
    )
    await store.initialize()
    recording_index = _RecordingVectorIndex()
    store._vector_index = recording_index  # type: ignore[assignment]
    store._schedule_event_embedding = lambda event: asyncio.sleep(0)  # type: ignore[method-assign]

    try:
        events = [
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": f"career note {idx}",
                        "author_type": "user",
                        "content_type": "text",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id=f"corr-short-{idx}",
                    event_id=f"evt-short-{idx}",
                ),
            )
            for idx in range(2)
        ]
        for event in events:
            await store.store(event)

        await store._maybe_upsert_event_embeddings(events)

        first = await store.get_event("evt-short-0")
        second = await store.get_event("evt-short-1")
    finally:
        await store.shutdown()

    assert recording_index.upsert_many_calls == [["evt-short-0::chunk-0"]]
    assert first is not None
    assert first["embedding_status"] == "ready"
    assert second is not None
    assert second["embedding_status"] == "failed"


@pytest.mark.asyncio
async def test_l1_rebuild_embeddings_reindexes_disabled_events(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    disabled_store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await disabled_store.initialize()
    try:
        await disabled_store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "user-1",
                        "session_id": "session-1",
                        "turn_id": "turn-1",
                        "content": "Career planning note that should be rebuilt",
                        "author_type": "user",
                        "content_type": "text",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id="evt-rebuild",
                    timestamp=1710000000.0,
                    event_id="evt-rebuild",
                ),
            )
        )
    finally:
        await disabled_store.shutdown()

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE l1_event_embedding_state SET updated_at = ? WHERE event_id = ?",
            (1.0, "evt-rebuild"),
        )
        conn.commit()

    rebuild_store = L1EventStore(
        db_path=str(db_path),
        embedding_service=_BatchTrackingEmbeddingService(),
        async_embeddings=False,
    )
    await rebuild_store.initialize()
    try:
        processed = await rebuild_store.rebuild_embeddings(batch_size=10)
        rebuilt = await rebuild_store.get_event("evt-rebuild")
    finally:
        await rebuild_store.shutdown()

    assert processed == 1
    assert rebuilt is not None
    assert rebuilt["embedding_status"] == "ready"
    assert rebuilt["embedding_profile_id"] is not None
    assert rebuilt["embedding_chunk_count"] > 0
    assert rebuilt["last_embedded_at"] is not None
    with sqlite3.connect(str(db_path)) as conn:
        updated_at = conn.execute(
            "SELECT updated_at FROM l1_event_embedding_state WHERE event_id = ?",
            ("evt-rebuild",),
        ).fetchone()[0]
    assert updated_at > 1.0


@pytest.mark.asyncio
async def test_l1_rebuild_keyset_does_not_skip_after_first_event_is_deleted(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    store = L1EventStore(
        db_path=str(tmp_path / "l1_events.db"),
        embedding_service=_BatchTrackingEmbeddingService(),
        async_embeddings=False,
    )
    await store.initialize()
    try:
        for index in range(2):
            await store.store(
                normalize_runtime_event(
                    Event(
                        type=EventTypes.USER_MESSAGE,
                        data={
                            "user_id": "user-1",
                            "session_id": "session-1",
                            "content": f"rebuild page {index}",
                            "author_type": "user",
                            "content_type": "text",
                        },
                        source="chat",
                        level=EventLevel.INFO,
                        correlation_id=f"corr-page-{index}",
                        event_id=f"evt-page-{index}",
                    )
                )
            )

        seen: list[str] = []

        async def delete_first_batch(events: list[MemoryEvent]) -> None:
            seen.extend(event.event_id for event in events)
            if len(seen) == 1:
                await store.mark_deleted(events[0].event_id)

        store._maybe_upsert_event_embeddings = delete_first_batch  # type: ignore[method-assign]
        processed = await store.rebuild_embeddings(batch_size=1)
    finally:
        await store.shutdown()

    assert processed == 2
    assert seen == ["evt-page-0", "evt-page-1"]


@pytest.mark.asyncio
async def test_l1_rebuild_prunes_vectors_that_are_no_longer_embedding_eligible(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(
        db_path=str(db_path),
        embedding_service=_BatchTrackingEmbeddingService(),
        async_embeddings=False,
    )
    await store.initialize()
    chunk_id = "evt-domain-change::chunk-0"
    try:
        await store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "user-1",
                        "session_id": "session-1",
                        "content": "a user-authored event that was initially searchable",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id="corr-domain-change",
                    event_id="evt-domain-change",
                )
            )
        )
        assert chunk_id in await store._vector_index.get_vectors(  # type: ignore[union-attr]
            entity_ids=[chunk_id]
        )

        with sqlite3.connect(db_path) as db:
            db.execute(
                "UPDATE fact_events SET memory_domain = ? WHERE event_id = ?",
                (int(MemoryDomain.RUNTIME_TELEMETRY), "evt-domain-change"),
            )
            db.commit()

        assert await store.rebuild_embeddings(batch_size=1) == 1
        assert (
            await store._vector_index.get_vectors(  # type: ignore[union-attr]
                entity_ids=[chunk_id]
            )
            == {}
        )
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_rebuild_removes_old_embedding_when_current_event_has_no_text(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(
        db_path=str(db_path),
        embedding_service=_BatchTrackingEmbeddingService(),
        async_embeddings=False,
    )
    await store.initialize()
    chunk_id = "evt-empty-text::chunk-0"
    try:
        await store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "user-1",
                        "session_id": "session-1",
                        "content": "career note that was initially searchable",
                        "author_type": "user",
                        "content_type": "text",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id="corr-empty-text",
                    event_id="evt-empty-text",
                )
            )
        )
        with sqlite3.connect(db_path) as db:
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM l1_event_chunk_vectors WHERE chunk_id = ?",
                    (chunk_id,),
                ).fetchone()[0]
                == 1
            )
            db.execute(
                "UPDATE fact_events SET content = '', metadata_json = NULL WHERE event_id = ?",
                ("evt-empty-text",),
            )
            db.commit()

        assert await store.rebuild_embeddings(batch_size=1) == 1
        current = await store.get_event("evt-empty-text")
        with sqlite3.connect(db_path) as db:
            vector_count = db.execute(
                "SELECT COUNT(*) FROM l1_event_chunk_vectors WHERE chunk_id = ?",
                (chunk_id,),
            ).fetchone()[0]
            chunk_count = db.execute(
                "SELECT COUNT(*) FROM l1_event_chunks WHERE event_id = ?",
                ("evt-empty-text",),
            ).fetchone()[0]
    finally:
        await store.shutdown()

    assert current is not None
    assert current["embedding_status"] == "skipped"
    assert current["embedding_chunk_count"] == 0
    assert vector_count == 0
    assert chunk_count == 0
