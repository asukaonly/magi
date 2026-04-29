from __future__ import annotations

import time

import pytest

from magi.scheduler import (
    ScheduleDefinition,
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)
from magi.scheduler.service import SchedulerService
from magi.tools.builtin.schedule_tool import ScheduleTool
from magi.tools.schema import ToolErrorCode, ToolExecutionContext


def _context(tmp_path) -> ToolExecutionContext:
    return ToolExecutionContext(
        agent_id="chat:test",
        task_id="turn-1",
        workspace=str(tmp_path),
        env_vars={"user_id": "user-1", "session_id": "session-1"},
    )


@pytest.mark.asyncio
async def test_schedule_tool_adds_lists_and_runs_agent_task_schedule(tmp_path, monkeypatch) -> None:
    import magi.tools.builtin.schedule_tool as schedule_tool_module

    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    handled: list[str] = []

    async def handler(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        handled.append(context.schedule.target_payload["prompt"])
        return ScheduledExecutionResult(success=True, message="ran", stats={"handled": True})

    service.register_handler(ScheduledTargetType.USER_AGENT_TASK, handler)
    await service.start()
    monkeypatch.setattr(schedule_tool_module, "require_scheduler_service", lambda: service)

    tool = ScheduleTool()
    add_result = await tool.execute(
        {
            "action": "add",
            "schedule_id": "daily-summary",
            "seconds": 120,
            "kind": "agent_task",
            "prompt": "Summarize today's memory changes.",
            "tools_allow": "memory_query",
            "title": "Daily memory summary",
        },
        _context(tmp_path),
    )

    assert add_result.success is True
    schedule = add_result.data["schedule"]
    assert schedule["schedule_id"] == "agent-task:daily-summary"
    assert schedule["target_type"] == "user_agent_task"
    assert schedule["owner_kind"] == "agent_created"
    assert schedule["target_payload"]["selected_tools"] == ["memory_query"]
    assert schedule["target_payload"]["user_id"] == "user-1"
    assert schedule["target_payload"]["session_id"] == "session-1"

    list_result = await tool.execute(
        {"action": "list", "include_system": False},
        _context(tmp_path),
    )
    assert list_result.success is True
    assert [item["schedule_id"] for item in list_result.data["schedules"]] == ["agent-task:daily-summary"]

    run_result = await tool.execute(
        {"action": "run", "schedule_id": "agent-task:daily-summary"},
        _context(tmp_path),
    )

    assert run_result.success is True
    assert run_result.data["result"]["message"] == "ran"
    assert handled == ["Summarize today's memory changes."]

    await service.stop()


@pytest.mark.asyncio
async def test_schedule_tool_rejects_system_schedule_mutation(tmp_path, monkeypatch) -> None:
    import magi.tools.builtin.schedule_tool as schedule_tool_module

    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    await service.start()
    await service.schedule_interval(
        schedule_id="l2-maintenance",
        target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
        target_key="global",
        seconds=300,
        target_payload={},
    )
    monkeypatch.setattr(schedule_tool_module, "require_scheduler_service", lambda: service)

    result = await ScheduleTool().execute(
        {"action": "remove", "schedule_id": "l2-maintenance"},
        _context(tmp_path),
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.PERMISSION_DENIED.value
    assert "agent-created" in result.error

    await service.stop()


@pytest.mark.asyncio
async def test_schedule_tool_rejects_too_short_intervals(tmp_path, monkeypatch) -> None:
    import magi.tools.builtin.schedule_tool as schedule_tool_module

    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    await service.start()
    monkeypatch.setattr(schedule_tool_module, "require_scheduler_service", lambda: service)

    result = await ScheduleTool().execute(
        {
            "action": "add",
            "seconds": 10,
            "kind": "agent_task",
            "prompt": "Run far too often.",
        },
        _context(tmp_path),
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.INVALID_PARAMETERS.value
    assert "at least 60 seconds" in result.error

    await service.stop()


@pytest.mark.asyncio
async def test_schedule_tool_accepts_iso_once_schedule_object(tmp_path, monkeypatch) -> None:
    import magi.tools.builtin.schedule_tool as schedule_tool_module

    db_path = tmp_path / "scheduler.db"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    service = SchedulerService(db_path=db_path, runtime_dir=runtime_dir)
    service.register_handler(
        ScheduledTargetType.USER_AGENT_TASK,
        lambda context: ScheduledExecutionResult(success=True, message=context.schedule.schedule_id),
    )
    await service.start()
    monkeypatch.setattr(schedule_tool_module, "require_scheduler_service", lambda: service)

    result = await ScheduleTool().execute(
        {
            "action": "add",
            "schedule": {
                "title": "One shot",
                "trigger": {
                    "trigger_type": "once",
                    "config": {"run_at": time.time() + 600},
                },
                "target": {
                    "kind": "agent_task",
                    "prompt": "Check the plugin registry.",
                },
            },
        },
        _context(tmp_path),
    )

    assert result.success is True
    assert result.data["schedule"]["trigger"]["trigger_type"] == "once"

    await service.stop()
