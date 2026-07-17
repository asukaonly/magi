from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from magi.memory.l2.batch_models import L2BatchJob
from magi.memory.l2.pipeline import L2Pipeline
from magi.memory.operation_barrier import AsyncOperationBarrier


class _CognitionStore:
    @asynccontextmanager
    async def memory_correction_job_guard(self):
        yield

    async def reconcile_entity(self, **_kwargs):
        return [SimpleNamespace(changed=True)]


@pytest.mark.asyncio
async def test_reconcile_callback_can_reenter_guard_while_clear_waits() -> None:
    barrier = AsyncOperationBarrier()
    callback_entered = asyncio.Event()
    release_callback = asyncio.Event()
    clear_entered = asyncio.Event()
    writes: list[str] = []

    async def state_change_callback(_entity_id, _entity_type, _outcomes) -> None:
        async with barrier.operation():
            callback_entered.set()
            await release_callback.wait()
            writes.append("insight")

    pipeline = L2Pipeline(
        _CognitionStore(),  # type: ignore[arg-type]
        entity_catalog=object(),  # type: ignore[arg-type]
        llm_service=object(),  # type: ignore[arg-type]
        state_change_callback=state_change_callback,
    )
    pipeline.set_operation_guard_factory(barrier.operation)

    async def evidence_timestamps(_entity_id: str) -> dict[str, float]:
        return {}

    pipeline._load_evidence_timestamps = evidence_timestamps  # type: ignore[method-assign]
    worker = asyncio.create_task(pipeline._run_reconcile_worker())
    await pipeline._reconcile_queue.put(["user:test"])
    await pipeline._reconcile_queue.put(None)
    await asyncio.wait_for(callback_entered.wait(), timeout=1)

    async def clear() -> None:
        async with barrier.exclusive():
            clear_entered.set()
            writes.clear()

    clear_task = asyncio.create_task(clear())
    await asyncio.sleep(0)
    assert not clear_entered.is_set()
    release_callback.set()
    await asyncio.wait_for(clear_task, timeout=1)
    await asyncio.wait_for(worker, timeout=1)

    assert writes == []


@pytest.mark.asyncio
async def test_pipeline_abort_drops_job_waiting_behind_clear() -> None:
    barrier = AsyncOperationBarrier()
    pipeline = L2Pipeline(
        _CognitionStore(),  # type: ignore[arg-type]
        entity_catalog=object(),  # type: ignore[arg-type]
        llm_service=object(),  # type: ignore[arg-type]
        batch_flush_interval_seconds=0,
    )
    pipeline.set_operation_guard_factory(barrier.operation)
    processed = asyncio.Event()

    async def process(_job) -> None:
        processed.set()

    pipeline._process_extract_job = process  # type: ignore[method-assign]
    await pipeline.start()
    job = L2BatchJob(
        job_id="old-job",
        bucket_key="old-bucket",
        events=[
            {
                "event_id": "event-old",
                "event_type": "USER_MESSAGE",
                "timestamp": 1.0,
            }
        ],
        flush_reason="test",
        estimated_tokens=0,
    )

    async with barrier.exclusive():
        await pipeline._extract_queue.put(job)
        await asyncio.sleep(0)
        await asyncio.wait_for(pipeline.abort_for_clear(), timeout=1)

    assert not processed.is_set()
    await pipeline.reset_after_clear()
    assert pipeline._extract_queue.empty()


@pytest.mark.asyncio
async def test_pipeline_reset_discards_resolution_cache_and_session_state() -> None:
    pipeline = L2Pipeline(None)
    pipeline._entity_catalog = object()  # type: ignore[assignment]
    pipeline._entity_resolution_cache[("private", "person")] = (
        "person:old",
        0.99,
    )
    pipeline._session_touched_entities["session-old"] = {"person:old"}
    pipeline._stats.extract_completed = 3
    await pipeline._extract_queue.put(
        L2BatchJob(
            job_id="old-job",
            bucket_key="old-bucket",
            events=[
                {
                    "event_id": "event-old",
                    "event_type": "USER_MESSAGE",
                    "timestamp": 1.0,
                }
            ],
            flush_reason="test",
            estimated_tokens=0,
        )
    )

    await pipeline.reset_after_clear()
    uncached_calls = 0

    async def resolve_uncached(**_kwargs):
        nonlocal uncached_calls
        uncached_calls += 1
        return ("person:new", 0.8)

    pipeline._resolve_entity_id_uncached = resolve_uncached  # type: ignore[method-assign]
    result = await pipeline._resolve_entity_id(
        mention={},
        entity_type="person",
        mention_text="private",
        mention_confidence=0.8,
        event=SimpleNamespace(content="", source="test"),
        source_event_ids=["event-new"],
    )

    assert result == ("person:new", 0.8)
    assert uncached_calls == 1
    assert pipeline._session_touched_entities == {}
    assert pipeline._stats.extract_completed == 0
    assert pipeline._extract_queue.empty()
