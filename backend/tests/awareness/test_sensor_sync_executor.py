from __future__ import annotations

import asyncio
import sqlite3
import threading
import time

import pytest

from magi.awareness.lifecycle import SensorSyncExecutorModule
from magi.awareness.sensor_sync_executor import (
    SensorSyncExecutor,
    SensorSyncExecutorState,
)
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.scheduler import (
    ScheduleDefinition,
    ScheduledExecutionResult,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)
from magi.scheduler.repository import ScheduleRepository


def _build_sensor_schedule(
    *,
    plugin_id: str = "test-plugin",
    source_type: str = "test-source",
    target_payload: dict[str, object] | None = None,
) -> ScheduleDefinition:
    payload = {
        "plugin_id": plugin_id,
        "source_type": source_type,
        "manual": False,
    }
    if target_payload:
        payload.update(target_payload)
    return ScheduleDefinition(
        schedule_id=f"sensor-sync:{plugin_id}:{source_type}",
        target_type=ScheduledTargetType.SENSOR_SYNC,
        target_key=f"{plugin_id}:{source_type}",
        trigger=TriggerDefinition(
            trigger_type=TriggerType.INTERVAL,
            config={"seconds": 300.0},
        ),
        target_payload=payload,
        metadata={"plugin_id": plugin_id, "source_type": source_type},
    )


async def _enqueue_job(repository: ScheduleRepository, schedule: ScheduleDefinition) -> str:
    await repository.upsert_schedule(schedule)
    admitted = await repository.enqueue_sensor_sync_execution(
        schedule=schedule,
        manual=False,
        started_at=time.time(),
    )
    assert admitted is not None
    return admitted.job_id


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


class _StoppingExecutor:
    def __init__(self) -> None:
        self.state = SensorSyncExecutorState.STOPPING
        self.timeout = True

    async def stop(self) -> None:
        if self.timeout:
            raise TimeoutError("worker still running")
        self.state = SensorSyncExecutorState.STOPPED


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
    )
    await executor.start()
    await _wait_for_job_status(repository, job_id, "success")
    await executor.stop()

    assert observed_loop_ids == [id(owner_loop)]


@pytest.mark.asyncio
async def test_sensor_sync_stop_timeout_retains_worker_and_blocks_restart(tmp_path):
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    job_id = await _enqueue_job(repository, schedule)
    run_started = asyncio.Event()
    release_run = asyncio.Event()
    run_calls = 0

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        nonlocal run_calls
        assert job_record["job_id"] == job_id
        run_calls += 1
        run_started.set()
        await release_run.wait()
        return ScheduledExecutionResult(success=True, message="released")

    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        poll_interval_seconds=0.01,
        stop_timeout_seconds=0.2,
    )
    await executor.start()
    await asyncio.wait_for(run_started.wait(), timeout=2.0)
    worker_thread = executor._thread
    worker_loop = executor._loop
    owner_loop = executor._owner_loop

    try:
        with pytest.raises(TimeoutError, match="existing worker is still running"):
            await executor.stop()

        assert executor.state is SensorSyncExecutorState.STOPPING
        assert executor._thread is worker_thread
        assert worker_thread is not None and worker_thread.is_alive()
        assert executor._loop is worker_loop
        assert executor._owner_loop is owner_loop

        with pytest.raises(RuntimeError, match="still stopping"):
            await executor.start()
        await asyncio.sleep(0.05)
        assert run_calls == 1

        release_run.set()
        await executor.stop()
    finally:
        release_run.set()
        if executor.state is not SensorSyncExecutorState.STOPPED:
            await executor.stop()

    completed_job = await _wait_for_job_status(repository, job_id, "success")
    assert completed_job["result_message"] == "released"
    assert run_calls == 1
    assert executor.state is SensorSyncExecutorState.STOPPED
    assert executor._thread is None
    assert executor._loop is None
    assert executor._owner_loop is None


@pytest.mark.asyncio
async def test_sensor_sync_executor_can_restart_after_timed_out_worker_exits(tmp_path):
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    job_id = await _enqueue_job(repository, schedule)
    run_started = asyncio.Event()
    release_run = asyncio.Event()

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        assert job_record["job_id"] == job_id
        run_started.set()
        await release_run.wait()
        return ScheduledExecutionResult(success=True, message="released")

    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        poll_interval_seconds=0.01,
        stop_timeout_seconds=0.2,
    )
    await executor.start()
    await asyncio.wait_for(run_started.wait(), timeout=2.0)
    with pytest.raises(TimeoutError):
        await executor.stop()

    release_run.set()
    await executor.stop()
    assert executor.state is SensorSyncExecutorState.STOPPED

    await executor.start()
    assert executor.state is SensorSyncExecutorState.RUNNING
    await executor.stop()
    assert executor.state is SensorSyncExecutorState.STOPPED
    await executor.stop()
    assert executor.state is SensorSyncExecutorState.STOPPED


@pytest.mark.asyncio
async def test_executor_module_keeps_timed_out_worker_for_later_shutdown() -> None:
    context = RuntimeBootstrapContext()
    module = SensorSyncExecutorModule(context)
    executor = _StoppingExecutor()
    module._executor = executor
    context.agent_runtime.sensor_sync_executor = executor

    with pytest.raises(TimeoutError, match="worker still running"):
        await module.shutdown()

    assert module._executor is executor
    assert context.agent_runtime.sensor_sync_executor is executor

    executor.timeout = False
    await module.shutdown()

    assert module._executor is None
    assert context.agent_runtime.sensor_sync_executor is None


@pytest.mark.asyncio
async def test_executor_module_rejects_restart_while_previous_worker_is_stopping() -> None:
    context = RuntimeBootstrapContext()
    module = SensorSyncExecutorModule(context)
    executor = _StoppingExecutor()
    module._executor = executor
    context.agent_runtime.sensor_sync_executor = executor

    with pytest.raises(RuntimeError, match="has not stopped"):
        await module.init()

    assert module._executor is executor
    assert context.agent_runtime.sensor_sync_executor is executor


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
    assert backfill_calls[0]["max_periods"] == 4


@pytest.mark.asyncio
async def test_sensor_sync_l3_backfill_does_not_block_next_sensor_job(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    first_schedule = _build_sensor_schedule(source_type="slow-backfill-source")
    second_schedule = _build_sensor_schedule(source_type="next-source")
    first_job_id = await _enqueue_job(repository, first_schedule)
    second_job_id = await _enqueue_job(repository, second_schedule)
    backfill_started = threading.Event()
    release_backfill = threading.Event()

    class _FakeL1:
        async def summarize_event_sources(self, **kwargs):
            return [
                {
                    "source": "slow-backfill-source",
                    "event_count": 5,
                    "avg_importance": 0.5,
                    "min_timestamp": 1000.0,
                    "max_timestamp": 2000.0,
                }
            ]

    class _FakeUnifiedMemory:
        l1 = _FakeL1()

        async def backfill_l3_gaps(self, **kwargs):
            backfill_started.set()
            await asyncio.to_thread(release_backfill.wait)
            return {"generated": [], "skipped_existing": 0, "skipped_sparse": 0}

    monkeypatch.setattr(
        "magi.memory.provider.get_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        return ScheduledExecutionResult(success=True, message=f"completed:{job_record['source_type']}")

    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        poll_interval_seconds=0.01,
    )
    try:
        await executor.start()
        await _wait_for_job_status(repository, first_job_id, "success")
        assert await asyncio.to_thread(backfill_started.wait, 1.0)

        second_job = await _wait_for_job_status(
            repository,
            second_job_id,
            "success",
            timeout_seconds=0.3,
        )
    finally:
        release_backfill.set()
        await executor.stop()

    assert second_job["result_message"] == "completed:next-source"


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

    derive_calls: list[str] = []
    summarize_calls: list[dict[str, object]] = []
    second_started = asyncio.Event()
    release_second = asyncio.Event()
    run_job_ids: list[str] = []

    async def _fake_execute_schedule_async(schedule_id: str, *, manual: bool = True, **kwargs):
        derive_calls.append(schedule_id)
        return ScheduledExecutionResult(success=True, message="queued", stats={})

    class _FakeSchedulerService:
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
            return {"generated": [], "skipped_existing": 0, "skipped_sparse": 0}

    monkeypatch.setattr(
        "magi.memory.provider.get_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        run_job_ids.append(str(job_record["job_id"]))
        if len(run_job_ids) == 1:
            assert job_record["job_id"] == job_id
            return ScheduledExecutionResult(
                success=True,
                message="sensor_sync_completed",
                next_cursor="cursor-2",
                stats={"items": 200, "has_more": True},
            )
        second_started.set()
        await release_second.wait()
        return ScheduledExecutionResult(
            success=True,
            message="sensor_sync_completed",
            next_cursor="cursor-3",
            stats={"items": 20, "has_more": False},
        )

    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        scheduler_service=_FakeSchedulerService(),
        poll_interval_seconds=0.01,
    )
    await executor.start()
    await _wait_for_job_status(repository, job_id, "success")
    await asyncio.wait_for(second_started.wait(), timeout=2.0)
    continuation = await repository.get_outstanding_sensor_sync_job(
        schedule.target_type,
        schedule.target_key,
    )
    assert continuation is not None
    continuation_job_id = str(continuation["job_id"])
    assert continuation_job_id != job_id
    assert continuation["status"] == "running"
    assert str(continuation["schedule_id"]).startswith(
        "sensor-sync-continuation:test-plugin:test-source:"
    )
    assert continuation["payload"] == {
        "plugin_id": "test-plugin",
        "source_type": "test-source",
        "manual": False,
    }
    assert summarize_calls == []
    assert derive_calls == []

    release_second.set()
    await _wait_for_job_status(repository, continuation_job_id, "success")
    deadline = time.time() + 2.0
    while time.time() < deadline and not derive_calls:
        await asyncio.sleep(0.02)
    await executor.stop()

    assert run_job_ids == [job_id, continuation_job_id]
    assert len(summarize_calls) == 1
    assert len(derive_calls) == 1


@pytest.mark.asyncio
async def test_sensor_sync_continuation_preserves_backfill_request(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    sync_request = {
        "mode": "backfill",
        "backfill_scope": "last_30_days",
        "backfill_days": 30,
    }
    schedule = _build_sensor_schedule(target_payload={"sync_request": sync_request})
    job_id = await _enqueue_job(repository, schedule)
    run_jobs: list[dict[str, object]] = []

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
        run_jobs.append(job_record)
        assert dict(job_record["payload"])["sync_request"] == sync_request
        if len(run_jobs) > 1:
            return ScheduledExecutionResult(
                success=True,
                message="sensor_sync_completed",
                next_cursor="cursor-3",
                stats={"items": 20, "has_more": False},
            )
        return ScheduledExecutionResult(
            success=True,
            message="sensor_sync_completed",
            next_cursor="cursor-2",
            stats={"items": 200, "has_more": True},
        )

    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        scheduler_service=None,
        poll_interval_seconds=0.01,
    )
    await executor.start()
    await _wait_for_job_status(repository, job_id, "success")
    deadline = time.time() + 2.0
    continuation = None
    while time.time() < deadline:
        latest = await repository.get_latest_sensor_sync_job(
            schedule.target_type,
            schedule.target_key,
        )
        if latest is not None and latest["job_id"] != job_id and latest["status"] == "success":
            continuation = latest
            break
        await asyncio.sleep(0.02)
    await executor.stop()

    assert continuation is not None
    assert len(run_jobs) == 2
    assert str(continuation["schedule_id"]).startswith(
        "sensor-sync-continuation:test-plugin:test-source:"
    )
    assert dict(continuation["payload"])["sync_request"] == sync_request


@pytest.mark.asyncio
async def test_first_context_sensor_sync_does_not_queue_continuation(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule(target_payload={"first_context": True})
    job_id = await _enqueue_job(repository, schedule)

    class _FakeSchedulerService:
        async def execute_schedule_async(self, *args, **kwargs):
            return ScheduledExecutionResult(success=True, message="queued", stats={})

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        assert job_record["job_id"] == job_id
        assert dict(job_record["payload"])["first_context"] is True
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
    )
    await executor.start()
    await _wait_for_job_status(repository, job_id, "success")
    await asyncio.sleep(0.05)
    await executor.stop()

    outstanding = await repository.get_outstanding_sensor_sync_job(
        schedule.target_type,
        schedule.target_key,
    )
    latest = await repository.get_latest_sensor_sync_job(
        schedule.target_type,
        schedule.target_key,
    )
    assert outstanding is None
    assert latest is not None
    assert latest["job_id"] == job_id


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
    )
    await executor.start()
    completed_job = await _wait_for_job_status(repository, job_id, "success")
    await executor.stop()

    # The sync must still be committed as success despite the scheduler crash
    assert completed_job["result_message"] == "sensor_sync_completed"
    assert completed_job["status"] == "success"


@pytest.mark.asyncio
async def test_sensor_sync_executor_recovers_recent_running_job_on_startup(tmp_path):
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule()
    job_id = await _enqueue_job(repository, schedule)
    claimed = await repository.claim_next_sensor_sync_job(claimed_by="stale-executor")
    assert claimed is not None

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
    )
    await executor.start()
    completed_job = await _wait_for_job_status(repository, job_id, "success")
    await executor.stop()

    assert completed_job["result_message"] == "recovered"
    assert completed_job["attempt_count"] == 2


@pytest.mark.asyncio
async def test_sensor_sync_executor_retries_transient_failure_until_success(tmp_path):
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule()
    job_id = await _enqueue_job(repository, schedule)
    job = await repository.get_sensor_sync_job(job_id)
    assert job is not None
    execution_id = str(job["execution_id"])
    attempt_count = 0

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            raise RuntimeError("temporary source failure")
        return ScheduledExecutionResult(
            success=True,
            message="recovered",
            stats={"items": 1},
        )

    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        poll_interval_seconds=0.01,
        retry_base_seconds=0.0,
        max_attempts=3,
    )
    await executor.start()
    completed_job = await _wait_for_job_status(repository, job_id, "success")
    await executor.stop()

    execution_status, execution_message = _load_execution_status(db_path, execution_id)
    target_state = await repository.get_target_state(schedule.target_type, schedule.target_key)
    assert attempt_count == 2
    assert completed_job["attempt_count"] == 2
    assert completed_job["error"] is None
    assert execution_status == "success"
    assert execution_message == "recovered"
    assert target_state.running is False
    assert target_state.last_error is None


@pytest.mark.asyncio
async def test_sensor_sync_executor_fails_after_retry_budget_is_exhausted(tmp_path):
    db_path = tmp_path / "scheduler.db"
    repository = ScheduleRepository(db_path)
    await repository.initialize()
    schedule = _build_sensor_schedule()
    job_id = await _enqueue_job(repository, schedule)
    job = await repository.get_sensor_sync_job(job_id)
    assert job is not None
    execution_id = str(job["execution_id"])
    attempt_count = 0

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        nonlocal attempt_count
        attempt_count += 1
        raise RuntimeError("persistent source failure")

    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        poll_interval_seconds=0.01,
        retry_base_seconds=0.0,
        max_attempts=3,
    )
    await executor.start()
    failed_job = await _wait_for_job_status(repository, job_id, "failed")
    await executor.stop()

    execution_status, execution_message = _load_execution_status(db_path, execution_id)
    target_state = await repository.get_target_state(schedule.target_type, schedule.target_key)
    assert attempt_count == 3
    assert failed_job["attempt_count"] == 3
    assert failed_job["error"] == "persistent source failure"
    assert execution_status == "failed"
    assert execution_message is None
    assert target_state.running is False
    assert target_state.last_error == "persistent source failure"


@pytest.mark.asyncio
async def test_sensor_sync_executor_retries_when_success_settlement_is_temporarily_unavailable(
    tmp_path,
    monkeypatch,
):
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    job_id = await _enqueue_job(repository, schedule)
    run_attempts = 0
    settlement_attempts = 0
    settle_success = repository.settle_sensor_sync_job_success

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        nonlocal run_attempts
        run_attempts += 1
        return ScheduledExecutionResult(success=True, message="committed")

    async def flaky_settle_success(*args, **kwargs):
        nonlocal settlement_attempts
        settlement_attempts += 1
        if settlement_attempts == 1:
            raise RuntimeError("scheduler database temporarily unavailable")
        return await settle_success(*args, **kwargs)

    monkeypatch.setattr(
        repository,
        "settle_sensor_sync_job_success",
        flaky_settle_success,
    )
    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        poll_interval_seconds=0.01,
        retry_base_seconds=0.0,
        max_attempts=3,
    )

    await executor.start()
    completed_job = await _wait_for_job_status(repository, job_id, "success")
    await executor.stop()

    assert run_attempts == 2
    assert settlement_attempts == 2
    assert completed_job["attempt_count"] == 2


@pytest.mark.asyncio
async def test_sensor_sync_executor_recovers_when_failure_settlement_is_interrupted(
    tmp_path,
    monkeypatch,
):
    repository = ScheduleRepository(tmp_path / "scheduler.db")
    await repository.initialize()
    schedule = _build_sensor_schedule()
    job_id = await _enqueue_job(repository, schedule)
    run_attempts = 0
    settlement_attempts = 0
    settle_failure = repository.settle_sensor_sync_job_failure

    async def run_job(job_record: dict[str, object]) -> ScheduledExecutionResult:
        nonlocal run_attempts
        run_attempts += 1
        if run_attempts == 1:
            raise RuntimeError("temporary source failure")
        return ScheduledExecutionResult(success=True, message="recovered")

    async def flaky_settle_failure(*args, **kwargs):
        nonlocal settlement_attempts
        settlement_attempts += 1
        if settlement_attempts == 1:
            raise RuntimeError("scheduler database temporarily unavailable")
        return await settle_failure(*args, **kwargs)

    monkeypatch.setattr(
        repository,
        "settle_sensor_sync_job_failure",
        flaky_settle_failure,
    )
    executor = SensorSyncExecutor(
        repository=repository,
        run_job=run_job,
        poll_interval_seconds=0.01,
        retry_base_seconds=0.0,
        max_attempts=3,
    )

    await executor.start()
    completed_job = await _wait_for_job_status(repository, job_id, "success")
    await executor.stop()

    assert run_attempts == 2
    assert settlement_attempts == 1
    assert completed_job["attempt_count"] == 2
