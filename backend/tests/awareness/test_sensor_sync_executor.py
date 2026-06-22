from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest

from magi.awareness.sensor_sync_executor import SensorSyncExecutor
from magi.scheduler import (
    ScheduleDefinition,
    ScheduledExecutionResult,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)
from magi.scheduler.repository import ScheduleRepository


def _build_sensor_schedule() -> ScheduleDefinition:
    return ScheduleDefinition(
        schedule_id="sensor-sync:test-plugin:test-source",
        target_type=ScheduledTargetType.SENSOR_SYNC,
        target_key="test-plugin:test-source",
        trigger=TriggerDefinition(
            trigger_type=TriggerType.INTERVAL,
            config={"seconds": 300.0},
        ),
        target_payload={
            "plugin_id": "test-plugin",
            "source_type": "test-source",
            "manual": False,
        },
        metadata={"plugin_id": "test-plugin", "source_type": "test-source"},
    )


async def _enqueue_job(repository: ScheduleRepository, schedule: ScheduleDefinition) -> str:
    await repository.upsert_schedule(schedule)
    acquired = await repository.acquire_target_lock(schedule.target_type, schedule.target_key)
    assert acquired is True
    execution_id = await repository.create_execution_record(
        schedule_id=schedule.schedule_id,
        target_type=schedule.target_type,
        target_key=schedule.target_key,
        manual=False,
        started_at=time.time(),
    )
    job_id = await repository.enqueue_sensor_sync_job(
        schedule=schedule,
        execution_id=execution_id,
        manual=False,
    )
    assert job_id is not None
    return job_id


async def _wait_for_job_status(
    repository: ScheduleRepository,
    job_id: str,
    expected_status: str,
    *,
    timeout_seconds: float = 2.0,
) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        job = await repository.get_sensor_sync_job(job_id)
        if job is not None and job["status"] == expected_status:
            return job
        await asyncio.sleep(0.02)
    raise AssertionError(f"Timed out waiting for sensor sync job {job_id} to reach {expected_status}")


def _load_execution_status(db_path, execution_id: str) -> tuple[str, str | None]:
    connection = sqlite3.connect(str(db_path))
    row = connection.execute(
        """
        SELECT status, result_message
        FROM schedule_executions
        WHERE execution_id = ?
        """,
        (execution_id,),
    ).fetchone()
    connection.close()
    assert row is not None
    return str(row[0]), str(row[1]) if row[1] is not None else None


@pytest.mark.asyncio
async def test_sensor_sync_executor_claims_and_completes_queued_job(tmp_path):
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule()
    job_id = await _enqueue_job(repository, schedule)
    job = await repository.get_sensor_sync_job(job_id)
    assert job is not None
    execution_id = str(job["execution_id"])

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        assert job_record["job_id"] == job_id
        return ScheduledExecutionResult(
            success=True,
            message="sensor_sync_completed",
            next_cursor="cursor-2",
            watermark_ts=321.0,
            stats={"items": 1},
        )

    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        poll_interval_seconds=0.01,
        running_timeout_seconds=30.0,
    )
    await executor.start()
    completed_job = await _wait_for_job_status(repository, job_id, "success")
    await executor.stop()

    target_state = await repository.get_target_state(schedule.target_type, schedule.target_key)
    execution_status, execution_message = _load_execution_status(db_path, execution_id)

    assert completed_job["result_message"] == "sensor_sync_completed"
    assert completed_job["next_cursor"] == "cursor-2"
    assert completed_job["watermark_ts"] == 321.0
    assert target_state.running is False
    assert target_state.last_cursor == "cursor-2"
    assert target_state.watermark_ts == 321.0
    assert execution_status == "success"
    assert execution_message == "sensor_sync_completed"


@pytest.mark.asyncio
async def test_sensor_sync_executor_runs_jobs_on_owner_loop(tmp_path):
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule()
    job_id = await _enqueue_job(repository, schedule)
    owner_loop = asyncio.get_running_loop()
    observed_loop_ids: list[int] = []

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        assert job_record["job_id"] == job_id
        observed_loop_ids.append(id(asyncio.get_running_loop()))
        return ScheduledExecutionResult(success=True, message="sensor_sync_completed")

    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        poll_interval_seconds=0.01,
        running_timeout_seconds=30.0,
    )
    await executor.start()
    await _wait_for_job_status(repository, job_id, "success")
    await executor.stop()

    assert observed_loop_ids == [id(owner_loop)]


@pytest.mark.asyncio
async def test_sensor_sync_success_triggers_l3_backfill(tmp_path, monkeypatch):
    """After a successful sync, the executor best-effort backfills L3 over the
    synced source's L1 event window (min/max timestamp from summarize_event_sources)."""
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule()
    job_id = await _enqueue_job(repository, schedule)

    backfill_calls: list[dict[str, object]] = []
    summarize_calls: list[dict[str, object]] = []

    async def _fake_backfill(**kwargs):
        backfill_calls.append(kwargs)
        return {"generated": [], "skipped_existing": 0, "skipped_sparse": 0}

    async def _fake_summarize_event_sources(**kwargs):
        summarize_calls.append(kwargs)
        return [
            {
                "source": "test-source",
                "event_count": 5,
                "avg_importance": 0.5,
                "min_timestamp": 1000.0,
                "max_timestamp": 2000.0,
            }
        ]

    class _FakeL1:
        summarize_event_sources = staticmethod(_fake_summarize_event_sources)

    class _FakeUnifiedMemory:
        l1 = _FakeL1()
        backfill_l3_gaps = staticmethod(_fake_backfill)

    fake_um = _FakeUnifiedMemory()
    monkeypatch.setattr(
        "magi.memory.provider.get_unified_memory",
        lambda: fake_um,
    )

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        assert job_record["job_id"] == job_id
        return ScheduledExecutionResult(success=True, message="sensor_sync_completed")

    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        poll_interval_seconds=0.01,
        running_timeout_seconds=30.0,
    )
    await executor.start()
    await _wait_for_job_status(repository, job_id, "success")
    # Backfill is fired after the success commit; give the executor loop a beat.
    deadline = time.time() + 2.0
    while time.time() < deadline and not backfill_calls:
        await asyncio.sleep(0.02)
    await executor.stop()

    assert summarize_calls, "summarize_event_sources was not called"
    assert summarize_calls[0]["source_filters"] == ["test-source"]
    assert len(backfill_calls) == 1
    assert backfill_calls[0]["range_start"] == 1000.0
    assert backfill_calls[0]["range_end"] == 2000.0


@pytest.mark.asyncio
async def test_sensor_sync_success_triggers_l2_derive(tmp_path, monkeypatch):
    """After a successful sync, execute_schedule_async is called with SCHEDULE_ID_L2_DERIVE."""
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule()
    job_id = await _enqueue_job(repository, schedule)

    derive_calls: list[tuple] = []

    async def _fake_execute_schedule_async(schedule_id: str, *, manual: bool = True, **kwargs):
        derive_calls.append((schedule_id, manual))
        return ScheduledExecutionResult(success=True, message="queued", stats={})

    class _FakeSchedulerService:
        execute_schedule_async = staticmethod(_fake_execute_schedule_async)

    # Patch get_unified_memory to avoid RuntimeError in _backfill_l3_after_sync
    class _FakeL1:
        async def summarize_event_sources(self, **kwargs):
            return []

    class _FakeUnifiedMemory:
        l1 = _FakeL1()

    monkeypatch.setattr(
        "magi.memory.provider.get_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        return ScheduledExecutionResult(success=True, message="sensor_sync_completed")

    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        scheduler_service=_FakeSchedulerService(),
        poll_interval_seconds=0.01,
        running_timeout_seconds=30.0,
    )
    await executor.start()
    await _wait_for_job_status(repository, job_id, "success")
    # L2 trigger fires after the success commit; give the executor loop a beat.
    deadline = time.time() + 2.0
    while time.time() < deadline and not derive_calls:
        await asyncio.sleep(0.02)
    await executor.stop()

    from magi.memory.l2.derive_schedule import SCHEDULE_ID_L2_DERIVE

    assert len(derive_calls) == 1, f"Expected 1 L2 derive call, got {len(derive_calls)}"
    assert derive_calls[0] == (SCHEDULE_ID_L2_DERIVE, True)


@pytest.mark.asyncio
async def test_sensor_sync_has_more_queues_continuation_and_defers_derivations(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule()
    job_id = await _enqueue_job(repository, schedule)

    continuation_calls: list[dict[str, object]] = []
    derive_calls: list[str] = []
    summarize_calls: list[dict[str, object]] = []

    async def _fake_schedule_once(**kwargs):
        continuation_calls.append(kwargs)
        return ScheduleDefinition(
            schedule_id=str(kwargs["schedule_id"]),
            target_type=kwargs["target_type"],
            target_key=str(kwargs["target_key"]),
            trigger=TriggerDefinition(
                trigger_type=TriggerType.ONCE,
                config={"run_at": kwargs["run_at"]},
            ),
            target_payload=dict(kwargs["target_payload"]),
            metadata=dict(kwargs.get("metadata") or {}),
        )

    async def _fake_execute_schedule_async(schedule_id: str, *, manual: bool = True, **kwargs):
        derive_calls.append(schedule_id)
        return ScheduledExecutionResult(success=True, message="queued", stats={})

    class _FakeSchedulerService:
        schedule_once = staticmethod(_fake_schedule_once)
        execute_schedule_async = staticmethod(_fake_execute_schedule_async)

    class _FakeL1:
        async def summarize_event_sources(self, **kwargs):
            summarize_calls.append(kwargs)
            return [
                {
                    "source": "test-source",
                    "event_count": 5,
                    "avg_importance": 0.5,
                    "min_timestamp": 1000.0,
                    "max_timestamp": 2000.0,
                }
            ]

    class _FakeUnifiedMemory:
        l1 = _FakeL1()

        async def backfill_l3_gaps(self, **kwargs):
            raise AssertionError("L3 backfill should wait until the final catch-up batch")

    monkeypatch.setattr(
        "magi.memory.provider.get_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        assert job_record["job_id"] == job_id
        return ScheduledExecutionResult(
            success=True,
            message="sensor_sync_completed",
            next_cursor="cursor-2",
            stats={"items": 200, "has_more": True},
        )

    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        scheduler_service=_FakeSchedulerService(),
        poll_interval_seconds=0.01,
        running_timeout_seconds=30.0,
    )
    await executor.start()
    await _wait_for_job_status(repository, job_id, "success")
    deadline = time.time() + 2.0
    while time.time() < deadline and not continuation_calls:
        await asyncio.sleep(0.02)
    await executor.stop()

    assert len(continuation_calls) == 1
    continuation = continuation_calls[0]
    assert str(continuation["schedule_id"]).startswith("sensor-sync-continuation:test-plugin:test-source:")
    assert continuation["target_type"] == ScheduledTargetType.SENSOR_SYNC
    assert continuation["target_key"] == schedule.target_key
    assert continuation["target_payload"] == {
        "plugin_id": "test-plugin",
        "source_type": "test-source",
        "manual": False,
    }
    assert continuation["metadata"]["continuation"] is True
    assert continuation["metadata"]["parent_job_id"] == job_id
    assert summarize_calls == []
    assert derive_calls == []


@pytest.mark.asyncio
async def test_sensor_sync_success_no_scheduler_service(tmp_path, monkeypatch):
    """Sync succeeds and does not crash when scheduler_service is None."""
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule()
    job_id = await _enqueue_job(repository, schedule)

    class _FakeL1:
        async def summarize_event_sources(self, **kwargs):
            return []

    class _FakeUnifiedMemory:
        l1 = _FakeL1()

    monkeypatch.setattr(
        "magi.memory.provider.get_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        return ScheduledExecutionResult(success=True, message="sensor_sync_completed")

    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        scheduler_service=None,  # explicitly no scheduler
        poll_interval_seconds=0.01,
        running_timeout_seconds=30.0,
    )
    await executor.start()
    completed_job = await _wait_for_job_status(repository, job_id, "success")
    await executor.stop()

    assert completed_job["result_message"] == "sensor_sync_completed"


@pytest.mark.asyncio
async def test_sensor_sync_l2_derive_trigger_failure_does_not_fail_sync(tmp_path, monkeypatch):
    """A raising scheduler does not fail the committed sync — trigger is fully guarded."""
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule()
    job_id = await _enqueue_job(repository, schedule)

    async def _raising_execute_schedule_async(schedule_id: str, **kwargs):
        raise RuntimeError("scheduler exploded")

    class _BrokenSchedulerService:
        execute_schedule_async = staticmethod(_raising_execute_schedule_async)

    class _FakeL1:
        async def summarize_event_sources(self, **kwargs):
            return []

    class _FakeUnifiedMemory:
        l1 = _FakeL1()

    monkeypatch.setattr(
        "magi.memory.provider.get_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        return ScheduledExecutionResult(success=True, message="sensor_sync_completed")

    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        scheduler_service=_BrokenSchedulerService(),
        poll_interval_seconds=0.01,
        running_timeout_seconds=30.0,
    )
    await executor.start()
    completed_job = await _wait_for_job_status(repository, job_id, "success")
    await executor.stop()

    # The sync must still be committed as success despite the scheduler crash
    assert completed_job["result_message"] == "sensor_sync_completed"
    assert completed_job["status"] == "success"


@pytest.mark.asyncio
async def test_sensor_sync_executor_requeues_stale_running_job_on_startup(tmp_path):
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule()
    job_id = await _enqueue_job(repository, schedule)
    claimed = await repository.claim_next_sensor_sync_job(claimed_by="stale-executor")
    assert claimed is not None

    connection = sqlite3.connect(str(db_path))
    connection.execute(
        """
        UPDATE sensor_sync_jobs
        SET started_at = ?, claimed_at = ?
        WHERE job_id = ?
        """,
        (time.time() - 3600.0, time.time() - 3600.0, job_id),
    )
    connection.commit()
    connection.close()

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        return ScheduledExecutionResult(
            success=True,
            message="recovered",
            stats={"items": 1},
        )

    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        poll_interval_seconds=0.01,
        running_timeout_seconds=0.01,
    )
    await executor.start()
    completed_job = await _wait_for_job_status(repository, job_id, "success")
    await executor.stop()

    assert completed_job["result_message"] == "recovered"
