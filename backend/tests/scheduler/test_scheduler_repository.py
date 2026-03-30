from __future__ import annotations

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


@pytest.mark.asyncio
async def test_enqueue_sensor_sync_job_rejects_second_outstanding_job_for_same_target(tmp_path):
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    await repository.upsert_schedule(schedule)

    first_execution_id = await repository.create_execution_record(
        schedule_id=schedule.schedule_id,
        target_type=schedule.target_type,
        target_key=schedule.target_key,
        manual=False,
        started_at=time.time(),
    )
    first_job_id = await repository.enqueue_sensor_sync_job(
        schedule=schedule,
        execution_id=first_execution_id,
        manual=False,
    )

    second_execution_id = await repository.create_execution_record(
        schedule_id=schedule.schedule_id,
        target_type=schedule.target_type,
        target_key=schedule.target_key,
        manual=False,
        started_at=time.time(),
    )
    second_job_id = await repository.enqueue_sensor_sync_job(
        schedule=schedule,
        execution_id=second_execution_id,
        manual=False,
    )
    outstanding = await repository.get_outstanding_sensor_sync_job(
        schedule.target_type,
        schedule.target_key,
    )

    assert first_job_id is not None
    assert second_job_id is None
    assert outstanding is not None
    assert outstanding["job_id"] == first_job_id
    assert outstanding["status"] == "queued"
    assert outstanding["execution_id"] == first_execution_id


@pytest.mark.asyncio
async def test_claim_next_sensor_sync_job_marks_job_running(tmp_path):
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    await repository.upsert_schedule(schedule)
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

    claimed = await repository.claim_next_sensor_sync_job(claimed_by="executor-1")

    assert claimed is not None
    assert claimed["job_id"] == job_id
    assert claimed["status"] == "running"
    assert claimed["claimed_by"] == "executor-1"
    assert claimed["started_at"] is not None


@pytest.mark.asyncio
async def test_requeue_stale_running_sensor_sync_job(tmp_path):
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule()
    await repository.upsert_schedule(schedule)
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
    claimed = await repository.claim_next_sensor_sync_job(claimed_by="executor-1")
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

    requeued_count = await repository.requeue_stale_sensor_sync_jobs(
        running_timeout_seconds=60.0,
    )
    outstanding = await repository.get_outstanding_sensor_sync_job(
        schedule.target_type,
        schedule.target_key,
    )

    assert requeued_count == 1
    assert outstanding is not None
    assert outstanding["job_id"] == job_id
    assert outstanding["status"] == "queued"
    assert outstanding["claimed_by"] is None
    assert outstanding["claimed_at"] is None
    assert outstanding["started_at"] is None


@pytest.mark.asyncio
async def test_complete_sensor_sync_job_success_persists_result_fields(tmp_path):
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    await repository.upsert_schedule(schedule)
    execution_id = await repository.create_execution_record(
        schedule_id=schedule.schedule_id,
        target_type=schedule.target_type,
        target_key=schedule.target_key,
        manual=False,
        started_at=time.time(),
    )
    await repository.enqueue_sensor_sync_job(
        schedule=schedule,
        execution_id=execution_id,
        manual=False,
    )
    claimed = await repository.claim_next_sensor_sync_job(claimed_by="executor-1")
    assert claimed is not None

    result = ScheduledExecutionResult(
        success=True,
        message="sensor_sync_completed",
        next_cursor="cursor-2",
        watermark_ts=123.0,
        stats={"items": 2},
    )
    await repository.complete_sensor_sync_job_success(
        claimed["job_id"],
        result=result,
        finished_at=time.time(),
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
