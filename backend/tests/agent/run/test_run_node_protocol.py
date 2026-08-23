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

        def snapshot(self) -> dict:
            return {}

        def restore(self, state: dict) -> None:
            pass

    instance = _ConformingNode()
    assert isinstance(instance, RunNode)


def test_run_node_protocol_rejects_non_conformer() -> None:
    """A class missing `execute` is NOT a RunNode."""

    class _MissingExecute:
        node_type: str = "reply"

    assert not isinstance(_MissingExecute(), RunNode)


def test_run_node_protocol_has_optional_snapshot_method() -> None:
    """Phase E: RunNode protocol declares snapshot() returning a dict
    and restore(state) accepting a dict. Default implementations on
    Phase C/D adapters return/accept empty dicts (no real state)."""
    from magi.agent.run.nodes.protocol import RunNode

    # Protocol attribute presence; checked via runtime_checkable.
    class _ConformingWithSnapshot:
        node_type: str = "reply"

        async def execute(self, request):
            return None

        def snapshot(self) -> dict:
            return {}

        def restore(self, state: dict) -> None:
            pass

    assert isinstance(_ConformingWithSnapshot(), RunNode)


def test_reply_node_snapshot_returns_empty_dict() -> None:
    """Phase E: ReplyNode is stateless — snapshot returns empty dict."""
    from magi.agent.run.nodes.reply import ReplyNode

    class _StubHandler:
        async def execute(self, request):
            return None

    node = ReplyNode(direct_llm_handler=_StubHandler())
    assert node.snapshot() == {}


def test_reply_node_restore_accepts_dict_noop() -> None:
    """Restoring an empty dict is a no-op."""
    from magi.agent.run.nodes.reply import ReplyNode

    class _StubHandler:
        async def execute(self, request):
            return None

    node = ReplyNode(direct_llm_handler=_StubHandler())
    # Must not raise.
    node.restore({})
    node.restore({"unknown": "ignored"})


def test_plan_fanout_node_snapshot_returns_empty_dict() -> None:
    from magi.agent.run.nodes.plan_fanout import PlanFanoutNode

    class _StubHandler:
        async def execute(self, request):
            return None

    node = PlanFanoutNode(orchestration_launch_handler=_StubHandler())
    assert node.snapshot() == {}


def test_validate_node_snapshot_returns_empty_dict() -> None:
    """ValidateNode has no persistent state between invocations."""
    from magi.agent.run.nodes.validate import ValidateNode

    class _StubInvocationService:
        async def invoke(self, call, context):
            return None

    node = ValidateNode(tool_invocation_service=_StubInvocationService())
    assert node.snapshot() == {}
