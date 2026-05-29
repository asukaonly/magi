"""Phase C end-to-end smoke: NodeRegistry routes user-message turns
to the correct Node based on RouteDecision.graph_shape; the wrapped
handler runs as before; the final ExecutionResult flows back through
the coordinator unchanged."""
from __future__ import annotations

import pytest

from magi.agent.run.nodes.protocol import NodeOutcome
from magi.agent.run.nodes.plan_fanout import PlanFanoutNode
from magi.agent.run.nodes.reply import ReplyNode
from magi.agent.run.nodes.tool_loop import ToolLoopNode
from magi.agent.run.registry import NodeRegistry


def _build_registry_with_stubs():
    from magi.agent.task_agents.common.contracts import ExecutionMode, ExecutionResult

    class _StubDirect:
        async def execute(self, request):
            return ExecutionResult(mode=ExecutionMode.DIRECT_LLM, response_text="reply!")

    class _StubFC:
        async def execute(self, request):
            return ExecutionResult(mode=ExecutionMode.FUNCTION_CALLING, response_text="tool!")

    class _StubOrch:
        async def execute(self, request):
            return ExecutionResult(mode=ExecutionMode.ORCHESTRATION_LAUNCH, response_text="orch!")

    registry = NodeRegistry()
    registry.register(ReplyNode(direct_llm_handler=_StubDirect()))
    registry.register(ToolLoopNode(function_calling_handler=_StubFC()))
    registry.register(PlanFanoutNode(orchestration_launch_handler=_StubOrch()))
    return registry


@pytest.mark.asyncio
async def test_node_registry_dispatches_to_reply_node_for_graph_shape_reply() -> None:
    registry = _build_registry_with_stubs()
    reply_node = registry.get("reply")
    assert reply_node is not None
    result = await reply_node.execute(object())  # type: ignore[arg-type]
    assert result.outcome == NodeOutcome.DONE
    assert result.execution_result.response_text == "reply!"


@pytest.mark.asyncio
async def test_node_registry_dispatches_to_tool_loop_node_for_graph_shape_tool_loop() -> None:
    registry = _build_registry_with_stubs()
    node = registry.get("tool_loop")
    assert node is not None
    result = await node.execute(object())  # type: ignore[arg-type]
    assert result.execution_result.response_text == "tool!"


@pytest.mark.asyncio
async def test_node_registry_dispatches_to_plan_fanout_node_for_graph_shape_plan_fanout() -> None:
    registry = _build_registry_with_stubs()
    node = registry.get("plan_fanout")
    assert node is not None
    result = await node.execute(object())  # type: ignore[arg-type]
    assert result.execution_result.response_text == "orch!"


def test_node_registry_returns_none_for_non_route_execution_modes() -> None:
    """The registry intentionally has no entry for non-route shapes —
    coordinator falls back to the legacy ExecutionHandlerRegistry."""
    from magi.agent.task_agents.common.contracts import ExecutionMode, ExecutionResult

    class _StubDirect:
        async def execute(self, request):
            return ExecutionResult(mode=ExecutionMode.DIRECT_LLM, response_text="reply!")

    registry = NodeRegistry()
    registry.register(ReplyNode(direct_llm_handler=_StubDirect()))

    assert registry.get("orchestration_update") is None
    assert registry.get("explore_task_render") is None
    assert registry.get("fact_only") is None
