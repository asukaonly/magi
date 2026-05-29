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


def test_chat_execution_coordinator_has_node_registry_attribute() -> None:
    """ChatExecutionCoordinator must construct a NodeRegistry at init
    and expose it as `_node_registry` (private; consumed only by
    execute())."""
    import inspect

    from magi.agent.task_agents.chat.coordinator import ChatExecutionCoordinator

    src = inspect.getsource(ChatExecutionCoordinator.__init__)
    assert "NodeRegistry" in src, (
        "ChatExecutionCoordinator.__init__ must construct a NodeRegistry"
    )


def test_chat_execution_coordinator_execute_dispatches_via_node_registry() -> None:
    """ChatExecutionCoordinator.execute must consult the NodeRegistry
    using request.intent.route_decision.graph_shape; only when the
    registry returns None should it fall back to the legacy
    ExecutionHandlerRegistry."""
    import inspect

    from magi.agent.task_agents.chat.coordinator import ChatExecutionCoordinator

    src = inspect.getsource(ChatExecutionCoordinator.execute)
    assert "_node_registry" in src or "node_registry" in src, (
        "execute() must consult the node registry"
    )
    assert "graph_shape" in src, (
        "execute() must dispatch by graph_shape"
    )


def test_chat_execution_coordinator_no_longer_builds_orchestration_plan() -> None:
    """Phase C cleanup: ChatExecutionCoordinator stops constructing
    OrchestrationPlan in match_intent."""
    import inspect

    from magi.agent.task_agents.chat.coordinator import ChatExecutionCoordinator

    src = inspect.getsource(ChatExecutionCoordinator)
    assert "_build_orchestration_plan_from_route" not in src, (
        "_build_orchestration_plan_from_route is no longer needed"
    )


def test_base_intent_decision_no_longer_has_orchestration_plan_field() -> None:
    """The orchestration_plan field is removed from BaseIntentDecision;
    consumers read route_decision instead."""
    from magi.agent.task_agents.common.contracts import BaseIntentDecision

    field_names = {f.name for f in BaseIntentDecision.__dataclass_fields__.values()}
    assert "orchestration_plan" not in field_names
    assert "route_decision" in field_names
