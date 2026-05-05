from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.agent.task_orchestration_workers import TaskOrchestrationWorkerMixin
from magi.events.events import EventTypes


@pytest.mark.asyncio
async def test_orchestrator_lazy_service_publishes():
    """Smoke: lazy _tool_invocation_service property builds a service that publishes."""
    host = TaskOrchestrationWorkerMixin.__new__(TaskOrchestrationWorkerMixin)
    registry = MagicMock()
    fake_result = MagicMock(success=True, error=None, error_code=None, data={"worker_ids": ["w1"]})
    registry.execute = AsyncMock(return_value=fake_result)
    host._tool_registry = registry

    svc = host._tool_invocation_service
    assert svc is not None
    # Cached on second access.
    assert host._tool_invocation_service is svc

    # Patch the bus on the cached service.
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=True)
    svc._event_bus = bus

    from magi.agent.execution.tool_invocation_service import (
        InvocationContext,
        ToolCall,
    )
    from magi.events.domain_payloads import TaskContext

    await svc.invoke(
        ToolCall(name="agent", args={"action": "launch"}),
        InvocationContext(
            tool_category="orchestrator_internal",
            task_context=TaskContext("s", "t", "orch-1", "u"),
            execution_context=MagicMock(),
        ),
    )

    registry.execute.assert_awaited_once()
    bus.publish.assert_awaited_once()
    event = bus.publish.await_args.args[0]
    assert event.type == EventTypes.TOOL_INVOCATION_COMPLETED
    assert event.data.tool_category == "orchestrator_internal"
    assert event.data.context.task_id == "orch-1"
