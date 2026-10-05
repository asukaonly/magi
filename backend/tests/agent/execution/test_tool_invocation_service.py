from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from magi.agent.execution.tool_invocation_service import (
    InvocationContext,
    ToolCall,
    ToolInvocationService,
)
from magi.events.events import EventTypes
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
@pytest.mark.parametrize("tool_succeeds", [False, True])
@pytest.mark.parametrize("publish_fails", [False, True])
async def test_invocation_result_and_trace_identity_survive_observer_failure(
    fake_bus, fake_registry, ctx, tool_succeeds, publish_fails
):
    from magi.tools.schema import ToolResult

    expected = ToolResult(
        success=tool_succeeds,
        data={"value": 0} if tool_succeeds else None,
        error=None if tool_succeeds else "boom",
        error_code=None if tool_succeeds else "E1",
    )
    fake_registry.execute = AsyncMock(return_value=expected)
    if publish_fails:
        fake_bus.publish.side_effect = RuntimeError("bus dead")
    with patch("magi.events.tracing._resolve_event_bus", return_value=fake_bus):
        result = await ToolInvocationService(fake_registry).invoke(
            ToolCall(name="probe", args={"path": "a.txt"}), ctx
        )
        await drain_pending()
    assert result is expected
    fake_registry.execute.assert_awaited_once_with(
        "probe", {"path": "a.txt"}, ctx.execution_context
    )
    fake_bus.publish.assert_awaited_once()
    event = fake_bus.publish.await_args.args[0]
    assert event.type == EventTypes.SPAN_COMPLETED
    payload = event.data
    assert isinstance(payload, SpanCompleted)
    assert (payload.node_type, payload.name, payload.status) == (
        "tool_invocation",
        "probe",
        "ok" if tool_succeeds else "error",
    )
    assert payload.attributes["tool_name"] == "probe"
    assert payload.attributes["tool_category"] == "external_tool"
    assert payload.attributes["success"] is tool_succeeds
    assert (payload.turn_id, payload.trace_id, payload.parent_span_id) == ("t", "trace:t", "t:turn")
    if not tool_succeeds:
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
async def test_modified_hook_without_authorizer_cannot_execute(fake_registry, ctx):
    fake_registry.execute = AsyncMock()
    with patch("magi.hooks.dispatch.dispatch_hook", new=AsyncMock(
        return_value=HookDecision.modify(arguments={"a": 2}),
    )):
        result = await ToolInvocationService(fake_registry).invoke(ToolCall("x", {"a": 1}), ctx)
    assert result.error_code == "HOOK_ARGUMENTS_NOT_AUTHORIZED"
    fake_registry.execute.assert_not_awaited()
