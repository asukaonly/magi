from __future__ import annotations

import sqlite3

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
            event_id=event_id,
        ),
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
            event_id=event_id,
        ),
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
        from magi.memory.embedding.embedding_service import EmbeddingResult

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

    def result_for_index(self, result, *, text_builder_version: str):
        # Mirror MemoryEmbeddingService.result_for_index; identity is enough.
        return result


class _IdentityEmbeddingService(_BatchTrackingEmbeddingService):
    def __init__(self, identity: str) -> None:
        super().__init__()
        self.identity = identity

    def _make_result(self, text: str):
        result = super()._make_result(text)
        result.index_identity = self.identity
        return result


def _skill_vector_models(db_path, chunk_id: str) -> set[str]:  # type: ignore[no-untyped-def]
    with sqlite3.connect(db_path) as db:
        rows = db.execute(
            """
            SELECT embedding_model
            FROM l4_skill_chunk_vectors
            WHERE chunk_id = ?
            """,
            (chunk_id,),
        ).fetchall()
    return {str(row[0]) for row in rows}


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

    await store.record_memory_event(
        _tool_event(event_id="evt-1", success=True, timestamp=1710000000.0)
    )
    await store.record_memory_event(
        _tool_event(event_id="evt-2", success=True, timestamp=1710000100.0)
    )
    await store.record_memory_event(
        _tool_event(event_id="evt-3", success=False, timestamp=1710000200.0, error="timeout")
    )

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

    await store.record_memory_event(
        _tool_event(event_id="evt-1", success=False, timestamp=1710000000.0, error="e1")
    )
    await store.record_memory_event(
        _tool_event(event_id="evt-2", success=False, timestamp=1710000100.0, error="e2")
    )
    await store.record_memory_event(
        _tool_event(event_id="evt-3", success=False, timestamp=1710000200.0, error="e3")
    )

    opened = await store.get_skill(skill_name="browser.open", skill_category="tool")
    assert opened is not None
    assert opened["circuit_breaker_state"] == "open"

    await store.record_memory_event(
        _tool_event(event_id="evt-4", success=True, timestamp=1710000300.0)
    )
    half_open = await store.get_skill(skill_name="browser.open", skill_category="tool")
    assert half_open is not None
    assert half_open["circuit_breaker_state"] == "half_open"

    await store.record_memory_event(
        _tool_event(event_id="evt-5", success=True, timestamp=1710000400.0)
    )
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
    assert all(
        chunk_id.startswith(f"{skill_id}::chunk-")
        for chunk_id in recording_index.upsert_many_calls[0]
    )
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
    from magi.memory.embedding.sqlite_vec_index import VectorSearchHit

    embedding_service = _BatchTrackingEmbeddingService()
    store = L4ProceduralMemoryStore(
        db_path=str(tmp_path / "l4.db"),
        embedding_service=embedding_service,
        async_embeddings=False,
    )
    await store.initialize()

    long_prompt = (
        "browser workflow recovery guidance " * 18 + "workflow recovery browser checklist " * 18
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


@pytest.mark.asyncio
async def test_l4_rebuild_embeddings_reindexes_disabled_skills(tmp_path):
    from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore

    disabled_store = L4ProceduralMemoryStore(db_path=str(tmp_path / "l4.db"), vector_enabled=False)
    await disabled_store.initialize()
    try:
        await disabled_store.record_memory_event(
            _task_event(
                event_id="evt-rebuild",
                task_id="browser-workflow",
                success=True,
                timestamp=1710000000.0,
                content="browser workflow recovery guidance that should be rebuilt",
            )
        )
    finally:
        await disabled_store.shutdown()

    rebuild_store = L4ProceduralMemoryStore(
        db_path=str(tmp_path / "l4.db"),
        embedding_service=_BatchTrackingEmbeddingService(),
        async_embeddings=False,
    )
    await rebuild_store.initialize()
    try:
        processed = await rebuild_store.rebuild_embeddings(batch_size=10)
        skill = await rebuild_store.get_skill(
            skill_name="browser-workflow", skill_category="workflow"
        )
    finally:
        await rebuild_store.shutdown()

    assert processed == 1
    assert skill is not None
    assert skill["embedding_status"] == "ready"
    assert skill["embedding_profile_id"] is not None
    assert skill["embedding_chunk_count"] > 0
    assert skill["last_embedded_at"] is not None


@pytest.mark.asyncio
async def test_l4_rebuild_keeps_old_identity_when_parent_changes_before_publish(tmp_path):
    from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore

    db_path = tmp_path / "l4.db"
    store = L4ProceduralMemoryStore(
        db_path=str(db_path),
        embedding_service=_IdentityEmbeddingService("old-identity"),
        async_embeddings=False,
    )
    await store.initialize()
    models_before_change: set[str] = set()
    try:
        skill_id = await store.record_memory_event(
            _task_event(
                event_id="evt-stale-rebuild",
                task_id="browser-workflow",
                success=True,
                timestamp=1710000000.0,
                content="browser workflow recovery before a concurrent correction",
            )
        )
        assert skill_id is not None
        chunk_id = f"{skill_id}::chunk-0"
        assert _skill_vector_models(db_path, chunk_id) == {"old-identity"}

        store._embedding_service = _IdentityEmbeddingService("new-identity")
        original_publish = store._publish_skill_embedding_result

        async def change_parent_before_publish(result):  # type: ignore[no-untyped-def]
            nonlocal models_before_change
            models_before_change = _skill_vector_models(db_path, chunk_id)
            with sqlite3.connect(db_path) as db:
                db.execute(
                    """
                    UPDATE procedural_skills
                    SET optimized_prompt = ?
                    WHERE skill_id = ?
                    """,
                    (
                        "browser workflow changed during rebuild",
                        skill_id,
                    ),
                )
                db.commit()
            return await original_publish(result)

        store._publish_skill_embedding_result = change_parent_before_publish  # type: ignore[method-assign]
        processed = await store.rebuild_embeddings(batch_size=1)
        models_after_rebuild = _skill_vector_models(db_path, chunk_id)
    finally:
        await store.shutdown()

    assert processed == 1
    assert models_before_change == {"old-identity", "new-identity"}
    assert models_after_rebuild == {"old-identity"}


@pytest.mark.asyncio
async def test_l4_rebuild_keyset_does_not_skip_after_first_skill_is_deleted(tmp_path):
    from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore

    db_path = tmp_path / "l4.db"
    store = L4ProceduralMemoryStore(
        db_path=str(db_path),
        embedding_service=_BatchTrackingEmbeddingService(),
        async_embeddings=False,
    )
    await store.initialize()
    try:
        skill_ids = []
        for index in range(2):
            skill_id = await store.record_memory_event(
                _task_event(
                    event_id=f"evt-page-{index}",
                    task_id=f"workflow-page-{index}",
                    success=True,
                    timestamp=1710000000.0 + index,
                    content=f"workflow rebuild page {index}",
                )
            )
            assert skill_id is not None
            skill_ids.append(skill_id)

        seen: list[str] = []

        async def delete_first_skill(**kwargs) -> None:  # type: ignore[no-untyped-def]
            seen.append(str(kwargs["skill_id"]))
            if len(seen) == 1:
                with sqlite3.connect(db_path) as db:
                    db.execute(
                        "UPDATE procedural_skills SET deleted_at = 1 WHERE skill_id = ?",
                        (seen[0],),
                    )
                    db.commit()

        store._maybe_upsert_skill_embedding = delete_first_skill  # type: ignore[method-assign]
        processed = await store.rebuild_embeddings(batch_size=1)
    finally:
        await store.shutdown()

    assert processed == 2
    assert seen == skill_ids


@pytest.mark.asyncio
async def test_execution_replay_does_not_change_counts_or_breaker(tmp_path):
    import asyncio
    from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore
    store = L4ProceduralMemoryStore(db_path=str(tmp_path / "l4.db"), vector_enabled=False)
    event = _tool_event(event_id="execution:1", success=False, timestamp=1710000000.0)
    event.turn_id = "turn:one"
    await store.record_memory_event(event)
    await asyncio.gather(*[store.record_memory_event(event) for _ in range(5)])
    with sqlite3.connect(store.db_path) as db:
        assert db.execute("SELECT total_attempts, failure_count, circuit_breaker_failure_count FROM procedural_skills").fetchone() == (1, 1, 1)
        assert db.execute("SELECT COUNT(*) FROM l4_execution_traces").fetchone() == (1,)
    second = _tool_event(event_id="execution:2", success=True, timestamp=1710000001.0)
    second.turn_id = event.turn_id
    await store.record_memory_event(second)
    with sqlite3.connect(store.db_path) as db:
        assert db.execute("SELECT total_attempts, success_count FROM procedural_skills").fetchone() == (2, 1)
        assert db.execute("SELECT COUNT(*) FROM l4_execution_traces").fetchone() == (2,)


@pytest.mark.asyncio
async def test_trace_failure_rolls_back_learning(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore
    store = L4ProceduralMemoryStore(db_path=str(tmp_path / "l4.db"), vector_enabled=False)
    event = _tool_event(event_id="execution:rollback", success=True, timestamp=1710000000.0)
    with monkeypatch.context() as scoped:
        scoped.setattr("magi.memory.l4.recording.insert_execution_trace", AsyncMock(side_effect=RuntimeError("trace unavailable")))
        with pytest.raises(RuntimeError, match="trace unavailable"):
            await store.record_memory_event(event)
    with sqlite3.connect(store.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM procedural_skills").fetchone() == (0,)
    await store.record_memory_event(event)
    with sqlite3.connect(store.db_path) as db:
        assert db.execute("SELECT total_attempts FROM procedural_skills").fetchone() == (1,)
