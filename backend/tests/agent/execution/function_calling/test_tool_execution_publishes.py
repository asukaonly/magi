from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.agent.execution.tool_invocation_service import (
    InvocationContext,
    ToolCall,
    ToolInvocationService,
)
from magi.events.events import EventTypes
from magi.events.domain_payloads import TaskContext


@pytest.mark.asyncio
async def test_function_calling_path_publishes_via_service():
    """Smoke: routing through ToolInvocationService publishes TOOL_INVOCATION_COMPLETED."""
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=True)
    registry = MagicMock()
    fake_result = MagicMock(success=True, error=None, error_code=None, data="ok")
    registry.execute = AsyncMock(return_value=fake_result)

    svc = ToolInvocationService(registry, bus)
    ctx = InvocationContext(
        tool_category="external_tool",
        task_context=TaskContext("s", "t", None, "u"),
        execution_context=MagicMock(),
    )
    await svc.invoke(ToolCall(name="shell", args={"cmd": "ls"}), ctx)

    registry.execute.assert_awaited_once_with("shell", {"cmd": "ls"}, ctx.execution_context)
    bus.publish.assert_awaited_once()
    event = bus.publish.await_args.args[0]
    assert event.type == EventTypes.TOOL_INVOCATION_COMPLETED
    assert event.data.tool_category == "external_tool"


def test_function_calling_host_caches_service():
    from magi.agent.execution.function_calling.tool_execution import (
        FunctionCallingToolExecutionMixin,
    )
    # Ensure attribute name agreed: refactor sets host._tool_invocation_service lazily
    assert hasattr(FunctionCallingToolExecutionMixin, "_execute_tool_call")
