from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.l1.chat_sessions import CHAT_SESSIONS_TABLE
from magi.memory.event_contracts import IngestTarget, MemoryDomain, RetentionClass, TomDepth, normalize_runtime_event


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
        from magi.memory.embedding_service import EmbeddingProfile, EmbeddingResult

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
        return EmbeddingResult(model_name=self.model_name, dimension=self.embedding_dimension, vector=vector)

    def get_active_profile(self, *, text_builder_version: str):
        from magi.memory.embedding_service import EmbeddingProfile

        return EmbeddingProfile.build(
            provider_name=self.provider_name,
            model_name=self.model_name,
            dimension=self.embedding_dimension,
            text_builder_version=text_builder_version,
        )

    def profile_from_result(self, result, *, text_builder_version: str):
        from magi.memory.embedding_service import EmbeddingProfile

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
        )
        memory_event = normalize_runtime_event(event, event_id="evt-1")

        stored_event_id = await store.store(memory_event)
        fetched = await store.get_event("evt-1")
        queried = await store.query_events(session_id="session-1", memory_domain="user_authored", limit=10)

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
async def test_l1_event_store_restores_final_memory_event_shape(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        event = Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "web_user",
                "session_id": "session-1",
                "turn_id": "turn-identity-1",
                "content": "Remember me",
                "author_type": "user",
                "content_type": "text",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id="corr-identity-1",
        )
        memory_event = normalize_runtime_event(event, event_id="evt-identity-1")

        await store.store(memory_event)
        fetched = await store.get_event("evt-identity-1")
        restored = await store.get_memory_event("evt-identity-1")

        assert fetched is not None
        assert fetched["user_id"] == "web_user"
        assert fetched["turn_id"] == "turn-identity-1"
        assert restored is not None
        assert restored.user_id == "web_user"
        assert restored.content == "Remember me"
        assert restored.author_type == "user"
        assert restored.content_type == "text"
        assert restored.turn_id == "turn-identity-1"
        assert not hasattr(restored, "runtime_user_id")
        assert not hasattr(restored, "memory_owner_id")
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l1_timeline_roundtrip_uses_timeline_metadata(tmp_path):
    from magi.memory.l1.event_store import L1EventStore
    from magi.timeline.contracts import TimelineContentBlock, TimelineEvent

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path))
    await store.initialize()
    try:
        timeline_event = TimelineEvent(
            event_id="timeline-1",
            source_type="manual_journal",
            source_item_id="journal-1",
            occurred_at=1710000000.0,
            captured_at=1710000001.0,
            title="Journal",
            summary="A reflective note",
            retention_mode="retain_raw",
            content_blocks=[TimelineContentBlock(kind="text", value="I felt stressed today.")],
            processing_status={"stored": False},
            provenance={"source": "manual_journal", "session_id": "session-1"},
        )

        await store.store_timeline_event(timeline_event)

        fetched = await store.get_timeline_event("timeline-1")
        listed = await store.list_timeline_events(limit=10, source_type="manual_journal")

        assert fetched is not None
        assert fetched["event_id"] == "timeline-1"
        assert fetched["summary"] == "A reflective note"
        assert len(listed) == 1
        assert listed[0]["summary"] == "A reflective note"
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
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
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
        )
        memory_event = normalize_runtime_event(event, event_id="evt-runtime-1")
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
        )

        await store.store(normalize_runtime_event(event, event_id="evt-chat-session-user"))

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
        assert row[0] == "New Chat"
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
                ),
                event_id="evt-chat-session-seed",
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
                ),
                event_id="evt-chat-session-ai",
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
            ),
            event_id="evt-idempotent",
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
        event_count = conn.execute("SELECT COUNT(*) FROM fact_events WHERE event_id = ?", ("evt-idempotent",)).fetchone()
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
                ),
                event_id="evt-search-fallback",
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
                event_id, correlation_id, timestamp, created_at,
                event_type, source, source_item_id, memory_domain, ingest_target,
                cognition_eligible, tom_depth, retention_class, session_id, turn_id, user_id,
                task_id, content, author_type, content_type, importance_score,
                level, media_path, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "evt-decoded",
                "corr-1",
                1.0,
                1.0,
                "UserMessage",
                "chat",
                None,
                int(MemoryDomain.USER_AUTHORED),
                int(IngestTarget.L1_ONLY),
                1,
                int(TomDepth.DEFENSIVE_PSYCHOLOGY),
                int(RetentionClass.PERMANENT),
                "session-1",
                "turn-1",
                "user-1",
                None,
                "hello",
                "user",
                "text",
                0.8,
                1,
                None,
                None,
            ),
        )
        conn.commit()
        conn.close()

        fetched = await store.get_event("evt-decoded")

        assert fetched is not None
        assert fetched["memory_domain"] == "user_authored"
        assert fetched["ingest_target"] == "l1_only"
        assert fetched["tom_depth"] == "defensive_psychology"
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
                    ),
                    event_id=f"evt-batch-{idx}",
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
                    ),
                    event_id=f"evt-timeout-{idx}",
                )
            )

        assert store._embedding_queue is not None
        await asyncio.wait_for(store._embedding_queue.join(), timeout=1.0)
    finally:
        await store.shutdown()

    assert time.monotonic() - started_at >= 0.04
    assert embedding_service.single_calls == []
    assert embedding_service.batch_calls == [[
        "stress note 0",
        "stress note 1",
    ]]


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
                ),
                event_id="evt-queue-1",
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
                    ),
                    event_id="evt-queue-2",
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
                    ),
                    event_id="evt-queue-3",
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
                ),
                event_id="evt-worker-a",
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
                ),
                event_id="evt-worker-b",
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
            ),
            event_id=f"evt-many-{idx}",
        )
        for idx in range(3)
    ]

    await store._maybe_upsert_event_embeddings(events)

    assert recording_index.upsert_many_calls == [["evt-many-0", "evt-many-1", "evt-many-2"]]
    assert recording_index.upsert_calls == []
    await store.shutdown()


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
                ),
                event_id="evt-ready",
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
                ),
                event_id="evt-stale",
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
                ),
                event_id="evt-disabled",
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
                ),
                event_id="evt-skipped",
            )
        )
        skipped = await skipped_store.get_event("evt-skipped")
        assert skipped is not None
        assert skipped["embedding_status"] == "skipped"
    finally:
        await skipped_store.shutdown()


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
                ),
                event_id=f"evt-short-{idx}",
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

    assert recording_index.upsert_many_calls == [["evt-short-0"]]
    assert first is not None
    assert first["embedding_status"] == "ready"
    assert second is not None
    assert second["embedding_status"] == "failed"
