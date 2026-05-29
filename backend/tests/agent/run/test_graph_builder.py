"""GraphBuilder + NodeSpec tests."""
from __future__ import annotations

from magi.agent.run.spec import NodeSpec, GRAPH_TEMPLATES


def test_node_spec_constructs_with_node_type_only() -> None:
    spec = NodeSpec(node_type="reply")
    assert spec.node_type == "reply"


def test_node_spec_is_frozen() -> None:
    import pytest
    spec = NodeSpec(node_type="reply")
    with pytest.raises(Exception):
        spec.node_type = "tool_loop"  # type: ignore[misc]


def test_graph_templates_define_three_base_shapes() -> None:
    """Phase D: GRAPH_TEMPLATES maps each route graph_shape to a base
    NodeSpec sequence. profile-driven appenders (e.g., ValidateNode for
    coding) are applied by GraphBuilder, not in the template."""
    assert "reply" in GRAPH_TEMPLATES
    assert "tool_loop" in GRAPH_TEMPLATES
    assert "plan_fanout" in GRAPH_TEMPLATES

    assert GRAPH_TEMPLATES["reply"] == (NodeSpec(node_type="reply"),)
    assert GRAPH_TEMPLATES["tool_loop"] == (NodeSpec(node_type="tool_loop"),)
    assert GRAPH_TEMPLATES["plan_fanout"] == (NodeSpec(node_type="plan_fanout"),)


def test_graph_templates_are_immutable_tuples() -> None:
    """Tuples so callers cannot mutate the template by reference."""
    for shape, template in GRAPH_TEMPLATES.items():
        assert isinstance(template, tuple), f"GRAPH_TEMPLATES[{shape!r}] must be a tuple"
