from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from magi.agent.execution.tool_invocation_service import (
    InvocationContext,
    ToolCall,
    ToolInvocationService,
)
from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SpanCompleted, TaskContext
from magi.events.tracing import drain_pending
from magi.hooks.contracts import HookDecision


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
async def test_publishes_span_completed_on_success(fake_bus, fake_registry, ctx):
    fake_result = MagicMock(success=True, error=None, error_code=None, data="ok")
    fake_registry.execute = AsyncMock(return_value=fake_result)

    svc = ToolInvocationService(fake_registry)
    with patch("magi.events.tracing._resolve_event_bus", return_value=fake_bus):
        result = await svc.invoke(ToolCall(name="shell", args={"cmd": "ls"}), ctx)
        await drain_pending()

    assert result is fake_result
    fake_bus.publish.assert_awaited_once()
    event: Event = fake_bus.publish.await_args.args[0]
    assert event.type == EventTypes.SPAN_COMPLETED
    assert isinstance(event.data, SpanCompleted)
    payload: SpanCompleted = event.data
    assert payload.node_type == "tool_invocation"
    assert payload.name == "shell"
    assert payload.status == "ok"
    assert payload.attributes["tool_name"] == "shell"
    assert payload.attributes["tool_category"] == "external_tool"
    assert payload.attributes["success"] is True
    assert payload.turn_id == "t"
    assert payload.trace_id == "trace:t"
    assert payload.parent_span_id == "t:turn"


@pytest.mark.asyncio
async def test_publishes_failure_status_when_result_failed(fake_bus, fake_registry, ctx):
    fake_result = MagicMock(success=False, error="boom", error_code="E1", data=None)
    fake_registry.execute = AsyncMock(return_value=fake_result)

    svc = ToolInvocationService(fake_registry)
    with patch("magi.events.tracing._resolve_event_bus", return_value=fake_bus):
        await svc.invoke(ToolCall(name="x", args={}), ctx)
        await drain_pending()

    payload: SpanCompleted = fake_bus.publish.await_args.args[0].data
    assert payload.status == "error"
    assert payload.attributes["success"] is False
    assert payload.attributes["error_message"] == "boom"
    assert payload.attributes["error_code"] == "E1"


@pytest.mark.asyncio
async def test_publishes_and_reraises_when_execute_throws(fake_bus, fake_registry, ctx):
    fake_registry.execute = AsyncMock(side_effect=ValueError("kaboom"))

    svc = ToolInvocationService(fake_registry)
    with patch("magi.events.tracing._resolve_event_bus", return_value=fake_bus):
        with pytest.raises(ValueError):
            await svc.invoke(ToolCall(name="x", args={}), ctx)
        await drain_pending()

    payload: SpanCompleted = fake_bus.publish.await_args.args[0].data
    assert payload.status == "error"
    assert payload.error is not None
    assert payload.error.type == "ValueError"


@pytest.mark.asyncio
async def test_publish_failure_does_not_break_caller(fake_bus, fake_registry, ctx):
    fake_registry.execute = AsyncMock(return_value=MagicMock(success=True, error=None))
    fake_bus.publish = AsyncMock(side_effect=RuntimeError("bus dead"))

    svc = ToolInvocationService(fake_registry)
    with patch("magi.events.tracing._resolve_event_bus", return_value=fake_bus):
        # must not raise — publish failure is swallowed
        await svc.invoke(ToolCall(name="x", args={}), ctx)
        await drain_pending()


@pytest.mark.asyncio
async def test_pre_tool_hook_denial_skips_execution(fake_registry, ctx):
    fake_registry.execute = AsyncMock()

    svc = ToolInvocationService(fake_registry)
    with patch(
        "magi.hooks.dispatch.dispatch_hook",
        new=AsyncMock(return_value=HookDecision.deny("blocked")),
    ):
        result = await svc.invoke(ToolCall(name="x", args={"a": 1}), ctx)

    fake_registry.execute.assert_not_called()
    assert result.success is False
    assert result.error == "blocked"
    assert result.error_code == "HOOK_DENIED"


@pytest.mark.asyncio
async def test_pre_tool_hook_modification_updates_arguments(fake_registry, ctx):
    fake_result = MagicMock(success=True, error=None, error_code=None, data="ok")
    fake_registry.execute = AsyncMock(return_value=fake_result)
    ctx.authorize_call = AsyncMock(return_value=None)

    svc = ToolInvocationService(fake_registry)
    with patch(
        "magi.hooks.dispatch.dispatch_hook",
        new=AsyncMock(return_value=HookDecision.modify(arguments={"a": 2})),
    ):
        result = await svc.invoke(ToolCall(name="x", args={"a": 1}), ctx)

    assert result is fake_result
    assert ctx.authorize_call.await_args.args[0].args == {"a": 2}
    fake_registry.execute.assert_awaited_once_with("x", {"a": 2}, ctx.execution_context)


@pytest.mark.asyncio
async def test_modified_hook_without_authorizer_cannot_execute(fake_registry, ctx):
    fake_registry.execute = AsyncMock()
    with patch("magi.hooks.dispatch.dispatch_hook", new=AsyncMock(
        return_value=HookDecision.modify(arguments={"a": 2}),
    )):
        result = await ToolInvocationService(fake_registry).invoke(ToolCall("x", {"a": 1}), ctx)
    assert result.error_code == "HOOK_ARGUMENTS_NOT_AUTHORIZED"
    fake_registry.execute.assert_not_awaited()
