"""Tests for ContextDecider returning RouteDecision."""
from __future__ import annotations

import pytest

from magi.tools.context_routing import RouteDecision


def _build_response_mixin_subject():
    """Construct a minimal subject that exposes _parse_response."""
    from magi.tools.context_decider_response import ContextDeciderResponseMixin

    class _Host(ContextDeciderResponseMixin):
        max_tools = 5
        tool_registry = None

        def _default_orchestration_strategy(self, tools=None, user_lower=""):
            return {"mode": "direct", "planner": "task_agent",
                    "default_leaf_type": "general-purpose", "allow_parallel": False}

        def _get_available_tools(self):
            return []

        def _normalize_orchestration_strategy(self, payload):
            return self._default_orchestration_strategy()

    return _Host()


def test_parse_response_returns_route_decision_for_valid_strict_json() -> None:
    """When the LLM emits a full RouteDecision JSON object, the parser
    must return a RouteDecision instance."""
    host = _build_response_mixin_subject()
    raw_json = """
    {
      "profile": "chat",
      "graph_shape": "reply",
      "complexity": "simple",
      "tools": [],
      "capabilities": [],
      "risky_tools": [],
      "needs_workspace": false,
      "needs_external": false,
      "may_write": false,
      "background_hint": "foreground",
      "effort": "low",
      "confidence": 0.85,
      "reasoning": "Simple conversational request.",
      "thinking_depth": "none",
      "memory_route": "none",
      "register": null,
      "active_trigger_ids": [],
      "situation_strength": "ordinary",
      "quiet_hour_hints": []
    }
    """
    result = host._parse_response(raw_json)
    assert isinstance(result, RouteDecision)
    assert result.profile == "chat"
    assert result.graph_shape == "reply"
    assert result.confidence == 0.85
    assert result.reasoning == "Simple conversational request."


def test_parse_response_returns_fallback_route_decision_for_empty_input() -> None:
    """Empty LLM output → safe-fallback RouteDecision."""
    host = _build_response_mixin_subject()
    result = host._parse_response("")
    assert isinstance(result, RouteDecision)
    assert result.profile == "chat"
    assert result.graph_shape == "reply"


def test_parse_response_returns_fallback_for_garbled_json() -> None:
    """Malformed JSON → safe-fallback RouteDecision."""
    host = _build_response_mixin_subject()
    result = host._parse_response("{ this is not json")
    assert isinstance(result, RouteDecision)
    assert result.profile == "chat"


def test_parse_response_returns_fallback_for_invalid_enum_value() -> None:
    """LLM emits an invalid enum (e.g., profile='nonsense') → fallback."""
    host = _build_response_mixin_subject()
    raw_json = """
    {
      "profile": "nonsense",
      "graph_shape": "reply",
      "complexity": "simple"
    }
    """
    result = host._parse_response(raw_json)
    assert isinstance(result, RouteDecision)
    assert result.profile == "chat"  # fallback


def test_parse_response_preserves_persona_fields() -> None:
    """Persona routing fields in the LLM output must reach the
    RouteDecision (tuple form)."""
    host = _build_response_mixin_subject()
    raw_json = """
    {
      "profile": "chat",
      "graph_shape": "reply",
      "complexity": "simple",
      "register": "focused",
      "active_trigger_ids": ["work_mode", "deep_focus"]
    }
    """
    result = host._parse_response(raw_json)
    assert result.register == "focused"
    assert result.active_trigger_ids == ("work_mode", "deep_focus")


def test_orchestration_launch_handler_reads_route_decision_from_intent() -> None:
    """OrchestrationLaunchHandler.execute must read RouteDecision off
    request.intent.route_decision and pass to start_orchestration so the
    typed schema flows end-to-end."""
    import inspect
    from magi.agent.task_agents.common.handlers import OrchestrationLaunchHandler

    src = inspect.getsource(OrchestrationLaunchHandler.execute)
    assert "route_decision" in src, (
        "OrchestrationLaunchHandler.execute must read intent.route_decision"
    )


def test_chat_coordinator_match_intent_signature_returns_intent_decision_from_route() -> None:
    """ChatCoordinator.match_intent must continue to return an IntentDecision
    even after the underlying ContextDecider returns RouteDecision. The
    coordinator translates RouteDecision → IntentDecision (which still has
    fields the rest of chat consumes: execution_mode, tools, thinking_depth,
    orchestration_plan, persona_routing_hint, etc.)."""
    import inspect
    from magi.agent.task_agents.chat.coordinator import ChatExecutionCoordinator

    src = inspect.getsource(ChatExecutionCoordinator.match_intent)
    assert "decision.graph_shape" in src or "decision.profile" in src, (
        "match_intent must consume RouteDecision fields directly, not "
        "the legacy orchestration_strategy dict"
    )


def test_task_orchestrator_start_accepts_route_decision_kwarg() -> None:
    import inspect
    from magi.agent.task_orchestrator import TaskOrchestrator

    sig = inspect.signature(TaskOrchestrator.start_orchestration)
    assert "route_decision" in sig.parameters
