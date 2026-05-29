"""NodeSequenceRunner tests."""
from __future__ import annotations

import pytest

from magi.agent.run.nodes.protocol import NodeOutcome, NodeResult
from magi.agent.run.registry import NodeRegistry
from magi.agent.run.runner import NodeSequenceRunner
from magi.agent.run.spec import NodeSpec


class _StubNode:
    def __init__(self, node_type: str, *, outcome: NodeOutcome = NodeOutcome.DONE,
                 response_text: str | None = None, error: str | None = None) -> None:
        self.node_type = node_type
        self._outcome = outcome
        self._response_text = response_text
        self._error = error
        self.executed_with: list = []

    async def execute(self, request):
        from magi.agent.task_agents.common.contracts import ExecutionMode, ExecutionResult
        self.executed_with.append(request)
        if self._outcome == NodeOutcome.FAILED:
            return NodeResult(outcome=NodeOutcome.FAILED, error=self._error)
        exec_result = (
            ExecutionResult(mode=ExecutionMode.DIRECT_LLM, response_text=self._response_text)
            if self._response_text is not None
            else None
        )
        return NodeResult(outcome=self._outcome, execution_result=exec_result)


def _build_registry(*nodes) -> NodeRegistry:
    registry = NodeRegistry()
    for n in nodes:
        registry.register(n)
    return registry


@pytest.mark.asyncio
async def test_runner_executes_single_node_and_returns_its_result() -> None:
    primary = _StubNode("tool_loop", response_text="primary done")
    registry = _build_registry(primary)
    runner = NodeSequenceRunner(node_registry=registry)
    result = await runner.run(
        node_specs=[NodeSpec(node_type="tool_loop")],
        request=object(),
    )
    assert result is not None
    assert result.response_text == "primary done"


@pytest.mark.asyncio
async def test_runner_executes_two_nodes_and_merges_response_text() -> None:
    """When two nodes both return DONE with response_text, the runner
    concatenates them with a newline separator."""
    primary = _StubNode("tool_loop", response_text="primary did stuff")
    validate = _StubNode("validate", response_text="[verify] OK")
    registry = _build_registry(primary, validate)
    runner = NodeSequenceRunner(node_registry=registry)
    result = await runner.run(
        node_specs=[NodeSpec(node_type="tool_loop"), NodeSpec(node_type="validate")],
        request=object(),
    )
    assert result is not None
    assert "primary did stuff" in result.response_text
    assert "[verify] OK" in result.response_text


@pytest.mark.asyncio
async def test_runner_stops_on_first_failed_and_returns_failure_result() -> None:
    """If any node returns FAILED, the runner short-circuits and does
    not execute subsequent nodes. Returns an ExecutionResult whose
    response_text describes the failure."""
    primary = _StubNode("tool_loop", outcome=NodeOutcome.FAILED, error="primary failed")
    validate = _StubNode("validate", response_text="should not run")
    registry = _build_registry(primary, validate)
    runner = NodeSequenceRunner(node_registry=registry)
    result = await runner.run(
        node_specs=[NodeSpec(node_type="tool_loop"), NodeSpec(node_type="validate")],
        request=object(),
    )
    assert validate.executed_with == [], "ValidateNode must not run after primary FAILED"
    assert result is not None
    assert "primary failed" in result.response_text.lower()


@pytest.mark.asyncio
async def test_runner_validate_failure_after_primary_success_returns_combined_result() -> None:
    """primary DONE → validate FAILED. Runner returns a result that
    surfaces both: the primary response_text PLUS the validation error."""
    primary = _StubNode("tool_loop", response_text="edits applied")
    validate = _StubNode("validate", outcome=NodeOutcome.FAILED, error="syntax error in foo.py")
    registry = _build_registry(primary, validate)
    runner = NodeSequenceRunner(node_registry=registry)
    result = await runner.run(
        node_specs=[NodeSpec(node_type="tool_loop"), NodeSpec(node_type="validate")],
        request=object(),
    )
    assert result is not None
    assert "edits applied" in result.response_text
    assert "syntax error in foo.py" in result.response_text


@pytest.mark.asyncio
async def test_runner_raises_if_node_type_not_in_registry() -> None:
    """An unregistered node_type is a programmer error and is loud."""
    registry = _build_registry()
    runner = NodeSequenceRunner(node_registry=registry)
    with pytest.raises(ValueError, match="reply"):
        await runner.run(
            node_specs=[NodeSpec(node_type="reply")],
            request=object(),
        )


@pytest.mark.asyncio
async def test_runner_empty_sequence_returns_none() -> None:
    """Empty node sequence — no work to do. Returns None so caller can
    fall back to legacy path."""
    registry = _build_registry()
    runner = NodeSequenceRunner(node_registry=registry)
    result = await runner.run(node_specs=[], request=object())
    assert result is None
