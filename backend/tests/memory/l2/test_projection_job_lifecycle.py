from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import AsyncIterator

import pytest

from magi.memory.l2.models import L2BatchJob, L2ProjectionLease
from magi.memory.l2.pipeline import L2Pipeline


class _RecordingCognitionStore:
    def __init__(self) -> None:
        self.recovered_count = 0
        self.recovery_calls: list[str] = []
        self.running_calls: list[tuple[list[str], str]] = []
        self.heartbeat_calls: list[list[str]] = []
        self.completed_calls: list[list[str]] = []
        self.failed_calls: list[tuple[list[str], str | None, bool]] = []
        self.heartbeat_event = asyncio.Event()
        self.call_order: list[str] = []

    @asynccontextmanager
    async def memory_correction_job_guard(self) -> AsyncIterator[None]:
        yield

    async def recover_foreign_projection_jobs(self, *, consumer_name: str) -> int:
        self.recovery_calls.append(consumer_name)
        self.call_order.append("recover")
        return self.recovered_count

    async def mark_projection_jobs_running(self, leases, *, consumer_name: str) -> int:  # type: ignore[no-untyped-def]
        event_ids = [lease.event_id for lease in leases]
        self.running_calls.append((event_ids, consumer_name))
        self.call_order.append("running")
        return len(event_ids)

    async def touch_running_projection_jobs(self, leases):  # type: ignore[no-untyped-def]
        event_ids = [lease.event_id for lease in leases]
        self.heartbeat_calls.append(event_ids)
        self.call_order.append("heartbeat")
        self.heartbeat_event.set()
        return len(event_ids)

    async def complete_projection_jobs(self, leases):  # type: ignore[no-untyped-def]
        event_ids = [lease.event_id for lease in leases]
        self.completed_calls.append(event_ids)
        self.call_order.append("complete")
        return len(event_ids)

    async def fail_projection_jobs(self, leases, *, error_text: str | None = None, requeue: bool):  # type: ignore[no-untyped-def]
        event_ids = [lease.event_id for lease in leases]
        self.failed_calls.append((event_ids, error_text, requeue))
        return len(event_ids)


def _lease(event_id: str) -> L2ProjectionLease:
    return L2ProjectionLease(event_id=event_id, lease_token=f"lease:{event_id}", attempt_count=1)


def _result(*, skipped: bool = True) -> dict[str, object]:
    return {
        "relation_count": 0,
        "assertion_count": 0,
        "touched_entity_ids": [],
        "snapshot_refresh_entity_ids": [],
        "skipped": skipped,
    }


def _job(*event_ids: str) -> L2BatchJob:
    return L2BatchJob(
        job_id=f"projection:{'-'.join(event_ids)}",
        bucket_key="owner:test",
        events=[
            {
                "event_id": event_id,
                "content": "hello",
                "timestamp": 1710000000.0,
            }
            for event_id in event_ids
        ],
        flush_reason="projection_ready",
        estimated_tokens=max(len(event_ids), 1),
        session_id=None,
        user_id=None,
        projection_leases=[_lease(event_id) for event_id in event_ids],
    )


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
        projection_leases=[_lease("evt-proj-1")],
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

    async def mark_projection_jobs_running(self, leases, *, consumer_name: str) -> int:  # type: ignore[no-untyped-def]
        ids = [lease.event_id for lease in leases]
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
        projection_leases=[_lease("evt-zombie-1")],
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
        projection_leases=[_lease("evt-invalid-json")],
    )

    await pipeline._extract_queue.put(job)
    await pipeline._extract_queue.put(None)
    await pipeline._run_extract_worker()

    assert cognition_store.completed_calls == []
    assert cognition_store.failed_calls == [(["evt-invalid-json"], "invalid model response", False)]
    assert pipeline._stats.extract_failed == 1


@pytest.mark.asyncio
async def test_pipeline_start_recovers_foreign_attempts_before_workers() -> None:
    cognition_store = _RecordingCognitionStore()
    cognition_store.recovered_count = 2
    pipeline = L2Pipeline(
        cognition_store=cognition_store,
        l1_store=SimpleNamespace(),
        entity_catalog=SimpleNamespace(),
        llm_service=SimpleNamespace(),
    )

    await pipeline.start()
    try:
        assert cognition_store.recovery_calls == [pipeline._projection_consumer_name]
        assert cognition_store.call_order == ["recover"]
        assert pipeline._stats.is_running is True
        assert len(pipeline._extract_workers) == pipeline._extract_worker_count
    finally:
        await pipeline.abort_for_clear()


class _DelayedRecoveryCognitionStore(_RecordingCognitionStore):
    def __init__(self) -> None:
        super().__init__()
        self.recovery_entered = asyncio.Event()
        self.release_recovery = asyncio.Event()

    async def recover_foreign_projection_jobs(self, *, consumer_name: str) -> int:
        self.recovery_calls.append(consumer_name)
        self.call_order.append("recover")
        self.recovery_entered.set()
        await self.release_recovery.wait()
        return 0


@pytest.mark.asyncio
async def test_abort_during_startup_recovery_does_not_spawn_workers() -> None:
    cognition_store = _DelayedRecoveryCognitionStore()
    pipeline = L2Pipeline(
        cognition_store=cognition_store,
        l1_store=SimpleNamespace(),
        entity_catalog=SimpleNamespace(),
        llm_service=SimpleNamespace(),
    )

    start_task = asyncio.create_task(pipeline.start())
    await asyncio.wait_for(cognition_store.recovery_entered.wait(), timeout=1)
    await pipeline.abort_for_clear()
    cognition_store.release_recovery.set()
    await asyncio.wait_for(start_task, timeout=1)

    assert pipeline._stats.is_running is False
    assert pipeline._extract_workers == []
    assert pipeline._flush_worker is None
    assert pipeline._reconcile_worker is None
    assert pipeline._snapshot_worker is None


class _PartialStartCognitionStore(_RecordingCognitionStore):
    async def mark_projection_jobs_running(self, leases, *, consumer_name: str) -> int:  # type: ignore[no-untyped-def]
        event_ids = [lease.event_id for lease in leases]
        self.running_calls.append((event_ids, consumer_name))
        self.call_order.append("running")
        return max(len(event_ids) - 1, 0)


@pytest.mark.asyncio
async def test_extract_worker_rejects_a_partial_running_transition() -> None:
    cognition_store = _PartialStartCognitionStore()
    pipeline = L2Pipeline(
        cognition_store=cognition_store,
        l1_store=SimpleNamespace(),
        entity_catalog=SimpleNamespace(),
        llm_service=SimpleNamespace(),
    )
    extract_called = False

    async def _fake_extract_and_persist(job: L2BatchJob):  # type: ignore[no-untyped-def]
        nonlocal extract_called
        _ = job
        extract_called = True
        return _result()

    pipeline._extract_and_persist = _fake_extract_and_persist  # type: ignore[method-assign]
    await pipeline._process_extract_job(_job("event-a", "event-b"))

    assert extract_called is False
    assert cognition_store.completed_calls == []
    assert cognition_store.failed_calls == []
    assert pipeline._stats.extract_skipped == 1


@pytest.mark.asyncio
async def test_long_extraction_renews_projection_lease_until_completion() -> None:
    cognition_store = _RecordingCognitionStore()
    pipeline = L2Pipeline(
        cognition_store=cognition_store,
        l1_store=SimpleNamespace(),
        entity_catalog=SimpleNamespace(),
        llm_service=SimpleNamespace(),
    )
    pipeline._projection_heartbeat_interval_seconds = 0.001

    async def _fake_extract_and_persist(job: L2BatchJob):  # type: ignore[no-untyped-def]
        _ = job
        await asyncio.wait_for(cognition_store.heartbeat_event.wait(), timeout=1)
        return _result()

    pipeline._extract_and_persist = _fake_extract_and_persist  # type: ignore[method-assign]
    await pipeline._process_extract_job(_job("event-heartbeat"))

    assert cognition_store.heartbeat_calls == [["event-heartbeat"]]
    assert cognition_store.completed_calls == [["event-heartbeat"]]
    assert cognition_store.failed_calls == []
    assert pipeline._stats.extract_completed == 1


class _LostLeaseCognitionStore(_RecordingCognitionStore):
    async def touch_running_projection_jobs(self, leases):  # type: ignore[no-untyped-def]
        event_ids = [lease.event_id for lease in leases]
        self.heartbeat_calls.append(event_ids)
        self.call_order.append("heartbeat")
        self.heartbeat_event.set()
        return 0


@pytest.mark.asyncio
async def test_lost_heartbeat_fences_completion_and_fails_the_attempt() -> None:
    cognition_store = _LostLeaseCognitionStore()
    pipeline = L2Pipeline(
        cognition_store=cognition_store,
        l1_store=SimpleNamespace(),
        entity_catalog=SimpleNamespace(),
        llm_service=SimpleNamespace(),
    )
    pipeline._projection_heartbeat_interval_seconds = 0.001

    async def _fake_extract_and_persist(job: L2BatchJob):  # type: ignore[no-untyped-def]
        _ = job
        await asyncio.wait_for(cognition_store.heartbeat_event.wait(), timeout=1)
        return _result()

    pipeline._extract_and_persist = _fake_extract_and_persist  # type: ignore[method-assign]
    await pipeline._process_extract_job(_job("event-lost"))

    assert cognition_store.completed_calls == []
    assert len(cognition_store.failed_calls) == 1
    failed_ids, error_text, requeue = cognition_store.failed_calls[0]
    assert failed_ids == ["event-lost"]
    assert error_text == "projection_attempt_fenced_during_extraction"
    assert requeue is True
    assert pipeline._stats.extract_completed == 0
    assert pipeline._stats.extract_failed == 1


@pytest.mark.asyncio
async def test_extract_finish_precedes_durable_completion() -> None:
    cognition_store = _RecordingCognitionStore()
    pipeline = L2Pipeline(
        cognition_store=cognition_store,
        l1_store=SimpleNamespace(),
        entity_catalog=SimpleNamespace(),
        llm_service=SimpleNamespace(),
    )

    async def _fake_extract_and_persist(job: L2BatchJob):  # type: ignore[no-untyped-def]
        _ = job
        return _result()

    async def _fake_finish_extract_job(
        job: L2BatchJob,
        result: dict[str, object],
    ) -> None:
        _ = job, result
        cognition_store.call_order.append("finish")

    pipeline._extract_and_persist = _fake_extract_and_persist  # type: ignore[method-assign]
    pipeline._finish_extract_job = _fake_finish_extract_job  # type: ignore[method-assign]
    await pipeline._process_extract_job(_job("event-order"))

    assert cognition_store.call_order == ["running", "finish", "complete"]
    assert pipeline._stats.extract_completed == 1


@pytest.mark.asyncio
async def test_extract_finish_failure_keeps_projection_attempt_retryable() -> None:
    cognition_store = _RecordingCognitionStore()
    pipeline = L2Pipeline(
        cognition_store=cognition_store,
        l1_store=SimpleNamespace(),
        entity_catalog=SimpleNamespace(),
        llm_service=SimpleNamespace(),
    )

    async def _fake_extract_and_persist(job: L2BatchJob):  # type: ignore[no-untyped-def]
        _ = job
        return _result()

    async def _fail_finish_extract_job(
        job: L2BatchJob,
        result: dict[str, object],
    ) -> None:
        _ = job, result
        cognition_store.call_order.append("finish")
        raise RuntimeError("finish failed")

    pipeline._extract_and_persist = _fake_extract_and_persist  # type: ignore[method-assign]
    pipeline._finish_extract_job = _fail_finish_extract_job  # type: ignore[method-assign]
    await pipeline._process_extract_job(_job("event-finish-failed"))

    assert cognition_store.completed_calls == []
    assert cognition_store.failed_calls == [(["event-finish-failed"], "finish failed", True)]
    assert cognition_store.call_order == ["running", "finish"]
    assert pipeline._stats.extract_completed == 0
    assert pipeline._stats.extract_failed == 1


@pytest.mark.asyncio
async def test_invalid_completion_metrics_fail_before_durable_completion() -> None:
    cognition_store = _RecordingCognitionStore()
    pipeline = L2Pipeline(
        cognition_store=cognition_store,
        l1_store=SimpleNamespace(),
        entity_catalog=SimpleNamespace(),
        llm_service=SimpleNamespace(),
    )

    async def _fake_extract_and_persist(job: L2BatchJob):  # type: ignore[no-untyped-def]
        _ = job
        return {**_result(), "relation_count": "not-a-count"}

    pipeline._extract_and_persist = _fake_extract_and_persist  # type: ignore[method-assign]
    await pipeline._process_extract_job(_job("event-invalid-metrics"))

    assert cognition_store.completed_calls == []
    assert cognition_store.failed_calls == [
        (["event-invalid-metrics"], "L2 extraction result has an invalid relation_count", True)
    ]
    assert pipeline._stats.extract_completed == 0
    assert pipeline._stats.extract_failed == 1
