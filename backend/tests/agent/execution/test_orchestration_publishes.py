from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from magi.agent.task_orchestration_workers import TaskOrchestrationWorkerMixin
from magi.events.events import EventTypes
from magi.events.tracing import drain_pending


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

    bus = MagicMock()
    bus.publish = AsyncMock(return_value=True)

    from magi.agent.execution.tool_invocation_service import (
        InvocationContext,
        ToolCall,
    )
    from magi.events.domain_payloads import SpanCompleted, TaskContext

    with patch("magi.events.tracing._resolve_event_bus", return_value=bus):
        await svc.invoke(
            ToolCall(name="agent", args={"action": "launch"}),
            InvocationContext(
                tool_category="orchestrator_internal",
                task_context=TaskContext("s", "t", "orch-1", "u"),
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
    assert event.data.attributes["tool_category"] == "orchestrator_internal"
    assert event.data.attributes["task_id"] == "orch-1"
