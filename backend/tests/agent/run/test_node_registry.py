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
