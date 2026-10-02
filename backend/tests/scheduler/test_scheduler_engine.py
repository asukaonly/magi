"""Exercise scheduling across real SQLite contention and runtime shutdown."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.events import EVENT_JOB_MAX_INSTANCES
from sqlalchemy import event

from magi.ipc.handlers import handle_ping
from magi.scheduler import SchedulerService, ScheduledExecutionResult, ScheduledTargetType


@pytest.mark.asyncio
async def test_due_job_lock_wait_keeps_runtime_responsive(tmp_path, monkeypatch):
    service = SchedulerService(db_path=tmp_path / "scheduler.db", runtime_dir=tmp_path)
    monkeypatch.setattr("magi.scheduler.service._get_scheduler_service", lambda: service)
    loop = asyncio.get_running_loop()
    handled = asyncio.Event()
    handler_loops = []

    async def handler(context):
        handler_loops.append(asyncio.get_running_loop())
        handled.set()
        return ScheduledExecutionResult(success=True)

    service.register_handler(ScheduledTargetType.MEMORY_L2_MAINTENANCE, handler)
    # Bound regressions without changing the production lock policy.
    @event.listens_for(service._jobstore_engine, "connect")
    def short_test_deadline(connection, record):
        connection.execute("PRAGMA busy_timeout = 1000")

    await service.start(paused=True)
    db = await aiosqlite.connect(tmp_path / "scheduler.db")
    attempted = threading.Event()
    try:
        await service.schedule_interval(
            schedule_id="lock-test", target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key="global", seconds=3600, target_payload={},
        )
        await service._scheduler_call(
            service._scheduler.modify_job, "lock-test",
            next_run_time=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        await db.execute("BEGIN IMMEDIATE")

        @event.listens_for(service._jobstore_engine, "before_cursor_execute")
        def observe_update(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("UPDATE apscheduler_jobs"):
                attempted.set()

        started = time.monotonic()
        await service.activate()
        assert await asyncio.to_thread(attempted.wait, 2)
        assert await asyncio.wait_for(handle_ping(None), timeout=0.2) == {"status": "pong"}
        # This commit needs the runtime loop: a synchronous scheduler on that loop
        # cannot reach it until its own SQLite lock wait times out.
        await db.commit()
        assert time.monotonic() - started < 0.75
        await asyncio.wait_for(handled.wait(), timeout=2)
        job = await service._scheduler_call(service._scheduler.get_job, "lock-test")
        assert job.next_run_time > datetime.now(timezone.utc)
        assert handler_loops == [loop]
    finally:
        await db.rollback()
        await db.close()
        await service.stop()


@pytest.mark.asyncio
async def test_scheduler_retries_failed_tick_on_its_thread(tmp_path, monkeypatch):
    service = SchedulerService(db_path=tmp_path / "scheduler.db", runtime_dir=tmp_path)
    await service.start(paused=True)
    service._scheduler.jobstore_retry_interval = 0.02
    original = BaseScheduler._process_jobs
    retried = threading.Event()
    attempts = []
    runtime_thread = threading.get_ident()

    def flaky_process_jobs(scheduler):
        attempts.append(threading.get_ident())
        if len(attempts) == 1:
            raise RuntimeError("Temporary job store failure")
        retried.set()
        return original(scheduler)

    monkeypatch.setattr(BaseScheduler, "_process_jobs", flaky_process_jobs)
    try:
        await service.activate()
        assert await asyncio.to_thread(retried.wait, 2)
        assert len(attempts) >= 2
        assert all(thread != runtime_thread for thread in attempts)
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_shutdown_drains_runtime_job_cleanup(tmp_path, monkeypatch):
    service = SchedulerService(db_path=tmp_path / "scheduler.db", runtime_dir=tmp_path)
    monkeypatch.setattr("magi.scheduler.service._get_scheduler_service", lambda: service)
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def handler(context):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.02)
            cleaned.set()
        return ScheduledExecutionResult(success=True)

    service.register_handler(ScheduledTargetType.MEMORY_L2_MAINTENANCE, handler)
    await service.start()
    scheduler_thread = service._scheduler._thread
    try:
        await service.schedule_once(
            schedule_id="shutdown-test", target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key="global", run_at=time.time() + 0.05, target_payload={},
        )
        await asyncio.wait_for(started.wait(), 2)
    finally:
        await service.stop()
    assert cleaned.is_set()
    assert not service._executor._tasks
    assert not scheduler_thread.is_alive()


@pytest.mark.asyncio
async def test_cancelled_scheduler_write_retains_owner_until_settled(tmp_path):
    service = SchedulerService(db_path=tmp_path / "scheduler.db", runtime_dir=tmp_path)
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    def blocking_write():
        entered.set()
        release.wait(2)
        completed.set()

    task = asyncio.create_task(service._scheduler_call(blocking_write))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert completed.is_set()


@pytest.mark.asyncio
async def test_scheduled_jobs_keep_instance_limit_and_can_restart(tmp_path, monkeypatch):
    service = SchedulerService(db_path=tmp_path / "scheduler.db", runtime_dir=tmp_path)
    monkeypatch.setattr("magi.scheduler.service._get_scheduler_service", lambda: service)
    loop = asyncio.get_running_loop()
    skipped = asyncio.Event()
    calls = []

    async def handler(context):
        calls.append(context)
        await asyncio.Event().wait()

    service.register_handler(ScheduledTargetType.MEMORY_L2_MAINTENANCE, handler)
    service._scheduler.add_listener(
        lambda event: loop.call_soon_threadsafe(skipped.set), EVENT_JOB_MAX_INSTANCES,
    )
    await service.start()
    try:
        await service.schedule_interval(
            schedule_id="bounded-test", target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key="global", seconds=0.03, target_payload={},
        )
        await asyncio.wait_for(skipped.wait(), 2)
        assert len(calls) == 1
    finally:
        await service.stop()

    await service.start(paused=True)
    try:
        assert await service.get_schedule("bounded-test") is not None
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_shutdown_and_due_tick_share_lock_order(tmp_path, monkeypatch):
    service = SchedulerService(db_path=tmp_path / "scheduler.db", runtime_dir=tmp_path)
    monkeypatch.setattr("magi.scheduler.service._get_scheduler_service", lambda: service)
    service.register_handler(
        ScheduledTargetType.MEMORY_L2_MAINTENANCE,
        lambda context: asyncio.sleep(0, result=ScheduledExecutionResult(success=True)),
    )
    entered = threading.Event()
    release = threading.Event()
    shutdown_entered = threading.Event()
    lock_timeouts = []
    original_lookup = service._scheduler._lookup_executor
    original_shutdown = service._scheduler.shutdown

    def gated_lookup(alias):
        entered.set()
        assert release.wait(2)
        # Bound the old lock inversion so a regression reports a failure, not a hang.
        lock = service._scheduler._executors_lock
        if not lock.acquire(timeout=0.5):
            lock_timeouts.append(alias)
            raise RuntimeError("Executor lock inversion")
        try:
            return original_lookup(alias)
        finally:
            lock.release()

    def observed_shutdown(*args, **kwargs):
        shutdown_entered.set()
        return original_shutdown(*args, **kwargs)

    await service.start(paused=True)
    stopping = None
    try:
        await service.schedule_once(
            schedule_id="shutdown-lock-order", target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key="global", run_at=time.time() - 1, target_payload={},
        )
        monkeypatch.setattr(service._scheduler, "_lookup_executor", gated_lookup)
        monkeypatch.setattr(service._scheduler, "shutdown", observed_shutdown)
        await service.activate()
        assert await asyncio.to_thread(entered.wait, 2)
        stopping = asyncio.create_task(service.stop())
        assert await asyncio.to_thread(shutdown_entered.wait, 2)
        # Let shutdown reach its first lock before the tick looks up its executor.
        await asyncio.sleep(0.05)
        release.set()
        await asyncio.wait_for(stopping, 3)
        assert not lock_timeouts
    finally:
        release.set()
        if stopping is not None:
            await stopping
        await service.stop()


@pytest.mark.asyncio
async def test_job_replacement_cannot_overwrite_concurrent_deadline_update(tmp_path, monkeypatch):
    service = SchedulerService(db_path=tmp_path / "scheduler.db", runtime_dir=tmp_path)
    await service.start(paused=True)
    snapshot_taken = threading.Event()
    release_snapshot = threading.Event()
    update_started = threading.Event()
    update_finished = threading.Event()
    replacement = None
    update = None
    try:
        schedule = await service.schedule_interval(
            schedule_id="replace-test", target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key="global", seconds=3600, target_payload={},
        )
        original_get_job = service._scheduler.get_job

        def paused_snapshot(*args, **kwargs):
            job = original_get_job(*args, **kwargs)
            snapshot_taken.set()
            release_snapshot.wait(2)
            return job

        monkeypatch.setattr(service._scheduler, "get_job", paused_snapshot)
        replacement = asyncio.create_task(service._upsert_job(schedule))
        assert await asyncio.to_thread(snapshot_taken.wait, 1)
        next_run = datetime.now(timezone.utc) + timedelta(hours=2)

        def advance_deadline():
            update_started.set()
            service._scheduler.modify_job("replace-test", next_run_time=next_run)
            update_finished.set()

        update = asyncio.create_task(asyncio.to_thread(advance_deadline))
        assert await asyncio.to_thread(update_started.wait, 1)
        assert not await asyncio.to_thread(update_finished.wait, 0.05)
        release_snapshot.set()
        await replacement
        await update
        job = await service._scheduler_call(original_get_job, "replace-test")
        assert job.next_run_time == next_run
    finally:
        release_snapshot.set()
        await asyncio.gather(*(task for task in (replacement, update) if task is not None))
        await service.stop()
