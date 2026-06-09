"""PlanFanoutNode adapter tests."""
from __future__ import annotations

import pytest

from magi.agent.run.nodes.protocol import NodeOutcome, RunNode
from magi.agent.run.nodes.plan_fanout import PlanFanoutNode


def test_plan_fanout_node_declares_node_type_plan_fanout() -> None:
    assert PlanFanoutNode.node_type == "plan_fanout"


def test_plan_fanout_node_is_a_run_node_protocol_conformer() -> None:
    class _StubHandler:
        async def execute(self, request):
            return None

    assert isinstance(PlanFanoutNode(orchestration_launch_handler=_StubHandler()), RunNode)


@pytest.mark.asyncio
async def test_plan_fanout_node_delegates_and_wraps_result() -> None:
    from magi.agent.task_agents.common.contracts import ExecutionMode, ExecutionResult

    captured = []

    class _StubOrchHandler:
        async def execute(self, request):
            captured.append(request)
            return ExecutionResult(
                mode=ExecutionMode.ORCHESTRATION_LAUNCH,
                response_text="orchestration done",
            )

    node = PlanFanoutNode(orchestration_launch_handler=_StubOrchHandler())
    sentinel = object()
    result = await node.execute(sentinel)  # type: ignore[arg-type]

    assert captured == [sentinel]
    assert result.outcome == NodeOutcome.DONE
    assert result.execution_result is not None
    assert result.execution_result.response_text == "orchestration done"


@pytest.mark.asyncio
async def test_plan_fanout_node_propagates_handler_exception_as_failed() -> None:
    class _RaisingHandler:
        async def execute(self, request):
            raise RuntimeError("orchestration boom")

    node = PlanFanoutNode(orchestration_launch_handler=_RaisingHandler())
    result = await node.execute(None)  # type: ignore[arg-type]
    assert result.outcome == NodeOutcome.FAILED
    assert "orchestration boom" in (result.error or "")
