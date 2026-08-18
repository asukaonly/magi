from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from magi.memory.operation_barrier import AsyncOperationBarrier
from magi.memory.store_ingestion import MemoryIngestionMixin
from magi.memory.store_l2_operations import UnifiedMemoryL2OperationsMixin
from magi.memory.store_lifecycle import UnifiedMemoryLifecycleMixin


class _RuntimeReplacementHost(UnifiedMemoryLifecycleMixin):
    def __init__(self, *, quiesce_error: BaseException | None = None) -> None:
        self._clear_barrier = AsyncOperationBarrier()
        self._write_lock = asyncio.Lock()
        self._clear_epoch = 0
        self._clear_request_count = 0
        self._quiesce_error = quiesce_error
        self.quiesced = asyncio.Event()
        self.resume_calls: list[dict[str, bool]] = []
        self.l0 = None
        self.l1 = None
        self.l2 = None
        self.l2_entity_catalog = None
        self.l2_pipeline = None
        self.l3 = None
        self.l4 = None
        self._edge_embedding_worker = None
        self._portrait_projection_scheduler = None

    async def _quiesce_memory_writers(self) -> None:
        self.quiesced.set()
        if self._quiesce_error is not None:
            raise self._quiesce_error

    async def _resume_memory_writers(self, **state: bool) -> None:
        self.resume_calls.append(state)


@pytest.mark.asyncio
async def test_exclusive_waiter_blocks_new_operations_until_clear_finishes() -> None:
    barrier = AsyncOperationBarrier()
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    clear_entered = asyncio.Event()
    release_clear = asyncio.Event()
    second_entered = asyncio.Event()
    order: list[str] = []

    async def first_operation() -> None:
        async with barrier.operation():
            order.append("first")
            first_entered.set()
            await release_first.wait()

    async def clear() -> None:
        async with barrier.exclusive():
            order.append("clear")
            clear_entered.set()
            await release_clear.wait()

    async def second_operation() -> None:
        async with barrier.operation():
            order.append("second")
            second_entered.set()

    first_task = asyncio.create_task(first_operation())
    await first_entered.wait()
    clear_task = asyncio.create_task(clear())
    await asyncio.sleep(0)
    second_task = asyncio.create_task(second_operation())
    await asyncio.sleep(0)

    assert not clear_entered.is_set()
    assert not second_entered.is_set()

    release_first.set()
    await clear_entered.wait()
    assert not second_entered.is_set()

    release_clear.set()
    await asyncio.gather(first_task, clear_task, second_task)
    assert order == ["first", "clear", "second"]


@pytest.mark.asyncio
async def test_operation_is_reentrant_while_exclusive_waits() -> None:
    barrier = AsyncOperationBarrier()
    outer_entered = asyncio.Event()
    allow_nested = asyncio.Event()
    nested_entered = asyncio.Event()
    release_nested = asyncio.Event()
    clear_entered = asyncio.Event()

    async def operation() -> None:
        async with barrier.operation():
            outer_entered.set()
            await allow_nested.wait()
            async with barrier.operation():
                nested_entered.set()
                await release_nested.wait()

    async def clear() -> None:
        async with barrier.exclusive():
            clear_entered.set()

    operation_task = asyncio.create_task(operation())
    await outer_entered.wait()
    clear_task = asyncio.create_task(clear())
    for _ in range(20):
        if barrier._exclusive_waiters:
            break
        await asyncio.sleep(0)
    assert barrier._exclusive_waiters == 1
    allow_nested.set()

    await asyncio.wait_for(nested_entered.wait(), timeout=1)
    assert not clear_entered.is_set()
    release_nested.set()
    await asyncio.gather(operation_task, clear_task)
    assert clear_entered.is_set()


@pytest.mark.asyncio
async def test_cancelled_exclusive_waiter_releases_new_operations() -> None:
    barrier = AsyncOperationBarrier()
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first_operation() -> None:
        async with barrier.operation():
            first_entered.set()
            await release_first.wait()

    async def wait_for_clear() -> None:
        async with barrier.exclusive():
            raise AssertionError("cancelled clear must not enter")

    async def second_operation() -> None:
        async with barrier.operation():
            second_entered.set()

    first_task = asyncio.create_task(first_operation())
    await first_entered.wait()
    clear_task = asyncio.create_task(wait_for_clear())
    await asyncio.sleep(0)
    second_task = asyncio.create_task(second_operation())
    await asyncio.sleep(0)
    assert not second_entered.is_set()

    clear_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await clear_task
    await asyncio.wait_for(second_entered.wait(), timeout=1)

    release_first.set()
    await asyncio.gather(first_task, second_task)


@pytest.mark.asyncio
async def test_runtime_replacement_drains_operations_and_does_not_resume_old_writers() -> None:
    host = _RuntimeReplacementHost()
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    replacement_entered = asyncio.Event()
    release_replacement = asyncio.Event()
    second_entered = asyncio.Event()

    async def first_operation() -> None:
        async with host.memory_operation_guard():
            first_entered.set()
            await release_first.wait()

    async def replace_runtime() -> None:
        async with host.memory_runtime_replacement_guard():
            replacement_entered.set()
            await release_replacement.wait()

    async def second_operation() -> None:
        async with host.memory_operation_guard():
            second_entered.set()

    first_task = asyncio.create_task(first_operation())
    await first_entered.wait()
    replacement_task = asyncio.create_task(replace_runtime())
    for _ in range(20):
        if host._clear_barrier._exclusive_waiters:
            break
        await asyncio.sleep(0)
    second_task = asyncio.create_task(second_operation())
    await asyncio.sleep(0)

    assert not replacement_entered.is_set()
    assert not second_entered.is_set()
    release_first.set()
    await replacement_entered.wait()
    assert host.quiesced.is_set()
    assert host.memory_operation_epoch() == 1
    assert host.memory_clear_in_progress() is True
    assert not second_entered.is_set()

    release_replacement.set()
    await asyncio.gather(first_task, replacement_task, second_task)
    assert host.resume_calls == []
    assert host.memory_clear_in_progress() is False
    assert second_entered.is_set()


@pytest.mark.asyncio
async def test_runtime_replacement_resumes_writers_when_quiesce_fails() -> None:
    host = _RuntimeReplacementHost(quiesce_error=RuntimeError("stop failed"))

    with pytest.raises(RuntimeError, match="stop failed"):
        async with host.memory_runtime_replacement_guard():
            raise AssertionError("replacement must not start")

    assert len(host.resume_calls) == 1
    assert host.memory_clear_in_progress() is False


async def _start_clear_behind_active_operation(
    barrier: AsyncOperationBarrier,
    advance_epoch,
) -> tuple[asyncio.Task[None], asyncio.Event]:
    release_blocker = asyncio.Event()
    blocker_entered = asyncio.Event()

    async def blocker() -> None:
        async with barrier.operation():
            blocker_entered.set()
            await release_blocker.wait()

    async def clear() -> None:
        async with barrier.exclusive():
            advance_epoch()

    blocker_task = asyncio.create_task(blocker())
    await blocker_entered.wait()
    clear_task = asyncio.create_task(clear())
    for _ in range(20):
        if barrier._exclusive_waiters:
            break
        await asyncio.sleep(0)
    assert barrier._exclusive_waiters == 1

    async def finish() -> None:
        release_blocker.set()
        await blocker_task
        await clear_task

    return asyncio.create_task(finish()), release_blocker


@pytest.mark.asyncio
async def test_direct_ingest_captures_epoch_before_waiting_for_clear() -> None:
    class IngestionHost(MemoryIngestionMixin):
        def __init__(self) -> None:
            self._clear_barrier = AsyncOperationBarrier()
            self._clear_epoch = 0
            self.written: list[str] = []

        def _normalize_event(self, event):
            return event

        async def _ingest_memory_event(self, event):
            self.written.append(event.event_id)
            return {"event_id": event.event_id}

    host = IngestionHost()
    event = SimpleNamespace(
        event_id="old",
        ingest_target=SimpleNamespace(label="l1_only"),
    )
    clear_task, release_blocker = await _start_clear_behind_active_operation(
        host._clear_barrier,
        lambda: setattr(host, "_clear_epoch", host._clear_epoch + 1),
    )
    ingest_task = asyncio.create_task(host.ingest_event(event))
    await asyncio.sleep(0)
    release_blocker.set()
    await asyncio.gather(clear_task, ingest_task)

    assert host.written == []
    assert (await ingest_task)["skip_reason"] == "memory_clear_epoch_changed"

    await host.ingest_event(
        SimpleNamespace(
            event_id="new",
            ingest_target=SimpleNamespace(label="l1_only"),
        )
    )
    assert host.written == ["new"]


@pytest.mark.asyncio
async def test_direct_graph_upsert_captures_epoch_before_waiting_for_clear() -> None:
    class L2Store:
        def __init__(self) -> None:
            self.written: list[str] = []

        async def upsert_knowledge_edges(self, edges):
            self.written.extend(str(edge["object_id"]) for edge in edges)
            return [str(edge["object_id"]) for edge in edges]

    class GraphHost(UnifiedMemoryL2OperationsMixin):
        def __init__(self) -> None:
            self._barrier = AsyncOperationBarrier()
            self._clear_epoch = 0
            self.l2 = L2Store()

        def memory_operation_guard(self):
            return self._barrier.operation()

        def memory_operation_epoch(self) -> int:
            return self._clear_epoch

    host = GraphHost()
    edge = {
        "subject_id": "user:self",
        "subject_type": "user",
        "predicate": "VIEWED",
        "object_id": "site:old",
        "object_type": "web_page",
        "evidence_event_ids": ["event-old"],
        "confidence": 0.8,
        "observed_at": 1.0,
        "source_type": "test",
    }
    clear_task, release_blocker = await _start_clear_behind_active_operation(
        host._barrier,
        lambda: setattr(host, "_clear_epoch", host._clear_epoch + 1),
    )
    write_task = asyncio.create_task(host.upsert_user_graph_edges([edge]))
    await asyncio.sleep(0)
    release_blocker.set()
    await asyncio.gather(clear_task, write_task)
    assert await write_task == []
    assert host.l2.written == []

    new_edge = {**edge, "object_id": "site:new", "evidence_event_ids": ["event-new"]}
    assert await host.upsert_user_graph_edges([new_edge]) == ["site:new"]
    assert host.l2.written == ["site:new"]
