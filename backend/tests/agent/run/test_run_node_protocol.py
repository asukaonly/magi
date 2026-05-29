"""Unit tests for the RunNode protocol + NodeResult dataclass."""
from __future__ import annotations

import pytest

from magi.agent.run.nodes.protocol import (
    NodeOutcome,
    NodeResult,
    RunNode,
)


def test_node_outcome_enum_has_three_values() -> None:
    """NodeOutcome: DONE (terminal), NEXT (advance to next node), FAILED."""
    assert NodeOutcome.DONE.value == "done"
    assert NodeOutcome.NEXT.value == "next"
    assert NodeOutcome.FAILED.value == "failed"


def test_node_result_constructs_with_required_fields() -> None:
    result = NodeResult(outcome=NodeOutcome.DONE)
    assert result.outcome == NodeOutcome.DONE
    assert result.execution_result is None
    assert result.error is None


def test_node_result_carries_execution_result_for_handler_adapter_path() -> None:
    """Phase C adapters return the wrapped ExecutionResult via NodeResult."""
    from magi.agent.task_agents.common.contracts import ExecutionMode, ExecutionResult

    exec_result = ExecutionResult(mode=ExecutionMode.DIRECT_LLM, response_text="hello")
    result = NodeResult(outcome=NodeOutcome.DONE, execution_result=exec_result)
    assert result.execution_result is exec_result
    assert result.execution_result.response_text == "hello"


def test_node_result_is_frozen() -> None:
    """Immutable to prevent post-execution mutation."""
    result = NodeResult(outcome=NodeOutcome.DONE)
    with pytest.raises(Exception):
        result.outcome = NodeOutcome.FAILED  # type: ignore[misc]


def test_node_result_failed_outcome_carries_error_message() -> None:
    result = NodeResult(outcome=NodeOutcome.FAILED, error="LLM unavailable")
    assert result.outcome == NodeOutcome.FAILED
    assert result.error == "LLM unavailable"


def test_run_node_protocol_runtime_checkable() -> None:
    """RunNode protocol must be runtime-checkable so the registry can
    isinstance-validate adapters at registration time."""

    class _ConformingNode:
        node_type: str = "reply"

        async def execute(self, request) -> NodeResult:
            return NodeResult(outcome=NodeOutcome.DONE)

    instance = _ConformingNode()
    assert isinstance(instance, RunNode)


def test_run_node_protocol_rejects_non_conformer() -> None:
    """A class missing `execute` is NOT a RunNode."""

    class _MissingExecute:
        node_type: str = "reply"

    assert not isinstance(_MissingExecute(), RunNode)
