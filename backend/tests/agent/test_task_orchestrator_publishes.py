"""TaskOrchestrator should publish TaskStarted/TaskCompleted/TaskFailed events."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.events.events import EventTypes
from magi.events.domain_payloads import TaskContext, TaskStarted


def _build_orchestrator():
    """Construct an orchestrator with all dependencies mocked."""
    from magi.agent.task_orchestrator import TaskOrchestrator

    return TaskOrchestrator(
        runtime_key="test",
        tool_registry=MagicMock(),
        plan_subtasks=AsyncMock(),
        aggregate_orchestration=AsyncMock(),
        register_user_message=MagicMock(),
        parent_task_agent_type="chat",
    )


@pytest.mark.asyncio
async def test_publish_task_event_uses_lazy_bus():
    orch = _build_orchestrator()
    fake_bus = MagicMock()
    fake_bus.publish = AsyncMock(return_value=True)

    with patch("magi.core.container.Container.message_bus", return_value=fake_bus):
        if hasattr(orch, "_event_bus_cached"):
            delattr(orch, "_event_bus_cached")

        payload = TaskStarted(
            task_id="orch-1",
            task_type="chat",
            started_at=1.0,
            context=TaskContext("s", "t", "orch-1", "u"),
        )
        await orch._publish_task_event(
            event_type=EventTypes.TASK_STARTED, payload=payload
        )

    fake_bus.publish.assert_awaited_once()
    event = fake_bus.publish.await_args.args[0]
    assert event.type == EventTypes.TASK_STARTED
    assert event.data is payload


@pytest.mark.asyncio
async def test_publish_failure_does_not_propagate():
    orch = _build_orchestrator()
    fake_bus = MagicMock()
    fake_bus.publish = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("magi.core.container.Container.message_bus", return_value=fake_bus):
        if hasattr(orch, "_event_bus_cached"):
            delattr(orch, "_event_bus_cached")

        await orch._publish_task_event(
            event_type=EventTypes.TASK_STARTED,
            payload=TaskStarted(
                task_id="x",
                task_type="chat",
                started_at=1.0,
                context=TaskContext(None, None, "x", None),
            ),
        )
