from __future__ import annotations

import time

import pytest

from magi.scheduler import SchedulerService, ScheduledExecutionContext, ScheduledExecutionResult, ScheduledTargetType


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
    service.register_handler(ScheduledTargetType.AGENT_TASK, handler)
    await service.start()

    await service.schedule_interval(
        schedule_id="agent-task-1",
        target_type=ScheduledTargetType.AGENT_TASK,
        target_key="chat:default",
        seconds=300.0,
        target_payload={"agent_type": "chat", "agent_id": "default", "event_type": "ScheduledAgentTask"},
    )
    await service.trigger_now("agent-task-1")

    schedule = await service.repository.get_schedule("agent-task-1")
    state = await service.get_target_state(ScheduledTargetType.AGENT_TASK, "chat:default")

    assert schedule is not None
    assert schedule.trigger.trigger_type.value == "interval"
    assert schedule.job_id == "agent-task-1"
    assert handled == ["agent-task-1"]
    assert state.last_success_at is not None
    assert state.next_run_at is not None

    await service.stop()

    restored = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    restored.register_handler(ScheduledTargetType.AGENT_TASK, handler)
    await restored.start()

    restored_schedule = await restored.repository.get_schedule("agent-task-1")

    assert restored_schedule is not None
    assert restored._scheduler.get_job("agent-task-1") is not None

    await restored.stop()


@pytest.mark.asyncio
async def test_scheduler_service_supports_once_and_cron_and_replaces_existing_schedule(tmp_path):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)

    async def handler(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        return ScheduledExecutionResult(success=True, message=context.schedule.schedule_id)

    service.register_handler(ScheduledTargetType.ACTION_DISPATCH, handler)
    await service.start()

    await service.schedule_once(
        schedule_id="action-once",
        target_type=ScheduledTargetType.ACTION_DISPATCH,
        target_key="notify-user",
        run_at=time.time() + 60.0,
        target_payload={"action_id": "notify-user"},
    )
    await service.schedule_cron(
        schedule_id="action-cron",
        target_type=ScheduledTargetType.ACTION_DISPATCH,
        target_key="send-email",
        cron={"minute": "15", "hour": "8"},
        target_payload={"action_id": "send-email"},
    )
    await service.schedule_interval(
        schedule_id="action-cron",
        target_type=ScheduledTargetType.ACTION_DISPATCH,
        target_key="send-email",
        seconds=120.0,
        target_payload={"action_id": "send-email"},
    )

    once_schedule = await service.repository.get_schedule("action-once")
    replaced_schedule = await service.repository.get_schedule("action-cron")

    assert once_schedule is not None
    assert once_schedule.trigger.trigger_type.value == "once"
    assert replaced_schedule is not None
    assert replaced_schedule.trigger.trigger_type.value == "interval"
    assert replaced_schedule.trigger.config["seconds"] == 120.0

    await service.stop()


@pytest.mark.asyncio
async def test_unschedule_clears_stale_target_errors(tmp_path):
    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)

    async def handler(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        raise RuntimeError("boom")

    service.register_handler(ScheduledTargetType.AGENT_TASK, handler)
    await service.start()

    await service.schedule_interval(
        schedule_id="agent-task-error",
        target_type=ScheduledTargetType.AGENT_TASK,
        target_key="chat:error",
        seconds=300.0,
        target_payload={"agent_type": "chat", "agent_id": "error", "event_type": "ScheduledAgentTask"},
    )

    with pytest.raises(RuntimeError):
        await service.trigger_now("agent-task-error")

    failed_state = await service.get_target_state(ScheduledTargetType.AGENT_TASK, "chat:error")
    assert failed_state.last_error == "boom"

    await service.unschedule("agent-task-error")
    cleared_state = await service.get_target_state(ScheduledTargetType.AGENT_TASK, "chat:error")

    assert cleared_state.last_error is None
    assert cleared_state.scheduler_job_id is None
    assert cleared_state.next_run_at is None

    await service.stop()
