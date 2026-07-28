from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest

from magi.scheduler import (
    ScheduleDefinition,
    ScheduledExecutionResult,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)
from magi.scheduler.repository import ScheduleRepository
from magi.scheduler.sensor_jobs import SensorSyncEnqueueResult


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


async def _enqueue_sensor_sync(
    repository: ScheduleRepository,
    schedule: ScheduleDefinition,
    *,
    manual: bool = False,
    started_at: float | None = None,
) -> SensorSyncEnqueueResult:
    await repository.upsert_schedule(schedule)
    admitted = await repository.enqueue_sensor_sync_execution(
        schedule=schedule,
        manual=manual,
        started_at=started_at if started_at is not None else time.time(),
    )
    assert admitted is not None
    return admitted


@pytest.mark.asyncio
async def test_enqueue_sensor_sync_execution_rejects_second_outstanding_job_for_same_target(
    tmp_path,
):
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    first = await _enqueue_sensor_sync(repository, schedule)
    second = await repository.enqueue_sensor_sync_execution(
        schedule=schedule,
        manual=False,
        started_at=time.time(),
    )
    outstanding = await repository.get_outstanding_sensor_sync_job(
        schedule.target_type,
        schedule.target_key,
    )
    executions = await repository.list_executions(schedule_id=schedule.schedule_id)

    assert second is None
    assert outstanding is not None
    assert outstanding["job_id"] == first.job_id
    assert outstanding["status"] == "queued"
    assert outstanding["execution_id"] == first.execution_id
    assert [execution["execution_id"] for execution in executions] == [first.execution_id]


@pytest.mark.asyncio
async def test_claim_next_sensor_sync_job_marks_job_running(tmp_path):
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    admitted = await _enqueue_sensor_sync(repository, schedule)

    claimed = await repository.claim_next_sensor_sync_job(claimed_by="executor-1")

    assert claimed is not None
    assert claimed["job_id"] == admitted.job_id
    assert claimed["status"] == "running"
    assert claimed["claimed_by"] == "executor-1"
    assert claimed["started_at"] is not None


@pytest.mark.asyncio
async def test_recover_running_sensor_sync_job_immediately(tmp_path):
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    admitted = await _enqueue_sensor_sync(repository, schedule)
    claimed = await repository.claim_next_sensor_sync_job(claimed_by="executor-1")
    assert claimed is not None

    requeued_count = await repository.recover_running_sensor_sync_jobs()
    outstanding = await repository.get_outstanding_sensor_sync_job(
        schedule.target_type,
        schedule.target_key,
    )

    assert requeued_count == 1
    assert outstanding is not None
    assert outstanding["job_id"] == admitted.job_id
    assert outstanding["status"] == "queued"
    assert outstanding["claimed_by"] is None
    assert outstanding["claimed_at"] is None
    assert outstanding["started_at"] is None
    assert outstanding["error"] == "SENSOR_SYNC_EXECUTOR_RESTARTED"


@pytest.mark.asyncio
async def test_settle_sensor_sync_job_failure_waits_until_retry_is_due(tmp_path, monkeypatch):
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    now = 1_000.0
    monkeypatch.setattr("magi.scheduler.sensor_jobs.admission.time.time", lambda: now)
    admitted = await _enqueue_sensor_sync(
        repository,
        schedule,
        started_at=now,
    )
    claimed = await repository.claim_next_sensor_sync_job(claimed_by="executor-1")
    assert claimed is not None

    requeued = await repository.settle_sensor_sync_job_failure(
        admitted.job_id,
        error="temporary source failure",
        failed_at=now,
        retry_delay_seconds=30.0,
        max_attempts=3,
        scheduler_job_id=None,
    )

    assert requeued is True
    assert await repository.claim_next_sensor_sync_job(claimed_by="executor-1") is None

    now = 1_030.0
    retried = await repository.claim_next_sensor_sync_job(claimed_by="executor-1")

    assert retried is not None
    assert retried["job_id"] == admitted.job_id
    assert retried["status"] == "running"
    assert retried["attempt_count"] == 2


@pytest.mark.asyncio
async def test_settle_sensor_sync_job_success_persists_all_runtime_state(tmp_path):
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    admitted = await _enqueue_sensor_sync(repository, schedule)
    claimed = await repository.claim_next_sensor_sync_job(claimed_by="executor-1")
    assert claimed is not None

    result = ScheduledExecutionResult(
        success=True,
        message="sensor_sync_completed",
        next_cursor="cursor-2",
        watermark_ts=123.0,
        stats={"items": 2},
    )
    await repository.settle_sensor_sync_job_success(
        claimed["job_id"],
        result=result,
        finished_at=time.time(),
        scheduler_job_id="scheduler-job-1",
        continue_sync=False,
    )

    outstanding = await repository.get_outstanding_sensor_sync_job(
        schedule.target_type,
        schedule.target_key,
    )
    job = await repository.get_sensor_sync_job(claimed["job_id"])

    assert outstanding is None
    assert job is not None
    assert job["status"] == "success"
    assert job["result_message"] == "sensor_sync_completed"
    assert job["next_cursor"] == "cursor-2"
    assert job["watermark_ts"] == 123.0
    assert job["stats"] == {"items": 2}
    target_state = await repository.get_target_state(
        schedule.target_type,
        schedule.target_key,
    )
    executions = await repository.list_executions(schedule_id=schedule.schedule_id)
    assert target_state.running is False
    assert target_state.last_cursor == "cursor-2"
    assert target_state.last_error is None
    assert target_state.scheduler_job_id == "scheduler-job-1"
    assert executions[0]["execution_id"] == admitted.execution_id
    assert executions[0]["status"] == "success"
    assert executions[0]["next_cursor"] == "cursor-2"


@pytest.mark.asyncio
async def test_settle_sensor_sync_job_success_atomically_admits_continuation(tmp_path):
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    schedule.target_payload["sync_request"] = {
        "mode": "backfill",
        "backfill_scope": "last_30_days",
    }
    admitted = await _enqueue_sensor_sync(repository, schedule, manual=True)
    claimed = await repository.claim_next_sensor_sync_job(claimed_by="executor-1")
    assert claimed is not None

    settlement = await repository.settle_sensor_sync_job_success(
        claimed["job_id"],
        result=ScheduledExecutionResult(
            success=True,
            message="sensor_sync_completed",
            next_cursor="cursor-2",
            stats={"items": 200, "has_more": True},
        ),
        finished_at=time.time(),
        scheduler_job_id="scheduler-job-1",
        continue_sync=True,
    )

    parent = await repository.get_sensor_sync_job(admitted.job_id)
    continuation = await repository.get_outstanding_sensor_sync_job(
        schedule.target_type,
        schedule.target_key,
    )
    target_state = await repository.get_target_state(
        schedule.target_type,
        schedule.target_key,
    )
    continuation_executions = await repository.list_executions(
        schedule_id=str(continuation["schedule_id"]) if continuation is not None else "",
    )

    assert settlement.committed is True
    assert parent is not None
    assert parent["status"] == "success"
    assert continuation is not None
    assert continuation["job_id"] == settlement.continuation_job_id
    assert continuation["execution_id"] == settlement.continuation_execution_id
    assert continuation["status"] == "queued"
    assert continuation["manual"] is True
    assert str(continuation["schedule_id"]).startswith(
        "sensor-sync-continuation:test-plugin:test-source:"
    )
    assert continuation["payload"] == {
        "plugin_id": "test-plugin",
        "source_type": "test-source",
        "manual": True,
        "sync_request": schedule.target_payload["sync_request"],
    }
    assert target_state.running is True
    assert target_state.last_cursor == "cursor-2"
    assert len(continuation_executions) == 1
    assert continuation_executions[0]["execution_id"] == settlement.continuation_execution_id
    assert continuation_executions[0]["status"] == "running"


@pytest.mark.asyncio
async def test_settle_sensor_sync_job_success_continuation_is_idempotent(tmp_path):
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule()
    admitted = await _enqueue_sensor_sync(repository, schedule)
    claimed = await repository.claim_next_sensor_sync_job(claimed_by="executor-1")
    assert claimed is not None
    result = ScheduledExecutionResult(
        success=True,
        message="sensor_sync_completed",
        stats={"has_more": True},
    )

    first = await repository.settle_sensor_sync_job_success(
        admitted.job_id,
        result=result,
        finished_at=time.time(),
        scheduler_job_id=None,
        continue_sync=True,
    )
    repeated = await repository.settle_sensor_sync_job_success(
        admitted.job_id,
        result=result,
        finished_at=time.time(),
        scheduler_job_id=None,
        continue_sync=True,
    )

    connection = sqlite3.connect(db_path)
    job_count = connection.execute("SELECT COUNT(*) FROM sensor_sync_jobs").fetchone()[0]
    execution_count = connection.execute(
        "SELECT COUNT(*) FROM schedule_executions"
    ).fetchone()[0]
    connection.close()

    assert first.committed is True
    assert repeated.committed is False
    assert repeated.continuation_job_id == first.continuation_job_id
    assert repeated.continuation_execution_id == first.continuation_execution_id
    assert job_count == 2
    assert execution_count == 2


@pytest.mark.asyncio
async def test_concurrent_sensor_sync_success_settlement_admits_one_continuation(tmp_path):
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule()
    admitted = await _enqueue_sensor_sync(repository, schedule)
    claimed = await repository.claim_next_sensor_sync_job(claimed_by="executor-1")
    assert claimed is not None
    result = ScheduledExecutionResult(
        success=True,
        message="sensor_sync_completed",
        stats={"has_more": True},
    )
    finished_at = time.time()

    settlements = await asyncio.gather(
        *(
            repository.settle_sensor_sync_job_success(
                admitted.job_id,
                result=result,
                finished_at=finished_at,
                scheduler_job_id=None,
                continue_sync=True,
            )
            for _ in range(2)
        )
    )

    connection = sqlite3.connect(db_path)
    job_count = connection.execute("SELECT COUNT(*) FROM sensor_sync_jobs").fetchone()[0]
    execution_count = connection.execute(
        "SELECT COUNT(*) FROM schedule_executions"
    ).fetchone()[0]
    connection.close()

    assert sorted(settlement.committed for settlement in settlements) == [False, True]
    assert len({settlement.continuation_job_id for settlement in settlements}) == 1
    assert job_count == 2
    assert execution_count == 2


@pytest.mark.asyncio
async def test_continuation_admission_failure_rolls_back_success_settlement(tmp_path):
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule()
    admitted = await _enqueue_sensor_sync(repository, schedule)
    claimed = await repository.claim_next_sensor_sync_job(claimed_by="executor-1")
    assert claimed is not None
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TRIGGER fail_sensor_continuation_admission
        BEFORE INSERT ON sensor_sync_jobs
        WHEN NEW.schedule_id LIKE 'sensor-sync-continuation:%'
        BEGIN
            SELECT RAISE(ABORT, 'continuation admission failed');
        END
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(sqlite3.IntegrityError, match="continuation admission failed"):
        await repository.settle_sensor_sync_job_success(
            admitted.job_id,
            result=ScheduledExecutionResult(
                success=True,
                message="sensor_sync_completed",
                stats={"has_more": True},
            ),
            finished_at=time.time(),
            scheduler_job_id=None,
            continue_sync=True,
        )

    parent = await repository.get_sensor_sync_job(admitted.job_id)
    outstanding = await repository.get_outstanding_sensor_sync_job(
        schedule.target_type,
        schedule.target_key,
    )
    target_state = await repository.get_target_state(
        schedule.target_type,
        schedule.target_key,
    )
    executions = await repository.list_executions(schedule_id=schedule.schedule_id)

    assert parent is not None
    assert parent["status"] == "running"
    assert outstanding is not None
    assert outstanding["job_id"] == admitted.job_id
    assert target_state.running is True
    assert executions[0]["status"] == "running"


@pytest.mark.asyncio
async def test_latest_sensor_sync_job_keeps_completed_backfill_details(tmp_path):
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    schedule.target_payload["sync_request"] = {
        "mode": "backfill",
        "backfill_scope": "custom",
        "backfill_start_date": "2026-06-01",
        "backfill_end_date": "2026-06-30",
    }
    admitted = await _enqueue_sensor_sync(
        repository,
        schedule,
        manual=True,
    )
    claimed = await repository.claim_next_sensor_sync_job(claimed_by="executor-1")
    assert claimed is not None
    await repository.settle_sensor_sync_job_success(
        admitted.job_id,
        result=ScheduledExecutionResult(success=True, stats={"items": 3}),
        finished_at=time.time(),
        scheduler_job_id=None,
        continue_sync=False,
    )

    latest = await repository.get_latest_sensor_sync_job(
        schedule.target_type,
        schedule.target_key,
    )

    assert latest is not None
    assert latest["job_id"] == admitted.job_id
    assert latest["status"] == "success"
    assert dict(latest["payload"])["sync_request"] == schedule.target_payload["sync_request"]


@pytest.mark.asyncio
async def test_update_target_cursor_persists_partial_cursor(tmp_path):
    """update_target_cursor saves cursor without clearing the running flag."""
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    await repository.upsert_schedule(schedule)

    # Mark target as running
    acquired = await repository.acquire_target_lock(
        schedule.target_type,
        schedule.target_key,
    )
    assert acquired is True

    # Save mid-batch cursor
    await repository.update_target_cursor(
        schedule.target_type,
        schedule.target_key,
        cursor="partial-cursor-42",
        watermark_ts=5000.0,
    )

    state = await repository.get_target_state(
        schedule.target_type,
        schedule.target_key,
    )
    assert state.last_cursor == "partial-cursor-42"
    assert state.watermark_ts == 5000.0
    # Should still be running
    assert state.running is True


@pytest.mark.asyncio
async def test_update_target_cursor_preserves_watermark_when_none(tmp_path):
    """update_target_cursor keeps existing watermark_ts when new value is None."""
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    await repository.upsert_schedule(schedule)
    await repository.acquire_target_lock(
        schedule.target_type,
        schedule.target_key,
    )

    # Set initial cursor with watermark
    await repository.update_target_cursor(
        schedule.target_type,
        schedule.target_key,
        cursor="cursor-1",
        watermark_ts=3000.0,
    )
    # Update cursor without watermark
    await repository.update_target_cursor(
        schedule.target_type,
        schedule.target_key,
        cursor="cursor-2",
        watermark_ts=None,
    )

    state = await repository.get_target_state(
        schedule.target_type,
        schedule.target_key,
    )
    assert state.last_cursor == "cursor-2"
    assert state.watermark_ts == 3000.0  # preserved
