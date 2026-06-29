"""NodeRegistry tests."""
from __future__ import annotations

import pytest

from magi.agent.run.nodes.protocol import NodeOutcome, NodeResult
from magi.agent.run.registry import NodeRegistry


class _StubNode:
    def __init__(self, node_type: str) -> None:
        self.node_type = node_type

    async def execute(self, request):
        return NodeResult(outcome=NodeOutcome.DONE)

    def snapshot(self) -> dict:
        return {}

    def restore(self, state: dict) -> None:
        pass


def test_node_registry_starts_empty() -> None:
    registry = NodeRegistry()
    assert registry.get("reply") is None
    assert registry.get("tool_loop") is None


def test_register_and_get_returns_node() -> None:
    registry = NodeRegistry()
    node = _StubNode(node_type="reply")
    registry.register(node)
    assert registry.get("reply") is node


def test_register_uses_node_type_attribute_as_key() -> None:
    registry = NodeRegistry()
    node = _StubNode(node_type="plan_fanout")
    registry.register(node)
    assert registry.get("plan_fanout") is node
    assert registry.get("reply") is None


def test_register_duplicate_node_type_raises() -> None:
    registry = NodeRegistry()
    registry.register(_StubNode(node_type="reply"))
    with pytest.raises(ValueError, match="reply"):
        registry.register(_StubNode(node_type="reply"))


def test_get_returns_none_for_unknown_graph_shape() -> None:
    registry = NodeRegistry()
    registry.register(_StubNode(node_type="reply"))
    assert registry.get("nonexistent_shape") is None


def test_register_rejects_non_run_node_conformer() -> None:
    registry = NodeRegistry()

    class _MissingExecute:
        node_type: str = "reply"

    with pytest.raises(TypeError, match="execute"):
        registry.register(_MissingExecute())  # type: ignore[arg-type]


def test_graph_shapes_returns_registered_keys() -> None:
    registry = NodeRegistry()
    registry.register(_StubNode(node_type="reply"))
    registry.register(_StubNode(node_type="tool_loop"))
    registry.register(_StubNode(node_type="plan_fanout"))
    assert set(registry.graph_shapes()) == {"reply", "tool_loop", "plan_fanout"}


def test_task_agent_execution_engine_has_node_registry_attribute() -> None:
    """TaskAgentExecutionEngine must construct a NodeRegistry at init."""
    import inspect

    from magi.agent.run.execution_engine import TaskAgentExecutionEngine

    src = inspect.getsource(TaskAgentExecutionEngine.__init__)
    assert "NodeRegistry" in src, (
        "TaskAgentExecutionEngine.__init__ must construct a NodeRegistry"
    )


def test_task_agent_execution_engine_dispatches_via_node_registry() -> None:
    """Phase D: TaskAgentExecutionEngine.execute dispatches user-message
    paths through NodeSequenceRunner (which internally uses the NodeRegistry).
    Phase D replaced the direct NodeRegistry lookup with a runner-based
    pipeline that supports multi-node sequences (e.g., ToolLoop + Validate).
    The execute() source must reference the sequence runner."""
    import inspect

    from magi.agent.run.execution_engine import TaskAgentExecutionEngine

    src = inspect.getsource(TaskAgentExecutionEngine.execute)
    # Phase D: NodeSequenceRunner drives dispatch; the runner holds the registry.
    assert "_node_sequence_runner" in src or "node_sequence_runner" in src, (
        "execute() must dispatch via the NodeSequenceRunner (Phase D)"
    )
    assert "route_decision" in src, (
        "execute() must consult route_decision to build the node sequence"
    )


def test_chat_intent_resolution_builds_typed_orchestration_plan() -> None:
    """Chat intent resolution derives the typed orchestration plan once."""
    import inspect

    from magi.chat.task_agent.intent_resolution_service import ChatIntentResolutionService

    src = inspect.getsource(ChatIntentResolutionService)
    assert "OrchestrationPlan.from_route_decision" in src


def test_base_intent_decision_carries_typed_orchestration_plan() -> None:
    """Intent decisions carry the route decision and its derived plan."""
    from magi.agent.task_agents.common.contracts import BaseIntentDecision

    field_names = {f.name for f in BaseIntentDecision.__dataclass_fields__.values()}
    assert "orchestration_plan" in field_names
    assert "route_decision" in field_names
