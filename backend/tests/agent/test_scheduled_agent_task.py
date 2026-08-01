from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.agent.background.contracts import BackgroundTaskTriggerSource
from magi.agent.scheduled_agent_task import (
    UserAgentTaskScheduleContributor,
    build_background_spec_from_schedule,
)
from magi.scheduler import (
    ScheduleDefinition,
    ScheduledExecutionContext,
    ScheduledTargetState,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)


def _context() -> ScheduledExecutionContext:
    schedule = ScheduleDefinition(
        schedule_id="agent-task:test",
        target_type=ScheduledTargetType.USER_AGENT_TASK,
        target_key="agent-task:test",
        trigger=TriggerDefinition(TriggerType.INTERVAL, {"seconds": 300}),
        target_payload={
            "prompt": "Summarize project state.",
            "title": "Project summary",
            "selected_tools": ["memory_query"],
            "user_id": "user-1",
            "session_id": "session-1",
            "workspace_path": "D:/code/magi",
            "timeout_seconds": 900,
            "max_iterations": 12,
        },
        metadata={"display_name": "Project summary"},
    )
    return ScheduledExecutionContext(
        schedule=schedule,
        target_state=ScheduledTargetState(
            target_type=ScheduledTargetType.USER_AGENT_TASK,
            target_key="agent-task:test",
        ),
        runtime_dir=Path("."),
        triggered_at=1.0,
    )


def test_build_background_spec_from_schedule() -> None:
    spec = build_background_spec_from_schedule(_context())

    assert spec.user_id == "user-1"
    assert spec.session_id == "session-1"
    assert spec.origin_turn_id == "agent-task:test"
    assert spec.title == "Project summary"
    assert spec.goal == "Summarize project state."
    assert spec.selected_tools == ["memory_query"]
    assert spec.workspace_path == "D:/code/magi"
    assert spec.timeout_seconds == 900
    assert spec.max_iterations == 12
    assert spec.trigger_source is BackgroundTaskTriggerSource.SCHEDULE
    # ADR-0004 P3: scheduler also speaks RunTrigger (additive, alongside the
    # legacy trigger_source enum).
    assert spec.trigger is not None
    assert spec.trigger.trigger_type == "scheduled"
    assert spec.trigger.requester == "user-1"
    assert spec.trigger.correlation == ["agent-task:test"]


@pytest.mark.asyncio
async def test_user_agent_task_contributor_enqueues_background_task() -> None:
    enqueued = []
    admitted_generations = []

    class FakeBackgroundManager:
        async def enqueue(self, spec):
            enqueued.append(spec)
            return SimpleNamespace(task_id="bg_123")

    class FakeScheduler:
        def register_handler(self, target_type, handler):
            assert target_type is ScheduledTargetType.USER_AGENT_TASK
            self.handler = handler

        async def run_user_agent_effect(self, data_generation, operation):
            admitted_generations.append(data_generation)
            return await operation()

    contributor = UserAgentTaskScheduleContributor(FakeBackgroundManager())
    scheduler = FakeScheduler()
    await contributor.register_schedules(scheduler)  # type: ignore[arg-type]
    result = await contributor._handle_user_agent_task(_context())

    assert result.success is True
    assert result.message == "background_task_enqueued"
    assert result.stats == {"background_task_id": "bg_123"}
    assert admitted_generations == [0]
    assert enqueued[0].goal == "Summarize project state."
