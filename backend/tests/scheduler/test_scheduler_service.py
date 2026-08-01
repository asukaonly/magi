from __future__ import annotations

import asyncio
import sqlite3
import time
from unittest.mock import AsyncMock

import pytest

from magi.scheduler import (
    ScheduleDefinition,
    SchedulerDataClearInProgressError,
    SchedulerService,
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)


@pytest.mark.asyncio
async def test_scheduler_can_prepare_jobs_before_activation(tmp_path):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)

    await service.start(paused=True)
    try:
        assert service._scheduler.state == 2
        service.activate()
        assert service._scheduler.state == 1
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_identical_schedule_registration_skips_persistent_writes(tmp_path):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    await service.start()
    try:
        await service.schedule_interval(
            schedule_id="stable",
            target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key="global",
            seconds=300.0,
            target_payload={"scope": "all"},
        )
        upsert_schedule = AsyncMock(wraps=service.repository.upsert_schedule)
        upsert_job = AsyncMock(wraps=service._upsert_job)
        service.repository.upsert_schedule = upsert_schedule
        service._upsert_job = upsert_job

        await service.schedule_interval(
            schedule_id="stable",
            target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key="global",
            seconds=300.0,
            target_payload={"scope": "all"},
        )

        upsert_schedule.assert_not_awaited()
        upsert_job.assert_not_awaited()
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_scheduler_service_persists_and_restores_interval_jobs(tmp_path):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    handled: list[str] = []

    async def handler(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        handled.append(context.schedule.schedule_id)
        return ScheduledExecutionResult(success=True, message="ok")

    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    service.register_handler(ScheduledTargetType.MEMORY_L2_MAINTENANCE, handler)
    await service.start()

    await service.schedule_interval(
        schedule_id="l2-maintenance-1",
        target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
        target_key="global",
        seconds=300.0,
        target_payload={},
    )
    await service.trigger_now("l2-maintenance-1")

    schedule = await service.repository.get_schedule("l2-maintenance-1")
    state = await service.get_target_state(ScheduledTargetType.MEMORY_L2_MAINTENANCE, "global")

    assert schedule is not None
    assert schedule.trigger.trigger_type.value == "interval"
    assert schedule.job_id == "l2-maintenance-1"
    assert handled == ["l2-maintenance-1"]
    assert state.last_success_at is not None
    # next_run_at is NOT persisted in target_state; it is only available via
    # get_schedule_runtime_state (jobstore-sourced). get_target_state returns None.
    assert state.next_run_at is None

    await service.stop()

    restored = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    restored.register_handler(ScheduledTargetType.MEMORY_L2_MAINTENANCE, handler)
    await restored.start()

    restored_schedule = await restored.repository.get_schedule("l2-maintenance-1")

    assert restored_schedule is not None
    assert restored._scheduler.get_job("l2-maintenance-1") is not None

    await restored.stop()


@pytest.mark.asyncio
async def test_reregistering_interval_job_preserves_next_run(tmp_path):
    """Re-registering an already-scheduled interval job must NOT reset its
    next_run to now+interval.

    Regression for #85: long-interval maintenance (24h) was starved because every
    app start re-upserts the job with ``replace_existing=True``, which recomputes
    next_run = now + interval. Desktop restarts more often than the interval, so the
    countdown never elapsed and L2 maintenance never ran.
    """
    import datetime

    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()

    async def handler(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        return ScheduledExecutionResult(success=True, message="ok")

    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    service.register_handler(ScheduledTargetType.MEMORY_L2_MAINTENANCE, handler)
    await service.start()
    try:
        await service.schedule_interval(
            schedule_id="m",
            target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key="global",
            seconds=86_400.0,
            target_payload={},
        )
        # Simulate a job partway through its 24h countdown (~100s left), as the
        # persistent jobstore holds after the app has been running for a while.
        sentinel = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=100)
        service._scheduler.modify_job("m", next_run_time=sentinel)
        before = service._scheduler.get_job("m").next_run_time

        # Re-registration on the next app start (what _restore_persisted_jobs does).
        schedule = await service.repository.get_schedule("m")
        await service._upsert_job(schedule)

        after = service._scheduler.get_job("m").next_run_time
        # Bug: `after` resets to ~now+86400 (diff ~86300s). Fixed: preserved (~0s).
        assert abs((after - before).total_seconds()) < 5, (
            f"next_run was reset on re-registration: before={before} after={after}"
        )
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_interval_jobs_are_configured_to_catch_up_missed_runs(tmp_path):
    """Scheduled jobs must catch up a run that came due while the app was down
    (misfire_grace_time=None) instead of skipping it (#85). The default 120s grace
    drops runs missed during downtime — the common case on a desktop app that is
    only open for part of the day, so a 24h job would otherwise never run.
    """
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()

    async def handler(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        return ScheduledExecutionResult(success=True, message="ok")

    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    service.register_handler(ScheduledTargetType.MEMORY_L2_MAINTENANCE, handler)
    await service.start()
    try:
        await service.schedule_interval(
            schedule_id="m",
            target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key="global",
            seconds=86_400.0,
            target_payload={},
        )
        job = service._scheduler.get_job("m")
        assert job is not None
        # None => an overdue run fires on the next start (caught up, coalesced to
        # one), rather than being dropped past the 120s default grace.
        assert job.misfire_grace_time is None, (
            f"missed runs would be skipped: misfire_grace_time={job.misfire_grace_time}"
        )
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_scheduler_service_supports_once_and_cron_and_replaces_existing_schedule(tmp_path):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)

    async def handler(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        return ScheduledExecutionResult(success=True, message=context.schedule.schedule_id)

    service.register_handler(ScheduledTargetType.MEMORY_L2_MAINTENANCE, handler)
    await service.start()

    await service.schedule_once(
        schedule_id="maintenance-once",
        target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
        target_key="global",
        run_at=time.time() + 60.0,
        target_payload={},
    )
    await service.schedule_cron(
        schedule_id="maintenance-cron",
        target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
        target_key="global",
        cron={"minute": "15", "hour": "8"},
        target_payload={},
    )
    await service.schedule_interval(
        schedule_id="maintenance-cron",
        target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
        target_key="global",
        seconds=120.0,
        target_payload={},
    )

    once_schedule = await service.repository.get_schedule("maintenance-once")
    replaced_schedule = await service.repository.get_schedule("maintenance-cron")

    assert once_schedule is not None
    assert once_schedule.trigger.trigger_type.value == "once"
    assert replaced_schedule is not None
    assert replaced_schedule.trigger.trigger_type.value == "interval"
    assert replaced_schedule.trigger.config["seconds"] == 120.0

    await service.stop()


@pytest.mark.asyncio
async def test_busy_once_schedule_is_rescheduled_in_place(tmp_path):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    target_type = ScheduledTargetType.MEMORY_L2_MAINTENANCE
    target_key = "busy-once"
    await service.start()
    try:
        assert await service.repository.acquire_target_lock(target_type, target_key)
        await service.schedule_once(
            schedule_id="busy-once-retry",
            target_type=target_type,
            target_key=target_key,
            run_at=time.time() + 60.0,
            target_payload={},
        )

        result = await service.execute_schedule("busy-once-retry")

        assert result.message == "target_busy"
        schedules = await service.repository.list_schedules(enabled_only=False)
        assert [item.schedule_id for item in schedules] == ["busy-once-retry"]
        retry = schedules[0]
        assert retry.metadata["_busy_once_retry_count"] == 1
        assert service._scheduler.get_job("busy-once-retry") is not None
        assert await service.repository.get_schedule_next_run_at(retry) is not None
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_busy_once_retry_cannot_overwrite_concurrent_earlier_schedule(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    await service.start()
    try:
        now = time.time()
        await service.schedule_once(
            schedule_id="busy-race",
            target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key="busy-race",
            run_at=now + 60.0,
            target_payload={},
            metadata={"_busy_once_retry_count": 5},
        )

        busy_read = asyncio.Event()
        release_busy = asyncio.Event()
        original_get_schedule = service.repository.get_schedule

        async def _pause_busy_read(schedule_id):  # type: ignore[no-untyped-def]
            schedule = await original_get_schedule(schedule_id)
            task = asyncio.current_task()
            if task is not None and task.get_name() == "busy-reschedule-race":
                busy_read.set()
                await release_busy.wait()
            return schedule

        monkeypatch.setattr(service.repository, "get_schedule", _pause_busy_read)
        busy_task = asyncio.create_task(
            service._reschedule_busy_once(
                "busy-race",
                ScheduledExecutionResult(success=False, message="target_busy"),
            ),
            name="busy-reschedule-race",
        )
        await asyncio.wait_for(busy_read.wait(), timeout=2.0)
        busy_holds_schedule_lock = service._schedule_lock.locked()
        earlier_run_at = now + 10.0
        earlier_task = asyncio.create_task(
            service.schedule_once_earliest(
                schedule_id="busy-race",
                target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
                target_key="busy-race",
                run_at=earlier_run_at,
                target_payload={"source": "correction_retry"},
            )
        )
        if not busy_holds_schedule_lock:
            await asyncio.wait_for(asyncio.shield(earlier_task), timeout=2.0)
        release_busy.set()
        await asyncio.wait_for(asyncio.gather(busy_task, earlier_task), timeout=2.0)

        stored = await original_get_schedule("busy-race")
        assert stored is not None
        next_run_at = await service.repository.get_schedule_next_run_at(stored)
        assert next_run_at is not None
        assert abs(next_run_at - earlier_run_at) < 1.0
        assert stored.target_payload == {"source": "correction_retry"}
    finally:
        release_busy.set()
        await service.stop()


@pytest.mark.asyncio
async def test_schedule_once_earliest_is_atomic_under_concurrency(tmp_path):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    await service.start()
    try:
        now = time.time()
        await asyncio.gather(
            *(
                service.schedule_once_earliest(
                    schedule_id="earliest-once",
                    target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
                    target_key="earliest",
                    run_at=now + offset,
                    target_payload={},
                )
                for offset in (30, 10, 20, 40, 15, 25)
            )
        )

        schedule = await service.repository.get_schedule("earliest-once")
        assert schedule is not None
        next_run_at = await service.repository.get_schedule_next_run_at(schedule)
        assert next_run_at is not None
        assert abs(next_run_at - (now + 10)) < 1.0
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_consumed_once_handler_can_reschedule_same_identifier(tmp_path):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    replacement_run_at = 0.0

    async def handler(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        nonlocal replacement_run_at
        replacement_run_at = time.time() + 60.0
        await service.schedule_once_earliest(
            schedule_id=context.schedule.schedule_id,
            target_type=context.schedule.target_type,
            target_key=context.schedule.target_key,
            run_at=replacement_run_at,
            target_payload=context.schedule.target_payload,
        )
        return ScheduledExecutionResult(success=True, message="retry_scheduled")

    service.register_handler(ScheduledTargetType.MEMORY_L2_MAINTENANCE, handler)
    await service.start()
    try:
        await service.schedule_once(
            schedule_id="self-rescheduling-once",
            target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key="self-rescheduling-once",
            run_at=time.time() + 30.0,
            target_payload={},
        )
        # APScheduler removes a date job before dispatching it. Keep the durable
        # definition to reproduce the state observed by the running handler.
        service._scheduler.remove_job("self-rescheduling-once")

        result = await service.execute_schedule("self-rescheduling-once")

        assert result.message == "retry_scheduled"
        replacement = await service.repository.get_schedule("self-rescheduling-once")
        assert replacement is not None
        next_run_at = await service.repository.get_schedule_next_run_at(replacement)
        assert next_run_at is not None
        assert abs(next_run_at - replacement_run_at) < 1.0
        assert service._scheduler.get_job("self-rescheduling-once") is not None
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_unschedule_clears_stale_target_errors(tmp_path):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)

    async def handler(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        raise RuntimeError("boom")

    service.register_handler(ScheduledTargetType.MEMORY_L2_MAINTENANCE, handler)
    await service.start()

    await service.schedule_interval(
        schedule_id="maintenance-error",
        target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
        target_key="global",
        seconds=300.0,
        target_payload={},
    )

    with pytest.raises(RuntimeError):
        await service.trigger_now("maintenance-error")

    failed_state = await service.get_target_state(ScheduledTargetType.MEMORY_L2_MAINTENANCE, "global")
    assert failed_state.last_error == "boom"

    await service.unschedule("maintenance-error")
    cleared_state = await service.get_target_state(ScheduledTargetType.MEMORY_L2_MAINTENANCE, "global")

    assert cleared_state.last_error is None
    assert cleared_state.scheduler_job_id is None
    assert cleared_state.next_run_at is None

    await service.stop()


@pytest.mark.asyncio
async def test_scheduler_service_serializes_concurrent_schedule_updates(tmp_path):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)

    async def handler(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        return ScheduledExecutionResult(success=True, message=context.schedule.schedule_id)

    service.register_handler(ScheduledTargetType.MEMORY_L2_MAINTENANCE, handler)
    await service.start()

    await asyncio.gather(
        *[
            service.schedule_interval(
                schedule_id="maintenance-shared",
                target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
                target_key="global",
                seconds=120.0,
                target_payload={},
            )
            for _ in range(4)
        ]
    )

    schedule = await service.repository.get_schedule("maintenance-shared")

    assert schedule is not None
    assert schedule.job_id == "maintenance-shared"
    assert service._scheduler.get_job("maintenance-shared") is not None

    await service.stop()


@pytest.mark.asyncio
async def test_scheduler_service_persists_execution_history_rows(tmp_path):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)

    async def handler(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        if context.schedule.target_key == "failed":
            raise RuntimeError("planned failure")
        return ScheduledExecutionResult(success=True, message="ok", stats={"runs": 1})

    service.register_handler(ScheduledTargetType.MEMORY_L2_MAINTENANCE, handler)
    await service.start()

    await service.schedule_interval(
        schedule_id="maintenance-success",
        target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
        target_key="ok",
        seconds=300.0,
        target_payload={},
    )
    await service.schedule_interval(
        schedule_id="maintenance-failed",
        target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
        target_key="failed",
        seconds=300.0,
        target_payload={},
    )

    await service.trigger_now("maintenance-success")
    with pytest.raises(RuntimeError):
        await service.trigger_now("maintenance-failed")

    await service.stop()

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        SELECT schedule_id, status, result_message, error, duration_ms
        FROM schedule_executions
        ORDER BY started_at ASC
        """
    )
    rows = cur.fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[0][0] == "maintenance-success"
    assert rows[0][1] == "success"
    assert rows[0][2] == "ok"
    assert rows[0][3] is None
    assert rows[0][4] is not None
    assert rows[1][0] == "maintenance-failed"
    assert rows[1][1] == "failed"
    assert rows[1][2] is None
    assert rows[1][3] == "planned failure"
    assert rows[1][4] is not None


@pytest.mark.asyncio
async def test_scheduler_service_enqueues_sensor_sync_jobs_without_running_handler(tmp_path):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    handled: list[str] = []
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)

    async def handler(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        handled.append(context.schedule.schedule_id)
        return ScheduledExecutionResult(success=True, message="unexpected_inline_run")

    service.register_handler(ScheduledTargetType.SENSOR_SYNC, handler)
    await service.start()

    await service.schedule_interval(
        schedule_id="sensor-sync-enqueue",
        target_type=ScheduledTargetType.SENSOR_SYNC,
        target_key="test-plugin:test-source",
        seconds=60.0,
        target_payload={"plugin_id": "test-plugin", "source_type": "test-source"},
    )

    result = await service.execute_schedule("sensor-sync-enqueue")
    outstanding = await service.repository.get_outstanding_sensor_sync_job(
        ScheduledTargetType.SENSOR_SYNC,
        "test-plugin:test-source",
    )

    await service.stop()

    assert result.success is True
    assert result.message == "sensor_sync_enqueued"
    assert handled == []
    assert outstanding is not None
    assert outstanding["status"] == "queued"


@pytest.mark.asyncio
async def test_scheduler_service_coalesces_sensor_sync_when_outstanding_job_exists(tmp_path):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)

    async def handler(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        return ScheduledExecutionResult(success=True, message="unexpected_inline_run")

    service.register_handler(ScheduledTargetType.SENSOR_SYNC, handler)
    await service.start()

    await service.schedule_interval(
        schedule_id="sensor-sync-coalesce",
        target_type=ScheduledTargetType.SENSOR_SYNC,
        target_key="test-plugin:test-source",
        seconds=60.0,
        target_payload={"plugin_id": "test-plugin", "source_type": "test-source"},
    )

    first = await service.execute_schedule("sensor-sync-coalesce")
    second = await service.execute_schedule("sensor-sync-coalesce")
    outstanding = await service.repository.get_outstanding_sensor_sync_job(
        ScheduledTargetType.SENSOR_SYNC,
        "test-plugin:test-source",
    )
    executions = await service.repository.list_executions(schedule_id="sensor-sync-coalesce")

    await service.stop()

    assert first.message == "sensor_sync_enqueued"
    assert second.message == "target_busy"
    assert outstanding is not None
    assert outstanding["status"] == "queued"
    assert len(executions) == 1
    assert executions[0]["execution_id"] == outstanding["execution_id"]


@pytest.mark.asyncio
async def test_next_run_at_sourced_from_jobstore_not_target_state(tmp_path):
    """next_run_at must come from the APScheduler jobstore, never from target_state.

    get_target_state (raw persistence layer) must return next_run_at=None — the
    field is no longer persisted there. get_schedule_runtime_state (display layer)
    must populate next_run_at from the jobstore instead.
    """
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()

    async def handler(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        return ScheduledExecutionResult(success=True, message="ok")

    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    service.register_handler(ScheduledTargetType.MEMORY_L2_MAINTENANCE, handler)
    await service.start()
    try:
        await service.schedule_interval(
            schedule_id="nra-test",
            target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key="global",
            seconds=300.0,
            target_payload={},
        )
        await service.trigger_now("nra-test")

        # Raw persistence layer: next_run_at is NOT stored here
        raw_state = await service.get_target_state(
            ScheduledTargetType.MEMORY_L2_MAINTENANCE, "global"
        )
        assert raw_state.next_run_at is None, (
            "target_state must not persist next_run_at (single-source: jobstore)"
        )

        # Display layer: next_run_at is populated from jobstore
        schedule = await service.repository.get_schedule("nra-test")
        assert schedule is not None
        runtime_state = await service.repository.get_schedule_runtime_state(schedule)
        assert runtime_state.next_run_at is not None, (
            "get_schedule_runtime_state must populate next_run_at from jobstore"
        )
        # Confirm the jobstore is the source by comparing with get_schedule_next_run_at
        jobstore_next_run = await service.repository.get_schedule_next_run_at(schedule)
        assert runtime_state.next_run_at == jobstore_next_run
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_scheduler_service_recovers_from_wakeup_failure(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    await service.start()

    scheduler = service._scheduler
    scheduler.jobstore_retry_interval = 0.05

    scheduled_waits: list[float | None] = []

    def record_start_timer(wait_seconds):
        scheduled_waits.append(wait_seconds)

    def flaky_process_jobs():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(scheduler, "_start_timer", record_start_timer)
    monkeypatch.setattr(scheduler, "_process_jobs", flaky_process_jobs)

    scheduler.wakeup()
    await asyncio.sleep(0)

    await service.stop()

    assert scheduled_waits == [0.05]


@pytest.mark.asyncio
async def test_user_data_clear_fences_stale_user_handler_and_preserves_system_jobs(
    tmp_path,
):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    handler_started = asyncio.Event()
    enqueue_attempts: list[str] = []

    async def user_handler(
        context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        handler_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

        async def enqueue() -> None:
            enqueue_attempts.append(context.schedule.schedule_id)

        await service.run_user_agent_effect(
            context.data_generation,
            enqueue,
        )
        return ScheduledExecutionResult(success=True, message="enqueued")

    service.register_handler(ScheduledTargetType.USER_AGENT_TASK, user_handler)
    await service.start()
    try:
        await service.schedule(
            ScheduleDefinition(
                schedule_id="agent-task:stale",
                target_type=ScheduledTargetType.USER_AGENT_TASK,
                target_key="agent-task:stale",
                trigger=TriggerDefinition(
                    trigger_type=TriggerType.INTERVAL,
                    config={"seconds": 300.0},
                ),
                target_payload={"prompt": "Reveal old private context."},
            )
        )
        await service.schedule_interval(
            schedule_id="system-maintenance",
            target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key="global",
            seconds=300.0,
            target_payload={},
        )
        queued = await service.execute_schedule_async("agent-task:stale")
        await asyncio.wait_for(handler_started.wait(), timeout=2.0)

        async with service.user_data_clear_boundary():
            counts = await service.clear_user_data()
            blocked_execution = await service.execute_schedule("system-maintenance")
            with pytest.raises(SchedulerDataClearInProgressError):
                await service.schedule(
                    ScheduleDefinition(
                        schedule_id="agent-task:during-clear",
                        target_type=ScheduledTargetType.USER_AGENT_TASK,
                        target_key="agent-task:during-clear",
                        trigger=TriggerDefinition(
                            trigger_type=TriggerType.INTERVAL,
                            config={"seconds": 300.0},
                        ),
                        target_payload={"prompt": "Must not persist."},
                    )
                )
            with pytest.raises(SchedulerDataClearInProgressError):
                await service.schedule_once(
                    schedule_id="sensor-sync-manual:during-clear",
                    target_type=ScheduledTargetType.SENSOR_SYNC,
                    target_key="plugin:source",
                    run_at=time.time(),
                    target_payload={
                        "plugin_id": "plugin",
                        "source_type": "source",
                        "manual": True,
                    },
                )

        await asyncio.sleep(0)
        schedules = await service.repository.list_schedules(enabled_only=False)
        executions = await service.repository.list_executions(limit=20)

        assert counts["user_schedules"] == 1
        assert queued.message == "queued"
        assert blocked_execution.message == "data_clear_in_progress"
        assert enqueue_attempts == []
        assert service._background_tasks == set()
        assert [schedule.schedule_id for schedule in schedules] == ["system-maintenance"]
        assert service._scheduler.get_job("agent-task:stale") is None
        assert service._scheduler.get_job("system-maintenance") is not None
        assert executions == []

        recreated = await service.schedule(
            ScheduleDefinition(
                schedule_id="agent-task:after-clear",
                target_type=ScheduledTargetType.USER_AGENT_TASK,
                target_key="agent-task:after-clear",
                trigger=TriggerDefinition(
                    trigger_type=TriggerType.INTERVAL,
                    config={"seconds": 300.0},
                ),
                target_payload={"prompt": "New post-clear task."},
            )
        )
        assert recreated.schedule_id == "agent-task:after-clear"
        assert service._scheduler.get_job("agent-task:after-clear") is not None
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_system_handler_finishing_after_clear_cannot_restore_result_content(
    tmp_path,
):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    handler_started = asyncio.Event()
    release_handler = asyncio.Event()

    async def system_handler(
        context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        _ = context
        handler_started.set()
        await release_handler.wait()
        return ScheduledExecutionResult(
            success=True,
            message="private maintenance result",
            stats={"private_path": "/Users/example/Documents/secret.txt"},
        )

    service.register_handler(
        ScheduledTargetType.MEMORY_L2_MAINTENANCE,
        system_handler,
    )
    await service.start()
    try:
        await service.schedule_interval(
            schedule_id="system-maintenance-stale",
            target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key="global",
            seconds=300.0,
            target_payload={},
        )
        queued = await service.execute_schedule_async("system-maintenance-stale")
        assert queued.message == "queued"
        background_task = next(iter(service._background_tasks))
        await asyncio.wait_for(handler_started.wait(), timeout=2.0)

        async with service.user_data_clear_boundary():
            await service.clear_user_data()

        release_handler.set()
        await asyncio.wait_for(background_task, timeout=2.0)

        state = await service.get_target_state(
            ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            "global",
        )
        executions = await service.repository.list_executions(limit=20)
        schedule = await service.repository.get_schedule("system-maintenance-stale")

        assert state.running is False
        assert state.last_error is None
        assert state.stats == {}
        assert executions == []
        assert schedule is not None
        assert service._scheduler.get_job("system-maintenance-stale") is not None
    finally:
        release_handler.set()
        await service.stop()
