"""Unit tests for RouteDecision strict typed schema."""
from __future__ import annotations

import pytest

from magi.config.models import ThinkingDepth
from magi.tools.context_routing.route_decision import PersonaRouting, RouteDecision


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
    assert decision.may_write is False
    assert decision.reasoning == ""
    assert decision.thinking_depth == ThinkingDepth.NONE
    assert decision.memory_route == "none"


def test_route_decision_construct_with_all_fields() -> None:
    decision = RouteDecision(
        profile="coding",
        graph_shape="plan_fanout",
        complexity="large",
        tools=["grep", "file_edit"],
        may_write=True,
        reasoning="Major refactor needing decomposition.",
        thinking_depth=ThinkingDepth.HIGH,
        memory_route="recall",
        persona=PersonaRouting(
            register="focused",
            active_trigger_ids=("code_review",),
            situation_strength="strong",
            quiet_hour_hints=("deep_work",),
        ),
    )
    assert decision.tools == ["grep", "file_edit"]
    assert decision.may_write is True
    assert decision.thinking_depth == ThinkingDepth.HIGH
    assert decision.memory_route == "recall"
    assert decision.register == "focused"
    assert decision.active_trigger_ids == ("code_review",)


def test_persona_fields_grouped_under_persona_subobject() -> None:
    """ADR-0005: persona fields live under a nested PersonaRouting sub-object;
    flat @property accessors remain as a transition shim for existing readers."""
    persona = PersonaRouting(register="task", active_trigger_ids=("x",))
    decision = RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple", persona=persona
    )
    assert decision.persona is persona
    assert decision.persona.register == "task"
    # flat shim still works for existing readers
    assert decision.register == "task"
    assert decision.active_trigger_ids == ("x",)
    assert decision.situation_strength == "ordinary"


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


def test_route_decision_accepts_all_profile_values() -> None:
    """Smoke test: each value in the profile Literal constructs cleanly."""
    for profile in ("chat", "research", "explore", "coding", "media", "system"):
        decision = RouteDecision(profile=profile, graph_shape="reply", complexity="simple")
        assert decision.profile == profile


def test_route_decision_accepts_all_graph_shape_values() -> None:
    for shape in ("reply", "tool_loop", "plan_fanout"):
        decision = RouteDecision(profile="chat", graph_shape=shape, complexity="simple")
        assert decision.graph_shape == shape


def test_route_decision_is_importable_from_context_routing_package() -> None:
    """RouteDecision must be re-exported from the package init so
    consumers can write ``from magi.tools.context_routing import RouteDecision``
    without reaching into the route_decision submodule."""
    from magi.tools.context_routing import RouteDecision

    assert RouteDecision.__name__ == "RouteDecision"


def test_legacy_strategy_dict_for_plan_fanout_coding() -> None:
    """Adapter: graph_shape=plan_fanout with profile=coding maps to
    mode=decompose, default_leaf_type=Coding."""
    from magi.tools.context_routing import RouteDecision

    decision = RouteDecision(
        profile="coding", graph_shape="plan_fanout", complexity="large", may_write=True,
    )
    legacy = decision.to_legacy_strategy_dict()
    assert legacy["mode"] == "decompose"
    assert legacy["default_leaf_type"] == "Coding"
    assert legacy["allow_parallel"] is True


def test_legacy_strategy_dict_for_reply_chat() -> None:
    """Adapter: graph_shape=reply with profile=chat maps to mode=direct,
    default_leaf_type=general-purpose, allow_parallel=False."""
    from magi.tools.context_routing import RouteDecision

    decision = RouteDecision(profile="chat", graph_shape="reply", complexity="simple")
    legacy = decision.to_legacy_strategy_dict()
    assert legacy["mode"] == "direct"
    assert legacy["default_leaf_type"] == "general-purpose"
    assert legacy["allow_parallel"] is False


def test_legacy_strategy_dict_for_explore() -> None:
    from magi.tools.context_routing import RouteDecision

    decision = RouteDecision(
        profile="explore", graph_shape="plan_fanout", complexity="medium",
    )
    legacy = decision.to_legacy_strategy_dict()
    assert legacy["mode"] == "decompose"
    assert legacy["default_leaf_type"] == "CodeExplore"
    assert legacy["allow_parallel"] is True


def test_orchestration_module_no_longer_exposes_keyword_normalization() -> None:
    """Task B.11: the keyword-based orchestration_strategy normalization is
    deleted. After this commit, only the RouteDecision adapter is used."""
    import importlib
    module = importlib.import_module("magi.tools.context_routing.orchestration")
    assert not hasattr(module, "default_orchestration_strategy"), (
        "default_orchestration_strategy must be deleted; use RouteDecision.to_legacy_strategy_dict()"
    )
    assert not hasattr(module, "normalize_orchestration_strategy"), (
        "normalize_orchestration_strategy must be deleted; RouteDecision schema validates strictly"
    )


def test_context_decision_class_is_deleted() -> None:
    """Task B.12: ContextDecision is deleted now that all consumers use RouteDecision."""
    import importlib
    models = importlib.import_module("magi.tools.context_routing.models")
    assert not hasattr(models, "ContextDecision"), (
        "ContextDecision must be deleted; use RouteDecision"
    )

    pkg = importlib.import_module("magi.tools.context_routing")
    assert not hasattr(pkg, "ContextDecision")


def test_context_decider_system_prompt_mentions_route_decision_fields() -> None:
    """Source check: the system prompt must request the RouteDecision
    schema's enum fields so the LLM outputs strict JSON that the new
    parser can validate."""
    from magi.tools.context_decider_system_prompt import CONTEXT_DECIDER_SYSTEM_PROMPT

    prompt = CONTEXT_DECIDER_SYSTEM_PROMPT
    assert "profile" in prompt
    assert "graph_shape" in prompt
    assert "complexity" in prompt
    # Each profile value must be mentioned so the LLM knows the allowed set
    for value in ("chat", "research", "explore", "coding", "media", "system"):
        assert value in prompt, f"system prompt must mention profile value {value!r}"
    # Each graph_shape value
    for value in ("reply", "tool_loop", "plan_fanout"):
        assert value in prompt, f"system prompt must mention graph_shape value {value!r}"
