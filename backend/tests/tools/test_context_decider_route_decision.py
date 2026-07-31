"""Tests for ContextDecider returning RouteDecision."""
from __future__ import annotations

from magi.tools import context_decider as context_decider_module
from magi.tools.context_decider import ContextDecider
from magi.tools.context_routing import RouteDecision
from magi.tools.registry import ToolRegistry


def _build_response_mixin_subject():
    """Construct a minimal subject that exposes _parse_response."""
    from magi.tools.context_decider_response import ContextDeciderResponseMixin

    class _Host(ContextDeciderResponseMixin):
        max_tools = 5
        tool_registry = None

        def _get_available_tools(self):
            return []

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
      "tool_need": "none",
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
    assert result.tool_need == "none"
    assert result.reasoning == "Simple conversational request."


def test_parse_response_preserves_tool_discovery_need() -> None:
    host = _build_response_mixin_subject()
    raw_json = """
    {
      "profile": "research",
      "graph_shape": "reply",
      "complexity": "simple",
      "tool_need": "discover",
      "tools": [],
      "reasoning": "Needs a tool capability that the router should not choose exactly."
    }
    """
    result = host._parse_response(raw_json)
    assert result.tool_need == "discover"
    assert result.tools == []


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


def test_context_decider_omits_content_logs_and_trace_previews_when_disabled(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setattr(
        context_decider_module,
        "full_content_logging_enabled",
        lambda: False,
    )
    decider = ContextDecider(ToolRegistry())
    decision = RouteDecision(
        profile="chat",
        graph_shape="reply",
        complexity="simple",
        reasoning="ROUTING-REASONING-CANARY",
    )

    traced = decider._attach_trace(
        decision=decision,
        metadata={"model": "test-model"},
        duration_ms=12,
        user_message="ROUTING-REQUEST-CANARY",
        response="ROUTING-RESPONSE-CANARY",
    )
    with caplog.at_level("DEBUG", logger=context_decider_module.logger.name):
        decider._log_decision(traced, "ROUTING-RESPONSE-CANARY")

    assert "request_preview" not in traced.llm_trace
    assert "response_preview" not in traced.llm_trace
    assert "ROUTING-REASONING-CANARY" not in caplog.text
    assert "ROUTING-RESPONSE-CANARY" not in caplog.text
    assert "Response chars:" in caplog.text


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


def test_orchestration_launch_handler_reads_orchestration_plan_from_intent() -> None:
    """OrchestrationLaunchHandler consumes the typed plan attached to intent."""
    import inspect
    from magi.agent.task_agents.common.handlers import OrchestrationLaunchHandler

    src = inspect.getsource(OrchestrationLaunchHandler.execute)
    assert "orchestration_plan" in src, (
        "OrchestrationLaunchHandler.execute must read intent.orchestration_plan"
    )


def test_chat_coordinator_match_intent_signature_returns_intent_decision_from_route() -> None:
    """Chat intent resolution must continue to return an IntentDecision
    even after the underlying ContextDecider returns RouteDecision. The
    chat intent resolver translates RouteDecision → IntentDecision (which still has
    fields the rest of chat consumes: execution_mode, tools, thinking_depth,
    orchestration_plan, persona_routing_hint, etc.)."""
    import inspect
    from magi.chat.task_agent.intent_resolution_service import ChatIntentResolutionService

    src = inspect.getsource(ChatIntentResolutionService._build_intent_decision)
    assert "decision.graph_shape" in src or "decision.profile" in src, (
        "chat intent resolution must consume RouteDecision fields directly, not "
        "the old orchestration strategy dict"
    )


def test_task_orchestrator_start_accepts_typed_orchestration_plan() -> None:
    import inspect
    from magi.agent.task_orchestrator import TaskOrchestrator

    sig = inspect.signature(TaskOrchestrator.start_orchestration)
    assert "orchestration_plan" in sig.parameters


def test_memory_guidance_marks_added_memory_tool_as_direct_need() -> None:
    from magi.tools.context_routing.memory_guidance import apply_memory_guidance

    decision = RouteDecision(
        profile="chat",
        graph_shape="reply",
        complexity="simple",
        tool_need="none",
        tools=[],
    )

    result = apply_memory_guidance(
        user_message="你还记得我上次说了什么吗",
        context={},
        decision=decision,
        available_tools=[{"name": "memory_query"}],
        max_tools=5,
    )

    assert result.tools == ["memory_query"]
    assert result.tool_need == "direct"
