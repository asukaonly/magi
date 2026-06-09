from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from magi.events.events import EventTypes
from magi.events.tracing import drain_pending


@pytest.mark.asyncio
async def test_planning_lazy_service_publishes():
    """Smoke: ChatPlanningService lazy _tool_invocation_service builds and publishes."""
    from magi.chat.task_agent.planning_service import ChatPlanningService

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

    from magi.agent.execution.tool_invocation_service import (
        InvocationContext,
        ToolCall,
    )
    from magi.events.domain_payloads import SpanCompleted, TaskContext

    with patch("magi.events.tracing._resolve_event_bus", return_value=bus):
        await svc.invoke(
            ToolCall(name="agent", args={"action": "launch", "subagent_type": "Plan"}),
            InvocationContext(
                tool_category="planning",
                task_context=TaskContext("s", None, None, "u"),
                execution_context=MagicMock(),
            ),
        )
        await drain_pending()

    registry.execute.assert_awaited_once()
    bus.publish.assert_awaited_once()
    event = bus.publish.await_args.args[0]
    assert event.type == EventTypes.SPAN_COMPLETED
    assert isinstance(event.data, SpanCompleted)
    assert event.data.node_type == "tool_invocation"
    assert event.data.attributes["tool_category"] == "planning"
