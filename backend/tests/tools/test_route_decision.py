"""Unit tests for RouteDecision strict typed schema."""
from __future__ import annotations

import pytest

from magi.config.models import ThinkingDepth
from magi.tools.context_routing.route_decision import RouteDecision


def test_route_decision_constructs_with_required_fields_only() -> None:
    decision = RouteDecision(
        profile="chat",
        graph_shape="reply",
        complexity="simple",
    )
    assert decision.profile == "chat"
    assert decision.graph_shape == "reply"
    assert decision.complexity == "simple"
    # Defaults
    assert decision.tools == []
    assert decision.capabilities == []
    assert decision.needs_workspace is False
    assert decision.needs_external is False
    assert decision.may_write is False
    assert decision.risky_tools == []
    assert decision.background_hint == "foreground"
    assert decision.effort == "low"
    assert decision.confidence == 0.0
    assert decision.reasoning == ""
    assert decision.thinking_depth == ThinkingDepth.NONE


def test_route_decision_construct_with_all_fields() -> None:
    decision = RouteDecision(
        profile="coding",
        graph_shape="plan_fanout",
        complexity="large",
        tools=["grep", "file_edit"],
        capabilities=["workspace_read", "workspace_write"],
        needs_workspace=True,
        needs_external=False,
        may_write=True,
        risky_tools=["file_edit"],
        background_hint="background_ok",
        effort="high",
        confidence=0.92,
        reasoning="Major refactor needing decomposition.",
        thinking_depth=ThinkingDepth.HIGH,
        memory_route="recall",
        memory_layer="L3",
        register="focused",
        active_trigger_ids=("code_review",),
        situation_strength="strong",
        quiet_hour_hints=("deep_work",),
    )
    assert decision.tools == ["grep", "file_edit"]
    assert decision.may_write is True
    assert decision.thinking_depth == ThinkingDepth.HIGH
    assert decision.memory_route == "recall"
    assert decision.register == "focused"
    assert decision.active_trigger_ids == ("code_review",)


def test_route_decision_is_frozen() -> None:
    """RouteDecision is immutable to prevent post-routing mutation by consumers."""
    decision = RouteDecision(profile="chat", graph_shape="reply", complexity="simple")
    with pytest.raises((AttributeError, Exception)):
        decision.profile = "coding"  # type: ignore[misc]


def test_route_decision_rejects_invalid_profile() -> None:
    """Validation: profile must be one of the allowed Literal values."""
    with pytest.raises(ValueError, match="profile"):
        RouteDecision(profile="invalid", graph_shape="reply", complexity="simple")


def test_route_decision_rejects_invalid_graph_shape() -> None:
    with pytest.raises(ValueError, match="graph_shape"):
        RouteDecision(profile="chat", graph_shape="weird_shape", complexity="simple")


def test_route_decision_rejects_invalid_complexity() -> None:
    with pytest.raises(ValueError, match="complexity"):
        RouteDecision(profile="chat", graph_shape="reply", complexity="impossible")


def test_route_decision_rejects_invalid_background_hint() -> None:
    with pytest.raises(ValueError, match="background_hint"):
        RouteDecision(
            profile="chat", graph_shape="reply", complexity="simple",
            background_hint="invalid",
        )


def test_route_decision_rejects_invalid_effort() -> None:
    with pytest.raises(ValueError, match="effort"):
        RouteDecision(
            profile="chat", graph_shape="reply", complexity="simple",
            effort="absurd",
        )


def test_route_decision_accepts_all_profile_values() -> None:
    """Smoke test: each value in the profile Literal constructs cleanly."""
    for profile in ("chat", "research", "explore", "coding", "media", "system"):
        decision = RouteDecision(profile=profile, graph_shape="reply", complexity="simple")
        assert decision.profile == profile


def test_route_decision_accepts_all_graph_shape_values() -> None:
    for shape in ("reply", "tool_loop", "plan_fanout"):
        decision = RouteDecision(profile="chat", graph_shape=shape, complexity="simple")
        assert decision.graph_shape == shape
