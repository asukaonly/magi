"""ToolLoopNode adapter tests."""
from __future__ import annotations

import pytest

from magi.agent.run.nodes.protocol import NodeOutcome, RunNode
from magi.agent.run.nodes.tool_loop import ToolLoopNode


def test_tool_loop_node_declares_node_type_tool_loop() -> None:
    assert ToolLoopNode.node_type == "tool_loop"


def test_tool_loop_node_is_a_run_node_protocol_conformer() -> None:
    class _StubHandler:
        async def execute(self, request):
            return None

    assert isinstance(ToolLoopNode(function_calling_handler=_StubHandler()), RunNode)


@pytest.mark.asyncio
async def test_tool_loop_node_delegates_to_fc_handler_and_wraps_result() -> None:
    from magi.agent.task_agents.common.contracts import (
        ExecutionMode,
        FunctionCallingExecutionResult,
    )

    captured_requests = []

    class _StubFCHandler:
        async def execute(self, request):
            captured_requests.append(request)
            return FunctionCallingExecutionResult(
                mode=ExecutionMode.FUNCTION_CALLING,
                response_text="tool loop result",
                execution_outcome={"status": "completed", "iterations": 2},
            )

    node = ToolLoopNode(function_calling_handler=_StubFCHandler())
    sentinel = object()
    result = await node.execute(sentinel)  # type: ignore[arg-type]

    assert captured_requests == [sentinel]
    assert result.outcome == NodeOutcome.DONE
    assert result.execution_result is not None
    assert result.execution_result.response_text == "tool loop result"


@pytest.mark.asyncio
async def test_tool_loop_node_propagates_handler_exception_as_failed() -> None:
    class _RaisingHandler:
        async def execute(self, request):
            raise ValueError("fc handler boom")

    node = ToolLoopNode(function_calling_handler=_RaisingHandler())
    result = await node.execute(None)  # type: ignore[arg-type]
    assert result.outcome == NodeOutcome.FAILED
    assert "fc handler boom" in (result.error or "")
