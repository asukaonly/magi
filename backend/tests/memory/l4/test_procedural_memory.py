from __future__ import annotations

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event


def _tool_event(*, event_id: str, success: bool, timestamp: float, error: str | None = None):
    return normalize_runtime_event(
        Event(
            type=EventTypes.ACTION_EXECUTED,
            data={
                "action_type": "browser.open",
                "params": {"url": "https://example.com"},
                "success": success,
                "execution_time": 0.5,
                "error": error,
                "session_id": "s1",
                "user_id": "u1",
            },
            source="worker",
            level=EventLevel.INFO if success else EventLevel.ERROR,
            correlation_id=event_id,
            timestamp=timestamp,
        ),
        event_id=event_id,
    )


def _task_event(*, event_id: str, task_id: str, success: bool, timestamp: float, content: str):
    return normalize_runtime_event(
        Event(
            type=EventTypes.TASK_COMPLETED if success else EventTypes.TASK_FAILED,
            data={
                "task_id": task_id,
                "content": content,
                "session_id": "s1",
                "user_id": "u1",
            },
            source="worker",
            level=EventLevel.INFO if success else EventLevel.ERROR,
            correlation_id=event_id,
            timestamp=timestamp,
        ),
        event_id=event_id,
    )


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
        if "browser" in lowered:
            vector[0] = 1.0
        if "workflow" in lowered:
            vector[1] = 1.0
        if "recovery" in lowered:
            vector[2] = 1.0
        if not any(vector):
            vector[3] = 1.0
        return EmbeddingResult(model_name="test-embedding", dimension=4, vector=vector)


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


@pytest.mark.asyncio
async def test_l4_tracks_success_rate_and_queryable_strategy(tmp_path):
    from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore

    store = L4ProceduralMemoryStore(db_path=str(tmp_path / "l4.db"))
    await store.initialize()

    await store.record_memory_event(_tool_event(event_id="evt-1", success=True, timestamp=1710000000.0))
    await store.record_memory_event(_tool_event(event_id="evt-2", success=True, timestamp=1710000100.0))
    await store.record_memory_event(_tool_event(event_id="evt-3", success=False, timestamp=1710000200.0, error="timeout"))

    skill = await store.get_skill(skill_name="browser.open", skill_category="tool")
    strategies = await store.query_strategies(query="browser", limit=5)

    assert skill is not None
    assert skill["total_attempts"] == 3
    assert skill["success_rate"] == pytest.approx(2 / 3, rel=1e-3)
    assert strategies[0]["skill_name"] == "browser.open"


@pytest.mark.asyncio
async def test_l4_opens_and_recovers_circuit_breaker(tmp_path):
    from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore

    store = L4ProceduralMemoryStore(db_path=str(tmp_path / "l4.db"), breaker_failure_threshold=3)
    await store.initialize()

    await store.record_memory_event(_tool_event(event_id="evt-1", success=False, timestamp=1710000000.0, error="e1"))
    await store.record_memory_event(_tool_event(event_id="evt-2", success=False, timestamp=1710000100.0, error="e2"))
    await store.record_memory_event(_tool_event(event_id="evt-3", success=False, timestamp=1710000200.0, error="e3"))

    opened = await store.get_skill(skill_name="browser.open", skill_category="tool")
    assert opened is not None
    assert opened["circuit_breaker_state"] == "open"

    await store.record_memory_event(_tool_event(event_id="evt-4", success=True, timestamp=1710000300.0))
    half_open = await store.get_skill(skill_name="browser.open", skill_category="tool")
    assert half_open is not None
    assert half_open["circuit_breaker_state"] == "half_open"

    await store.record_memory_event(_tool_event(event_id="evt-5", success=True, timestamp=1710000400.0))
    recovered = await store.get_skill(skill_name="browser.open", skill_category="tool")
    assert recovered is not None
    assert recovered["circuit_breaker_state"] == "closed"


@pytest.mark.asyncio
async def test_l4_long_prompt_indexes_skill_chunks(tmp_path):
    from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore

    embedding_service = _BatchTrackingEmbeddingService()
    store = L4ProceduralMemoryStore(
        db_path=str(tmp_path / "l4.db"),
        embedding_service=embedding_service,
        async_embeddings=False,
    )
    await store.initialize()
    recording_index = _RecordingVectorIndex()
    store._vector_index = recording_index  # type: ignore[assignment]

    long_prompt = (
        "browser workflow recovery guidance " * 24
        + "browser workflow fallback plan " * 24
        + "browser workflow validation checklist " * 24
    )

    try:
        skill_id = await store.record_memory_event(
            _task_event(
                event_id="evt-long",
                task_id="browser-workflow",
                success=True,
                timestamp=1710000000.0,
                content=long_prompt,
            )
        )
        skill = await store.get_skill(skill_name="browser-workflow", skill_category="workflow")
    finally:
        await store.shutdown()

    assert skill_id is not None
    assert len(recording_index.upsert_many_calls) == 1
    assert all(chunk_id.startswith(f"{skill_id}::chunk-") for chunk_id in recording_index.upsert_many_calls[0])
    assert skill is not None
    assert skill["embedding_chunk_count"] > 1


@pytest.mark.asyncio
async def test_l4_skill_exposes_embedding_status_and_profile_id(tmp_path):
    from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore

    embedding_service = _BatchTrackingEmbeddingService()
    store = L4ProceduralMemoryStore(
        db_path=str(tmp_path / "l4.db"),
        embedding_service=embedding_service,
        async_embeddings=False,
    )
    await store.initialize()
    try:
        await store.record_memory_event(
            _task_event(
                event_id="evt-status",
                task_id="browser-workflow",
                success=True,
                timestamp=1710000000.0,
                content="browser workflow recovery guidance",
            )
        )
        skill = await store.get_skill(skill_name="browser-workflow", skill_category="workflow")
    finally:
        await store.shutdown()

    assert skill is not None
    assert skill["embedding_status"] == "ready"
    assert skill["embedding_profile_id"] is not None


@pytest.mark.asyncio
async def test_l4_semantic_query_folds_chunk_hits_to_parent_skill(tmp_path):
    from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore
    from magi.memory.sqlite_vec_index import VectorSearchHit

    embedding_service = _BatchTrackingEmbeddingService()
    store = L4ProceduralMemoryStore(
        db_path=str(tmp_path / "l4.db"),
        embedding_service=embedding_service,
        async_embeddings=False,
    )
    await store.initialize()

    long_prompt = (
        "browser workflow recovery guidance " * 18
        + "workflow recovery browser checklist " * 18
    )

    try:
        skill_id = await store.record_memory_event(
            _task_event(
                event_id="evt-query",
                task_id="browser-workflow",
                success=True,
                timestamp=1710000000.0,
                content=long_prompt,
            )
        )
        assert skill_id is not None

        async def _fake_search(*, embedding, limit: int, max_distance=None):  # type: ignore[no-untyped-def]
            _ = (embedding, limit, max_distance)
            return [
                VectorSearchHit(entity_id=f"{skill_id}::chunk-1", distance=0.03),
                VectorSearchHit(entity_id=f"{skill_id}::chunk-0", distance=0.07),
            ]

        store._vector_index.search = _fake_search  # type: ignore[method-assign]
        ranked = await store._semantic_query_strategies(query="browser workflow recovery", limit=5)
    finally:
        await store.shutdown()

    assert [item["skill_id"] for item in ranked] == [skill_id]
    assert ranked[0]["distance"] == 0.03
    assert [chunk["chunk_id"] for chunk in ranked[0]["matched_chunks"]] == [
        f"{skill_id}::chunk-1",
        f"{skill_id}::chunk-0",
    ]
