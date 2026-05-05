from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.agent.execution.tool_invocation_service import (
    InvocationContext,
    ToolCall,
    ToolInvocationService,
)
from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import ToolInvocationCompleted, TaskContext


@pytest.fixture
def fake_bus():
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=True)
    return bus


@pytest.fixture
def fake_registry():
    return MagicMock()


@pytest.fixture
def ctx():
    return InvocationContext(
        tool_category="external_tool",
        task_context=TaskContext("s", "t", None, "u"),
        execution_context=MagicMock(),
    )


@pytest.mark.asyncio
async def test_publishes_tool_invocation_completed_on_success(fake_bus, fake_registry, ctx):
    fake_result = MagicMock(success=True, error=None, error_code=None, data="ok")
    fake_registry.execute = AsyncMock(return_value=fake_result)

    svc = ToolInvocationService(fake_registry, fake_bus)
    result = await svc.invoke(ToolCall(name="shell", args={"cmd": "ls"}), ctx)

    assert result is fake_result
    fake_bus.publish.assert_awaited_once()
    event: Event = fake_bus.publish.await_args.args[0]
    assert event.type == EventTypes.TOOL_INVOCATION_COMPLETED
    payload: ToolInvocationCompleted = event.data
    assert isinstance(payload, ToolInvocationCompleted)
    assert payload.tool_name == "shell"
    assert payload.success is True
    assert payload.error is None
    assert payload.tool_category == "external_tool"
    assert event.correlation_id is not None  # Event auto-assigns via __post_init__


@pytest.mark.asyncio
async def test_publishes_failure_payload_when_result_failed(fake_bus, fake_registry, ctx):
    fake_result = MagicMock(success=False, error="boom", error_code="E1", data=None)
    fake_registry.execute = AsyncMock(return_value=fake_result)

    svc = ToolInvocationService(fake_registry, fake_bus)
    await svc.invoke(ToolCall(name="x", args={}), ctx)

    payload: ToolInvocationCompleted = fake_bus.publish.await_args.args[0].data
    assert payload.success is False
    assert payload.error is not None
    assert payload.error.message == "boom"


@pytest.mark.asyncio
async def test_publishes_and_reraises_when_execute_throws(fake_bus, fake_registry, ctx):
    fake_registry.execute = AsyncMock(side_effect=ValueError("kaboom"))

    svc = ToolInvocationService(fake_registry, fake_bus)
    with pytest.raises(ValueError):
        await svc.invoke(ToolCall(name="x", args={}), ctx)

    fake_bus.publish.assert_awaited_once()
    payload: ToolInvocationCompleted = fake_bus.publish.await_args.args[0].data
    assert payload.success is False
    assert payload.error is not None
    assert payload.error.type == "ValueError"


@pytest.mark.asyncio
async def test_publish_failure_does_not_break_caller(fake_bus, fake_registry, ctx):
    fake_registry.execute = AsyncMock(return_value=MagicMock(success=True, error=None))
    fake_bus.publish = AsyncMock(side_effect=RuntimeError("bus dead"))

    svc = ToolInvocationService(fake_registry, fake_bus)
    await svc.invoke(ToolCall(name="x", args={}), ctx)
