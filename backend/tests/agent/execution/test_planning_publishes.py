from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.events.events import EventTypes


@pytest.mark.asyncio
async def test_planning_lazy_service_publishes():
    """Smoke: ChatPlanningService lazy _tool_invocation_service builds and publishes."""
    from magi.agent.task_agents.chat.planning_service import ChatPlanningService

    host = ChatPlanningService.__new__(ChatPlanningService)
    registry = MagicMock()
    fake_result = MagicMock(success=True, error=None, error_code=None, data={"result": {}})
    registry.execute = AsyncMock(return_value=fake_result)
    host._tool_registry = registry

    svc = host._tool_invocation_service
    assert svc is not None
    assert host._tool_invocation_service is svc

    bus = MagicMock()
    bus.publish = AsyncMock(return_value=True)
    svc._event_bus = bus

    from magi.agent.execution.tool_invocation_service import (
        InvocationContext,
        ToolCall,
    )
    from magi.events.domain_payloads import TaskContext

    await svc.invoke(
        ToolCall(name="agent", args={"action": "launch", "subagent_type": "Plan"}),
        InvocationContext(
            tool_category="planning",
            task_context=TaskContext("s", None, None, "u"),
            execution_context=MagicMock(),
        ),
    )

    registry.execute.assert_awaited_once()
    bus.publish.assert_awaited_once()
    event = bus.publish.await_args.args[0]
    assert event.type == EventTypes.TOOL_INVOCATION_COMPLETED
    assert event.data.tool_category == "planning"
