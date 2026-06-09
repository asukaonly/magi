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


def test_tool_loop_node_snapshot_starts_empty() -> None:
    """Before any execute() call, snapshot returns an empty dict."""
    from magi.agent.run.nodes.tool_loop import ToolLoopNode

    class _StubHandler:
        async def execute(self, request):
            return None

    node = ToolLoopNode(function_calling_handler=_StubHandler())
    assert node.snapshot() == {}


def test_tool_loop_node_snapshot_captures_orchestrator_snapshot_from_execution_outcome() -> None:
    """When execute() returns a FunctionCallingExecutionResult with an
    'execution_outcome.snapshot' field (the existing FC OrchestratorSnapshot
    shape), ToolLoopNode.snapshot returns that snapshot dict — so a
    later restore reproduces the in-flight FC message history."""
    import asyncio
    from magi.agent.run.nodes.tool_loop import ToolLoopNode
    from magi.agent.task_agents.common.contracts import (
        ExecutionMode, FunctionCallingExecutionResult,
    )

    class _StubFC:
        async def execute(self, request):
            return FunctionCallingExecutionResult(
                mode=ExecutionMode.FUNCTION_CALLING,
                response_text="partial",
                execution_outcome={
                    "status": "detached",
                    "iterations": 3,
                    "snapshot": {
                        "messages": [{"role": "user", "content": "hi"}],
                        "iterations": 3,
                        "reason": "user_request",
                        "note": "",
                    },
                },
            )

    node = ToolLoopNode(function_calling_handler=_StubFC())
    asyncio.run(node.execute(object()))  # type: ignore[arg-type]

    snap = node.snapshot()
    assert snap.get("messages") == [{"role": "user", "content": "hi"}]
    assert snap.get("iterations") == 3


def test_tool_loop_node_restore_round_trips_via_snapshot() -> None:
    """A snapshot dict can be restored on a fresh ToolLoopNode; the
    restored state survives until next execute()."""
    from magi.agent.run.nodes.tool_loop import ToolLoopNode

    class _StubHandler:
        async def execute(self, request):
            return None

    node = ToolLoopNode(function_calling_handler=_StubHandler())
    snapshot_data = {
        "messages": [{"role": "user", "content": "restored"}],
        "iterations": 2,
        "reason": "background_resume",
    }
    node.restore(snapshot_data)
    assert node.snapshot() == snapshot_data
