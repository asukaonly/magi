from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from agent.permission_helpers import AllowAllPermissionGateway
from magi.agent.execution import tool_invocation_service
from magi.agent.execution.function_calling import FunctionCallingOrchestrator, ToolCall
from magi.agent.execution.function_calling.step_models import FunctionCallingStepState, StepExecutionContext
from magi.agent.execution.function_calling.tool_batch_journal import FunctionCallingToolBatchJournal, ToolExecutionRecord
from magi.hooks.contracts import HookDecision
from magi.events.domain_payloads import SpanCompleted
from magi.events.events import EventTypes
from magi.events.tracing import drain_pending
from magi.tools.registry import ToolRegistry
from magi.tools.schema import Tool, ToolParameter, ToolResult, ToolSchema


class _EchoTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="echo",
            description="Return the supplied text",
            category="test",
            parameters=[ToolParameter(name="text", type="string", description="Text to return")],
            effect_class="read_only",
        )

    async def execute(self, parameters, context) -> ToolResult:
        return ToolResult(success=True, data=parameters["text"])


@pytest.fixture
def runtime(monkeypatch):
    registry = ToolRegistry()
    registry.register(_EchoTool)
    orchestrator = FunctionCallingOrchestrator(
        tool_registry=registry,
        permission_gateway=AllowAllPermissionGateway(),
    )
    bus = Mock(publish=AsyncMock(return_value=True))
    monkeypatch.setattr("magi.events.tracing._resolve_event_bus", lambda: bus)
    return orchestrator, bus


async def _execute(orchestrator, *, call_id: str, text: str):
    return await orchestrator._execute_tool_call(
        tool_call=ToolCall(id=call_id, name="echo", arguments={"text": text}),
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        execution_preset="chat",
        execution_agent_id="chat:user-1",
        execution_workspace=None,
        run_id="run-1",
    )


@pytest.mark.asyncio
async def test_function_calling_path_publishes_via_service(runtime):
    orchestrator, bus = runtime

    result = await _execute(orchestrator, call_id="call-1", text="first result")
    await drain_pending()

    assert result.success is True
    assert result.data == "first result"
    assert result.tool_call_id == "call-1"
    assert result.tool_name == "echo"
    bus.publish.assert_awaited_once()
    event = bus.publish.await_args.args[0]
    assert event.type == EventTypes.SPAN_COMPLETED
    assert isinstance(event.data, SpanCompleted)
    assert event.data.node_type == "tool_invocation"
    assert event.data.attributes["tool_category"] == "external_tool"
    assert event.data.attributes["tool_name"] == "echo"
    assert event.data.status == "ok"
    assert event.data.trace_id == "trace:turn-1"
    assert event.data.turn_id == "turn-1"


@pytest.mark.asyncio
async def test_function_calling_host_caches_service(runtime, monkeypatch):
    orchestrator, bus = runtime
    factory = Mock(wraps=tool_invocation_service.get_tool_invocation_service)
    monkeypatch.setattr(tool_invocation_service, "get_tool_invocation_service", factory)

    first = await _execute(orchestrator, call_id="call-1", text="first result")
    second = await _execute(orchestrator, call_id="call-2", text="second result")
    await drain_pending()

    assert first.success is True
    assert second.success is True
    assert (first.tool_call_id, first.data) == ("call-1", "first result")
    assert (second.tool_call_id, second.data) == ("call-2", "second result")
    factory.assert_called_once_with(orchestrator.tool_registry)
    assert bus.publish.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_action,final_action,expected_effect", [
    ("list", "set", "local_write"), ("set", "list", "read_only"),
])
async def test_tool_evidence_uses_authorized_action_after_hooks(
    runtime, monkeypatch, initial_action, final_action, expected_effect,
):
    orchestrator, _ = runtime
    tool = orchestrator.tool_registry.get_tool("echo")
    tool.schema.effect_class = "local_write"
    tool.schema.effect_replay_policy = "reconcilable"
    tool.schema.metadata["read_only_actions"] = ["list"]
    tool.schema.parameters.append(ToolParameter(
        name="action", type="string", description="Operation", enum=["list", "set"],
    ))
    monkeypatch.setattr("magi.hooks.dispatch.dispatch_hook", AsyncMock(
        return_value=HookDecision.modify(arguments={"text": "result", "action": final_action}),
    ))
    call = ToolCall(id="call", name="echo", arguments={"text": "result", "action": initial_action})
    result = await orchestrator._execute_tool_call(
        tool_call=call, user_id="user-1", session_id="session-1", turn_id="turn-1",
        execution_preset="chat", execution_agent_id="chat:user-1", execution_workspace=None, run_id="run-1",
    )
    assert result.success
    assert result.effect_metadata.effect_class.value == expected_effect
    state = FunctionCallingStepState(messages=[], effective_system_prompt="system", tools=[])
    await FunctionCallingToolBatchJournal(orchestrator).record_execution(
        state=state, record=ToolExecutionRecord(tool_call=call, result=result, fingerprint="call"),
        ctx=StepExecutionContext(
            user_message="test", user_id="user-1", session_id="session-1", turn_id="turn-1",
            run_id="run-1", run_revision=0, execution_preset="chat", execution_agent_id="chat:user-1",
            execution_workspace=None,
        ), iteration=1,
    )
    assert state.tool_evidence[0].effect_class == expected_effect
    await drain_pending()
