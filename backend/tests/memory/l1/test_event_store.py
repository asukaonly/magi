from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import IngestTarget, MemoryDomain, RetentionClass, TomDepth, normalize_runtime_event


class _BatchTrackingEmbeddingService:
    def __init__(self) -> None:
        self.single_calls: list[str] = []
        self.batch_calls: list[list[str]] = []

    async def embed_text(self, text: str):
        self.single_calls.append(text)
        return self._make_result(text)

    async def embed_texts(self, texts: list[str]):
        self.batch_calls.append(list(texts))
        return [self._make_result(text) for text in texts]

    def _make_result(self, text: str):
        from magi.memory.embedding_service import EmbeddingResult

        lowered = text.lower()
        vector = [0.0, 0.0, 0.0, 0.0]
        if "stress" in lowered:
            vector[0] = 1.0
        if "calm" in lowered:
            vector[1] = 1.0
        if "career" in lowered:
            vector[2] = 1.0
        if not any(vector):
            vector[3] = 1.0
        return EmbeddingResult(model_name="test-embedding", dimension=4, vector=vector)


@pytest.mark.asyncio
async def test_l1_event_store_persists_and_filters_memory_events(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path))
    await store.initialize()

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


@pytest.mark.asyncio
async def test_l1_event_store_restores_final_memory_event_shape(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()

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


@pytest.mark.asyncio
async def test_l1_timeline_roundtrip_uses_timeline_metadata(tmp_path):
    from magi.memory.l1.event_store import L1EventStore
    from magi.timeline.contracts import TimelineContentBlock, TimelineEvent

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path))
    await store.initialize()

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


@pytest.mark.asyncio
async def test_l1_store_initializes_without_runtime_observations_table(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path))
    await store.initialize()

    conn = sqlite3.connect(str(db_path))
    table_names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    conn.close()

    assert "fact_events" in table_names
    assert "runtime_observations" not in table_names


@pytest.mark.asyncio
async def test_l1_event_store_persists_action_events_in_fact_events(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path))
    await store.initialize()

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


@pytest.mark.asyncio
async def test_l1_event_store_decodes_integer_classification_fields(tmp_path):
    import sqlite3

    from magi.memory.l1.event_store import L1EventStore

    db_path = tmp_path / "l1_events.db"
    store = L1EventStore(db_path=str(db_path))
    await store.initialize()

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


@pytest.mark.asyncio
async def test_l1_async_embeddings_flush_full_batches_via_batch_api(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    embedding_service = _BatchTrackingEmbeddingService()
    store = L1EventStore(
        db_path=str(tmp_path / "l1_events.db"),
        embedding_service=embedding_service,
        async_embeddings=True,
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
