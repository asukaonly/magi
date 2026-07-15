from __future__ import annotations

import asyncio

import aiosqlite
import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event
from magi.memory.l1.event_store import L1EventStore
from magi.memory.l2.edge_embedding_drain import L2EdgeEmbeddingWorker
from magi.memory.embedding.embedding_service import EmbeddingResult
from magi.memory.l3.models import L3Candidate
from magi.memory.l3.summary_store import L3SummaryStore
from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore
from magi.memory.operation_barrier import AsyncOperationBarrier


class _DeterministicEmbeddingService:
    async def embed_text(self, text: str) -> EmbeddingResult:
        return self._result(text)

    async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        return [self._result(text) for text in texts]

    def result_for_index(
        self,
        result: EmbeddingResult,
        *,
        text_builder_version: str,
    ) -> EmbeddingResult:
        _ = text_builder_version
        return result

    @staticmethod
    def _result(text: str) -> EmbeddingResult:
        lowered = text.lower()
        if "travel" in lowered:
            vector = [1.0, 0.0, 0.0]
        elif "coding" in lowered:
            vector = [0.0, 1.0, 0.0]
        else:
            vector = [0.0, 0.0, 1.0]
        return EmbeddingResult(
            model_name="clear-test-embedding",
            dimension=3,
            vector=vector,
        )


class _BlockingNextEmbeddingService(_DeterministicEmbeddingService):
    def __init__(self) -> None:
        self.block_next = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        if self.block_next:
            self.block_next = False
            self.started.set()
            await self.release.wait()
        return await super().embed_texts(texts)


def _user_message(*, event_id: str, content: str):
    return normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "content": content,
                "user_id": "user:u1",
                "session_id": "session-1",
                "author_type": "user",
                "content_type": "text",
            },
            timestamp=1.0,
            source="chat",
            level=EventLevel.INFO,
            event_id=event_id,
        )
    )


async def _assert_batched_worker_clear_cancels_model_phase(
    *,
    store,
    worker_attr: str,
    start_worker,
    enqueue,
    abort,
) -> None:
    barrier = AsyncOperationBarrier()
    store.set_operation_guard_factory(barrier.operation)
    active_entered = asyncio.Event()
    release_active = asyncio.Event()
    new_processed = asyncio.Event()
    processed: list[str] = []

    async def process_batch(batch) -> None:
        names = [str(item) for item in batch]
        if "old-active" in names:
            active_entered.set()
            await release_active.wait()
        processed.extend(names)
        if "new" in names:
            new_processed.set()

    store._test_process_batch = process_batch
    setattr(store, worker_attr, [asyncio.create_task(start_worker())])
    await enqueue("old-active")
    await asyncio.wait_for(active_entered.wait(), timeout=1)
    await enqueue("old-queued")

    clear_entered = asyncio.Event()

    async def clear() -> None:
        async with barrier.exclusive():
            clear_entered.set()
            await abort()
            processed.clear()

    clear_task = asyncio.create_task(clear())
    await asyncio.wait_for(clear_entered.wait(), timeout=1)
    await asyncio.wait_for(clear_task, timeout=1)
    assert processed == []
    release_active.set()

    setattr(store, worker_attr, [asyncio.create_task(start_worker())])
    await enqueue("new")
    await asyncio.wait_for(new_processed.wait(), timeout=1)
    assert processed == ["new"]
    await abort()


@pytest.mark.asyncio
async def test_l1_embedding_worker_cancels_active_model_phase_and_drops_queued_batch(
    tmp_path,
) -> None:
    store = L1EventStore(
        db_path=str(tmp_path / "l1.db"),
        embedding_service=object(),  # type: ignore[arg-type]
        embedding_worker_count=1,
    )
    store._embedding_batch_size = 1

    async def process(events) -> None:
        await store._test_process_batch(events)

    store._maybe_upsert_event_embeddings = process  # type: ignore[method-assign]
    assert store._embedding_queue is not None

    async def enqueue(value: str) -> None:
        assert store._embedding_queue is not None
        await store._embedding_queue.put(value)  # type: ignore[arg-type]

    await _assert_batched_worker_clear_cancels_model_phase(
        store=store,
        worker_attr="_embedding_workers",
        start_worker=store._run_embedding_worker,
        enqueue=enqueue,
        abort=store.abort_for_clear,
    )


@pytest.mark.asyncio
async def test_l3_embedding_worker_finishes_active_batch_and_drops_queued_batch(
    tmp_path,
) -> None:
    store = L3SummaryStore(
        db_path=str(tmp_path / "memory.db"),
        embedding_service=object(),  # type: ignore[arg-type]
    )
    store._embedding_batch_size = 1

    async def process(summaries) -> None:
        await store._test_process_batch(summaries)

    store._maybe_upsert_summary_embeddings = process  # type: ignore[method-assign]
    assert store._embedding_queue is not None

    async def abort() -> None:
        await store.abort_for_clear()

    async def run_worker() -> None:
        await store._run_embedding_worker()

    async def enqueue(value: str) -> None:
        assert store._embedding_queue is not None
        await store._embedding_queue.put(value)  # type: ignore[arg-type]

    async def exercise() -> None:
        barrier = AsyncOperationBarrier()
        store.set_operation_guard_factory(barrier.operation)
        active_entered = asyncio.Event()
        release_active = asyncio.Event()
        new_processed = asyncio.Event()
        processed: list[str] = []

        async def process_batch(batch) -> None:
            names = [str(item) for item in batch]
            if "old-active" in names:
                active_entered.set()
                await release_active.wait()
            processed.extend(names)
            if "new" in names:
                new_processed.set()

        store._test_process_batch = process_batch
        store._embedding_worker = asyncio.create_task(run_worker())
        await enqueue("old-active")
        await asyncio.wait_for(active_entered.wait(), timeout=1)
        await enqueue("old-queued")

        clear_entered = asyncio.Event()

        async def clear() -> None:
            async with barrier.exclusive():
                clear_entered.set()
                await abort()
                processed.clear()

        clear_task = asyncio.create_task(clear())
        await asyncio.wait_for(clear_entered.wait(), timeout=1)
        await asyncio.wait_for(clear_task, timeout=1)
        assert processed == []

        store._embedding_worker = asyncio.create_task(run_worker())
        await enqueue("new")
        await asyncio.wait_for(new_processed.wait(), timeout=1)
        assert processed == ["new"]
        release_active.set()
        await abort()

    await exercise()


@pytest.mark.asyncio
async def test_l4_embedding_worker_cancels_active_model_phase_and_drops_queued_item(
    tmp_path,
) -> None:
    store = L4ProceduralMemoryStore(
        db_path=str(tmp_path / "memory.db"),
        embedding_service=object(),  # type: ignore[arg-type]
    )
    barrier = AsyncOperationBarrier()
    store.set_operation_guard_factory(barrier.operation)
    active_entered = asyncio.Event()
    release_active = asyncio.Event()
    new_processed = asyncio.Event()
    processed: list[str] = []

    async def process(*, skill_id: str, **_kwargs) -> None:
        if skill_id == "old-active":
            active_entered.set()
            await release_active.wait()
        processed.append(skill_id)
        if skill_id == "new":
            new_processed.set()

    store._maybe_upsert_skill_embedding = process  # type: ignore[method-assign]
    assert store._embedding_queue is not None
    store._embedding_worker = asyncio.create_task(store._run_embedding_worker())

    def item(skill_id: str) -> dict[str, str | None]:
        return {
            "skill_id": skill_id,
            "skill_name": skill_id,
            "skill_category": "test",
            "optimized_prompt": None,
        }

    await store._embedding_queue.put(item("old-active"))
    await asyncio.wait_for(active_entered.wait(), timeout=1)
    await store._embedding_queue.put(item("old-queued"))

    clear_entered = asyncio.Event()

    async def clear() -> None:
        async with barrier.exclusive():
            clear_entered.set()
            await store.abort_for_clear()
            processed.clear()

    clear_task = asyncio.create_task(clear())
    await asyncio.wait_for(clear_entered.wait(), timeout=1)
    await asyncio.wait_for(clear_task, timeout=1)
    assert processed == []
    release_active.set()

    store._embedding_worker = asyncio.create_task(store._run_embedding_worker())
    assert store._embedding_queue is not None
    await store._embedding_queue.put(item("new"))
    await asyncio.wait_for(new_processed.wait(), timeout=1)
    assert processed == ["new"]
    await store.abort_for_clear()


@pytest.mark.asyncio
async def test_l3_vector_index_survives_clear_and_accepts_new_embeddings(tmp_path) -> None:
    store = L3SummaryStore(
        db_path=str(tmp_path / "memory.db"),
        embedding_service=_DeterministicEmbeddingService(),
        async_embeddings=False,
    )
    await store.initialize()
    try:
        await store.upsert_candidate(
            candidate=L3Candidate(
                summary_type="insight",
                summary_category="topic",
                content="Travel planning preference.",
                source_event_ids=["evt-old"],
                insight_key="topic:old",
            )
        )
        assert await store.vector_search(query="travel", limit=10)

        await store.abort_for_clear()
        assert await store.clear() == 1
        await store.initialize()
        assert await store.vector_search(query="travel", limit=10) == []

        fresh = await store.upsert_candidate(
            candidate=L3Candidate(
                summary_type="insight",
                summary_category="topic",
                content="Coding workflow preference.",
                source_event_ids=["evt-new"],
                insight_key="topic:new",
            )
        )
        recalled = await store.vector_search(query="coding", limit=10)
        assert [item["summary_id"] for item in recalled] == [fresh["summary_id"]]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l4_vector_index_survives_clear_and_accepts_new_embeddings(tmp_path) -> None:
    store = L4ProceduralMemoryStore(
        db_path=str(tmp_path / "memory.db"),
        embedding_service=_DeterministicEmbeddingService(),
        async_embeddings=False,
    )
    await store.initialize()
    try:
        old_skill_id = await store.record_task_preference(
            user_id="user:u1",
            task_category="travel",
            preference="Prefer travel plans with quiet hotels.",
        )
        assert old_skill_id is not None
        assert await store._semantic_query_strategies(query="travel", limit=10)

        await store.abort_for_clear()
        assert await store.clear() == 1
        await store.initialize()
        assert await store._semantic_query_strategies(query="travel", limit=10) == []

        new_skill_id = await store.record_task_preference(
            user_id="user:u1",
            task_category="coding",
            preference="Prefer coding changes with tests.",
        )
        assert new_skill_id is not None
        recalled = await store._semantic_query_strategies(query="coding", limit=10)
        assert [item["skill_id"] for item in recalled] == [new_skill_id]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_clear_removes_existing_vectors_without_loading_an_embedding_model(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "memory.db")
    service = _DeterministicEmbeddingService()
    seeded_l3 = L3SummaryStore(
        db_path=db_path,
        embedding_service=service,
        async_embeddings=False,
    )
    seeded_l4 = L4ProceduralMemoryStore(
        db_path=db_path,
        embedding_service=service,
        async_embeddings=False,
    )
    await seeded_l3.initialize()
    await seeded_l4.initialize()
    try:
        await seeded_l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="insight",
                summary_category="topic",
                content="Travel planning preference.",
                source_event_ids=["evt-old"],
                insight_key="topic:seeded",
            )
        )
        assert await seeded_l4.record_task_preference(
            user_id="user:u1",
            task_category="travel",
            preference="Prefer quiet hotels",
        )
    finally:
        await seeded_l3.shutdown()
        await seeded_l4.shutdown()

    l3 = L3SummaryStore(db_path=db_path)
    l4 = L4ProceduralMemoryStore(db_path=db_path)
    await l3.initialize()
    await l4.initialize()
    try:
        assert l3._vector_index is not None and l3._vector_index._db is None
        assert l4._vector_index is not None and l4._vector_index._db is None
        assert await l3.clear() == 1
        assert await l4.clear() == 1
        assert l3._vector_index._db is None
        assert l4._vector_index._db is None
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM l3_summary_chunk_vectors"
            ) as cursor:
                assert await cursor.fetchone() == (0,)
            async with db.execute(
                "SELECT COUNT(*) FROM l4_skill_chunk_vectors"
            ) as cursor:
                assert await cursor.fetchone() == (0,)
    finally:
        await l3.shutdown()
        await l4.shutdown()


@pytest.mark.asyncio
async def test_l1_slow_embedding_crosses_clear_without_restoring_old_event(tmp_path) -> None:
    service = _BlockingNextEmbeddingService()
    store = L1EventStore(
        db_path=str(tmp_path / "l1.db"),
        embedding_service=service,
        async_embeddings=False,
    )
    barrier = AsyncOperationBarrier()
    store.set_operation_guard_factory(barrier.operation)
    await store.initialize()
    old_event = _user_message(event_id="evt-same", content="Travel preference.")
    try:
        await store.store(old_event)
        service.block_next = True
        stale_embedding = asyncio.create_task(
            store._maybe_upsert_event_embedding(old_event)
        )
        await asyncio.wait_for(service.started.wait(), timeout=2.0)

        async with barrier.exclusive():
            await store.abort_for_clear()
            assert await store.clear(restart_workers=False) == 1
        assert not stale_embedding.done()

        new_event = _user_message(event_id="evt-same", content="Coding preference.")
        await store.store(new_event)
        service.release.set()
        await asyncio.wait_for(stale_embedding, timeout=2.0)

        chunk_ids = await store._list_chunk_ids_for_event("evt-same")
        assert chunk_ids
        assert store._vector_index is not None
        vectors = await store._vector_index.get_vectors(entity_ids=chunk_ids)
        assert vectors[chunk_ids[0]] == pytest.approx([0.0, 1.0, 0.0])
    finally:
        service.release.set()
        await store.shutdown()


@pytest.mark.asyncio
async def test_l3_direct_upsert_model_phase_does_not_block_or_survive_clear(tmp_path) -> None:
    service = _BlockingNextEmbeddingService()
    service.block_next = True
    store = L3SummaryStore(
        db_path=str(tmp_path / "memory.db"),
        embedding_service=service,
        async_embeddings=False,
    )
    barrier = AsyncOperationBarrier()
    store.set_operation_guard_factory(barrier.operation)
    await store.initialize()
    try:
        pending = asyncio.create_task(
            store.upsert_candidate(
                candidate=L3Candidate(
                    summary_type="insight",
                    summary_category="topic",
                    content="Travel planning preference.",
                    source_event_ids=["evt-old"],
                    insight_key="topic:clear-race",
                )
            )
        )
        await asyncio.wait_for(service.started.wait(), timeout=2.0)

        async with barrier.exclusive():
            await store.abort_for_clear()
            assert await store.clear() == 1
        assert not pending.done()

        service.release.set()
        stale_summary = await asyncio.wait_for(pending, timeout=2.0)
        assert await store.count_summaries() == 0
        assert store._vector_index is not None
        assert await store._vector_index.get_vectors(
            entity_ids=[f"{stale_summary['summary_id']}::chunk-0"]
        ) == {}
    finally:
        service.release.set()
        await store.shutdown()


@pytest.mark.asyncio
async def test_l4_slow_embedding_crosses_clear_without_restoring_old_skill(tmp_path) -> None:
    service = _BlockingNextEmbeddingService()
    store = L4ProceduralMemoryStore(
        db_path=str(tmp_path / "memory.db"),
        embedding_service=service,
        async_embeddings=False,
    )
    barrier = AsyncOperationBarrier()
    store.set_operation_guard_factory(barrier.operation)
    await store.initialize()
    try:
        old_skill_id = await store.record_task_preference(
            user_id="user:u1",
            task_category="planning",
            preference="Keep plans explicit",
            evidence_text="travel",
        )
        assert old_skill_id is not None
        old_item = (await store.get_task_preferences(
            user_id="user:u1",
            task_category="planning",
            limit=1,
        ))[0]

        service.block_next = True
        stale_embedding = asyncio.create_task(
            store._maybe_upsert_skill_embedding(
                skill_id=old_skill_id,
                skill_name=str(old_item["skill_name"]),
                skill_category="task_preference",
                optimized_prompt=None,
            )
        )
        await asyncio.wait_for(service.started.wait(), timeout=2.0)

        async with barrier.exclusive():
            await store.abort_for_clear()
            assert await store.clear() == 1
        assert not stale_embedding.done()

        new_skill_id = await store.record_task_preference(
            user_id="user:u1",
            task_category="coding",
            preference="Keep changes tested",
            evidence_text="coding",
        )
        assert new_skill_id is not None
        service.release.set()
        await asyncio.wait_for(stale_embedding, timeout=2.0)

        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute(
                "SELECT chunk_id FROM l4_skill_chunks WHERE skill_id = ?",
                (new_skill_id,),
            ) as cursor:
                chunk_ids = [str(row[0]) for row in await cursor.fetchall()]
        assert chunk_ids
        assert store._vector_index is not None
        vectors = await store._vector_index.get_vectors(entity_ids=chunk_ids)
        assert vectors[chunk_ids[0]] == pytest.approx([0.0, 1.0, 0.0])
    finally:
        service.release.set()
        await store.shutdown()


@pytest.mark.asyncio
async def test_l4_late_old_embedding_cannot_overwrite_newer_skill_version(tmp_path) -> None:
    service = _BlockingNextEmbeddingService()
    store = L4ProceduralMemoryStore(
        db_path=str(tmp_path / "memory.db"),
        embedding_service=service,
        async_embeddings=False,
    )
    await store.initialize()
    try:
        skill_id = await store.record_task_preference(
            user_id="user:u1",
            task_category="planning",
            preference="Keep plans explicit",
            evidence_text="travel",
        )
        assert skill_id is not None
        old_item = (await store.get_task_preferences(
            user_id="user:u1",
            task_category="planning",
            limit=1,
        ))[0]

        service.block_next = True
        stale_embedding = asyncio.create_task(
            store._maybe_upsert_skill_embedding(
                skill_id=skill_id,
                skill_name=str(old_item["skill_name"]),
                skill_category="task_preference",
                optimized_prompt=None,
            )
        )
        await asyncio.wait_for(service.started.wait(), timeout=2.0)

        updated_skill_id = await store.record_task_preference(
            user_id="user:u1",
            task_category="planning",
            preference="Keep plans explicit",
            evidence_text="coding",
        )
        assert updated_skill_id == skill_id
        service.release.set()
        await asyncio.wait_for(stale_embedding, timeout=2.0)

        async with aiosqlite.connect(store.db_path) as db:
            async with db.execute(
                "SELECT chunk_id FROM l4_skill_chunks WHERE skill_id = ?",
                (skill_id,),
            ) as cursor:
                chunk_ids = [str(row[0]) for row in await cursor.fetchall()]
        assert chunk_ids
        assert store._vector_index is not None
        vectors = await store._vector_index.get_vectors(entity_ids=chunk_ids)
        assert vectors[chunk_ids[0]] == pytest.approx([0.0, 1.0, 0.0])
    finally:
        service.release.set()
        await store.shutdown()


@pytest.mark.asyncio
async def test_l2_edge_worker_finishes_active_drain_before_clear(tmp_path) -> None:
    barrier = AsyncOperationBarrier()
    active_entered = asyncio.Event()
    release_active = asyncio.Event()
    new_processed = asyncio.Event()
    writes: list[str] = []

    class Drainer:
        calls = 0

        async def drain_once(self, *, batch_limit: int) -> int:
            assert batch_limit == 1
            self.calls += 1
            if self.calls == 1:
                active_entered.set()
                await release_active.wait()
                writes.append("old")
                return 1
            writes.append("new")
            new_processed.set()
            return 0

    worker = L2EdgeEmbeddingWorker(
        drainer=Drainer(),  # type: ignore[arg-type]
        idle_interval_seconds=0.01,
        batch_limit=1,
    )
    worker.set_operation_guard_factory(barrier.operation)
    await worker.start()
    await asyncio.wait_for(active_entered.wait(), timeout=1)

    clear_entered = asyncio.Event()

    async def clear() -> None:
        async with barrier.exclusive():
            clear_entered.set()
            await worker.stop()
            writes.clear()

    clear_task = asyncio.create_task(clear())
    await asyncio.sleep(0)
    assert not clear_entered.is_set()
    release_active.set()
    await asyncio.wait_for(clear_task, timeout=1)
    assert writes == []

    await worker.start()
    await asyncio.wait_for(new_processed.wait(), timeout=1)
    assert writes == ["new"]
    await worker.stop()
