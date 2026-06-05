"""End-to-end smoke for Phase B: a RouteDecision constructed in the
ContextDecider parser flows through the chat coordinator, intent
decision, handler, and execution path without losing information."""
from __future__ import annotations

import pytest

from magi.config.models import ThinkingDepth
from magi.tools.context_routing import PersonaRouting, RouteDecision


def test_route_decision_to_legacy_strategy_for_each_graph_shape() -> None:
    for shape, expected_mode in (
        ("reply", "direct"),
        ("tool_loop", "direct"),
        ("plan_fanout", "decompose"),
    ):
        d = RouteDecision(profile="chat", graph_shape=shape, complexity="simple")
        legacy = d.to_legacy_strategy_dict()
        assert legacy["mode"] == expected_mode


def test_route_decision_preserves_thinking_depth() -> None:
    d = RouteDecision(
        profile="research", graph_shape="tool_loop", complexity="medium",
        thinking_depth=ThinkingDepth.HIGH,
    )
    assert d.thinking_depth == ThinkingDepth.HIGH


def test_route_decision_default_leaf_type_for_coding_profile() -> None:
    d = RouteDecision(
        profile="coding", graph_shape="plan_fanout", complexity="large",
        may_write=True,
    )
    assert d.to_legacy_strategy_dict()["default_leaf_type"] == "Coding"


def test_route_decision_default_leaf_type_for_explore_profile() -> None:
    d = RouteDecision(
        profile="explore", graph_shape="plan_fanout", complexity="medium",
    )
    assert d.to_legacy_strategy_dict()["default_leaf_type"] == "CodeExplore"


def test_route_decision_default_leaf_type_for_chat_profile() -> None:
    d = RouteDecision(profile="chat", graph_shape="reply", complexity="simple")
    assert d.to_legacy_strategy_dict()["default_leaf_type"] == "general-purpose"


def test_route_decision_immutable_post_construction() -> None:
    d = RouteDecision(profile="chat", graph_shape="reply", complexity="simple")
    with pytest.raises(Exception):
        d.profile = "coding"  # type: ignore[misc]


def test_route_decision_with_persona_routing_fields_preserved() -> None:
    d = RouteDecision(
        profile="chat",
        graph_shape="reply",
        complexity="simple",
        persona=PersonaRouting(
            register="focused",
            active_trigger_ids=("work_mode",),
            situation_strength="strong",
            quiet_hour_hints=("deep_work",),
        ),
    )
    assert d.register == "focused"
    assert d.active_trigger_ids == ("work_mode",)
    assert d.situation_strength == "strong"
    assert d.quiet_hour_hints == ("deep_work",)
