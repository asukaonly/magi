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


from magi.agent.run.builder import GraphBuilder
from magi.tools.context_routing import RouteDecision


def test_graph_builder_returns_single_node_for_chat_reply() -> None:
    builder = GraphBuilder()
    decision = RouteDecision(profile="chat", graph_shape="reply", complexity="simple")
    sequence = builder.build_node_sequence(decision)
    assert len(sequence) == 1
    assert sequence[0].node_type == "reply"


def test_graph_builder_returns_single_node_for_research_tool_loop() -> None:
    builder = GraphBuilder()
    decision = RouteDecision(profile="research", graph_shape="tool_loop", complexity="medium")
    sequence = builder.build_node_sequence(decision)
    assert len(sequence) == 1
    assert sequence[0].node_type == "tool_loop"


def test_graph_builder_appends_validate_for_coding_tool_loop() -> None:
    """profile=coding causes ValidateNode to be appended after the primary
    node. Phase D's only profile-driven append."""
    builder = GraphBuilder()
    decision = RouteDecision(
        profile="coding", graph_shape="tool_loop", complexity="medium",
        may_write=True,
    )
    sequence = builder.build_node_sequence(decision)
    assert len(sequence) == 2
    assert sequence[0].node_type == "tool_loop"
    assert sequence[1].node_type == "validate"


def test_graph_builder_appends_validate_for_coding_plan_fanout() -> None:
    """Large coding refactor: plan_fanout primary node, ValidateNode appended."""
    builder = GraphBuilder()
    decision = RouteDecision(
        profile="coding", graph_shape="plan_fanout", complexity="large",
        may_write=True,
    )
    sequence = builder.build_node_sequence(decision)
    assert len(sequence) == 2
    assert sequence[0].node_type == "plan_fanout"
    assert sequence[1].node_type == "validate"


def test_graph_builder_does_not_append_validate_for_coding_reply() -> None:
    """A coding-profile turn that's just chat (graph_shape=reply, no
    tool use, no writes) does not need validate. ValidateNode is
    only useful when the primary node may have touched files."""
    builder = GraphBuilder()
    decision = RouteDecision(
        profile="coding", graph_shape="reply", complexity="simple",
        may_write=False,
    )
    sequence = builder.build_node_sequence(decision)
    # The decision is "coding profile but no writes" — pure conversation
    # about code. No validate needed.
    assert len(sequence) == 1
    assert sequence[0].node_type == "reply"


def test_graph_builder_does_not_append_validate_for_non_coding_profile() -> None:
    """profile != coding never appends validate, even if may_write=True
    (e.g., research with web-write tools is not a coding context)."""
    builder = GraphBuilder()
    decision = RouteDecision(
        profile="research", graph_shape="tool_loop", complexity="medium",
        may_write=True,
    )
    sequence = builder.build_node_sequence(decision)
    assert len(sequence) == 1
    assert sequence[0].node_type == "tool_loop"


def test_graph_builder_does_not_append_validate_when_may_write_false() -> None:
    """profile=coding + tool_loop + may_write=False (e.g., code Q&A
    that uses read-only tools) should NOT append ValidateNode."""
    builder = GraphBuilder()
    decision = RouteDecision(
        profile="coding", graph_shape="tool_loop", complexity="medium",
        may_write=False,
    )
    sequence = builder.build_node_sequence(decision)
    assert len(sequence) == 1
    assert sequence[0].node_type == "tool_loop"
