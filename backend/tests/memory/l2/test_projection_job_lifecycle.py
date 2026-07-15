from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import AsyncIterator

import pytest

from magi.memory.l2.models import L2BatchJob
from magi.memory.l2.pipeline import L2Pipeline


class _RecordingCognitionStore:
    def __init__(self) -> None:
        self.running_calls: list[tuple[list[str], str]] = []
        self.completed_calls: list[list[str]] = []
        self.failed_calls: list[tuple[list[str], str | None, bool]] = []

    @asynccontextmanager
    async def memory_correction_job_guard(self) -> AsyncIterator[None]:
        yield

    async def mark_projection_jobs_running(self, event_ids, *, consumer_name: str) -> int:  # type: ignore[no-untyped-def]
        ids = list(event_ids)
        self.running_calls.append((ids, consumer_name))
        return len(ids)

    async def complete_projection_jobs(self, event_ids):  # type: ignore[no-untyped-def]
        self.completed_calls.append(list(event_ids))
        return len(event_ids)

    async def fail_projection_jobs(self, event_ids, *, error_text: str | None = None, requeue: bool):  # type: ignore[no-untyped-def]
        self.failed_calls.append((list(event_ids), error_text, requeue))
        return len(event_ids)


@pytest.mark.asyncio
async def test_extract_worker_marks_projection_jobs_running_before_completion():
    cognition_store = _RecordingCognitionStore()
    pipeline = L2Pipeline(
        cognition_store=cognition_store,
        l1_store=SimpleNamespace(),
        entity_catalog=SimpleNamespace(),
        llm_service=SimpleNamespace(),
    )

    recorded_job_ids: list[str] = []

    async def _fake_extract_and_persist(job: L2BatchJob):  # type: ignore[no-untyped-def]
        recorded_job_ids.append(job.job_id)
        return {
            "relation_count": 0,
            "assertion_count": 0,
            "touched_entity_ids": [],
            "snapshot_refresh_entity_ids": [],
        }

    pipeline._extract_and_persist = _fake_extract_and_persist  # type: ignore[method-assign]

    job = L2BatchJob(
        job_id="projection:test-job",
        bucket_key="owner:test",
        events=[{"event_id": "evt-proj-1", "content": "hello", "timestamp": 1710000000.0}],
        flush_reason="projection_ready",
        estimated_tokens=4,
        session_id=None,
        user_id=None,
    )

    await pipeline._extract_queue.put(job)
    await pipeline._extract_queue.put(None)

    await pipeline._run_extract_worker()

    assert recorded_job_ids == ["projection:test-job"]
    assert cognition_store.running_calls == [
        (["evt-proj-1"], pipeline._projection_consumer_name),
    ]
    assert cognition_store.completed_calls == [["evt-proj-1"]]
    assert cognition_store.failed_calls == []


class _ZombieSkipCognitionStore(_RecordingCognitionStore):
    """Returns 0 from mark_projection_jobs_running to simulate a stale batch."""

    async def mark_projection_jobs_running(self, event_ids, *, consumer_name: str) -> int:  # type: ignore[no-untyped-def]
        ids = list(event_ids)
        self.running_calls.append((ids, consumer_name))
        return 0  # Simulates all events already completed/not-queued


@pytest.mark.asyncio
async def test_extract_worker_skips_stale_batch_when_no_rows_transitioned():
    """Worker must skip extraction when mark_projection_jobs_running returns 0."""
    cognition_store = _ZombieSkipCognitionStore()
    pipeline = L2Pipeline(
        cognition_store=cognition_store,
        l1_store=SimpleNamespace(),
        entity_catalog=SimpleNamespace(),
        llm_service=SimpleNamespace(),
    )

    extract_called = False

    async def _fake_extract_and_persist(job: L2BatchJob):  # type: ignore[no-untyped-def]
        nonlocal extract_called
        extract_called = True
        return {"relation_count": 0, "assertion_count": 0}

    pipeline._extract_and_persist = _fake_extract_and_persist  # type: ignore[method-assign]

    job = L2BatchJob(
        job_id="projection:zombie-job",
        bucket_key="owner:zombie",
        events=[{"event_id": "evt-zombie-1", "content": "hi", "timestamp": 1710000000.0}],
        flush_reason="projection_ready",
        estimated_tokens=2,
        session_id=None,
        user_id=None,
    )

    await pipeline._extract_queue.put(job)
    await pipeline._extract_queue.put(None)

    await pipeline._run_extract_worker()

    assert extract_called is False, "Extraction must be skipped for stale batch"
    assert cognition_store.running_calls == [
        (["evt-zombie-1"], pipeline._projection_consumer_name),
    ]
    assert cognition_store.completed_calls == []
    assert cognition_store.failed_calls == []
    assert pipeline._stats.extract_skipped == 1


@pytest.mark.asyncio
async def test_extract_worker_fails_invalid_model_output_instead_of_looping():
    from magi.memory.l2.llm_json_client import L2InvalidJsonResponseError

    cognition_store = _RecordingCognitionStore()
    pipeline = L2Pipeline(
        cognition_store=cognition_store,
        l1_store=SimpleNamespace(),
        entity_catalog=SimpleNamespace(),
        llm_service=SimpleNamespace(),
    )

    async def _fake_extract_and_persist(job: L2BatchJob):  # type: ignore[no-untyped-def]
        _ = job
        raise L2InvalidJsonResponseError("invalid model response")

    pipeline._extract_and_persist = _fake_extract_and_persist  # type: ignore[method-assign]
    job = L2BatchJob(
        job_id="projection:invalid-json",
        bucket_key="owner:test",
        events=[{"event_id": "evt-invalid-json", "content": "hello", "timestamp": 1.0}],
        flush_reason="projection_ready",
        estimated_tokens=2,
        session_id=None,
        user_id=None,
    )

    await pipeline._extract_queue.put(job)
    await pipeline._extract_queue.put(None)
    await pipeline._run_extract_worker()

    assert cognition_store.completed_calls == []
    assert cognition_store.failed_calls == [
        (["evt-invalid-json"], "invalid model response", False)
    ]
    assert pipeline._stats.extract_failed == 1
