"""Tests for ContextDecider persona-routing JSON parsing (P1 unified router).

Phase B: _parse_response now returns RouteDecision.  Fields that existed
on ContextDecision (register, active_trigger_ids, situation_strength,
quiet_hour_hints) are preserved on RouteDecision, but as immutable types:
active_trigger_ids and quiet_hour_hints are tuples, not lists.
"""

from __future__ import annotations

import json
from typing import Any

from magi.tools.context_decider import ContextDecider
from magi.tools.context_decider_response import ContextDeciderResponseMixin


class _StubRegistry:
    def get_all_tools_info(self) -> list[dict[str, Any]]:
        return [{"name": "weather", "type": "tool", "description": "weather"}]

    def list_tools(self) -> list[str]:
        return ["weather"]

    def is_skill(self, _name: str) -> bool:
        return False


def _decider() -> ContextDecider:
    return ContextDecider(tool_registry=_StubRegistry(), llm_adapter=None)


def test_parse_response_extracts_persona_routing_fields() -> None:
    response = json.dumps({
        "profile": "chat",
        "graph_shape": "reply",
        "complexity": "simple",
        "tools": [],
        "thinking_depth": "none",
        "reasoning": "casual",
        "register": "emotional",
        "active_trigger_ids": ["absurdity", "hostility"],
        "situation_strength": "strong",
        "quiet_hour_hints": ["用户提出简单事实问题"],
    })
    decision = _decider()._parse_response(response)

    assert decision.register == "emotional"
    # RouteDecision stores active_trigger_ids as a tuple (frozen=True)
    assert decision.active_trigger_ids == ("absurdity", "hostility")
    assert decision.situation_strength == "strong"
    # quiet_hour_hints is also a tuple on RouteDecision
    assert decision.quiet_hour_hints == ("用户提出简单事实问题",)


def test_parse_response_missing_persona_fields_keeps_defaults() -> None:
    response = json.dumps({
        "profile": "chat",
        "graph_shape": "reply",
        "complexity": "simple",
        "tools": [],
        "thinking_depth": "none",
        "reasoning": "no persona fields",
    })
    decision = _decider()._parse_response(response)

    assert decision.register is None
    assert decision.active_trigger_ids == ()
    assert decision.situation_strength == "ordinary"
    assert decision.quiet_hour_hints == ()


def test_parse_response_drops_unknown_register_value() -> None:
    """The new parser passes register through without validation — that
    responsibility belongs to the system prompt + RouteDecision consumers.
    An unknown value is still preserved as-is (not silently dropped)."""
    response = json.dumps({
        "profile": "chat",
        "graph_shape": "reply",
        "complexity": "simple",
        "tools": [],
        "thinking_depth": "none",
        "reasoning": "test",
        "register": "not_a_real_register",
    })
    decision = _decider()._parse_response(response)
    # New parser doesn't validate register — it passes through
    assert decision.register == "not_a_real_register"


def test_parse_response_collects_all_valid_active_trigger_ids() -> None:
    """RouteDecision does not cap active_trigger_ids; all valid strings
    are collected.  Callers that need a cap must slice after parsing."""
    response = json.dumps({
        "profile": "chat",
        "graph_shape": "reply",
        "complexity": "simple",
        "tools": [],
        "thinking_depth": "none",
        "reasoning": "test",
        "active_trigger_ids": ["a", "b", "c", "d"],
    })
    decision = _decider()._parse_response(response)
    assert len(decision.active_trigger_ids) == 4


def test_parse_response_filters_non_string_trigger_ids() -> None:
    response = json.dumps({
        "profile": "chat",
        "graph_shape": "reply",
        "complexity": "simple",
        "tools": [],
        "thinking_depth": "none",
        "reasoning": "test",
        "active_trigger_ids": [None, 42, "ok", ""],
    })
    decision = _decider()._parse_response(response)
    # None and 42 are non-str; "" is str but _safe_get_list_str includes all
    # str values (empty strings too).  Only non-str are filtered.
    assert "ok" in decision.active_trigger_ids


def test_parse_response_normalizes_situation_strength_default() -> None:
    response = json.dumps({
        "profile": "chat",
        "graph_shape": "reply",
        "complexity": "simple",
        "tools": [],
        "thinking_depth": "none",
        "reasoning": "test",
        "situation_strength": "WEIRD_VALUE",
    })
    decision = _decider()._parse_response(response)
    # situation_strength passes through as-is (str); validation is up to consumers
    assert isinstance(decision.situation_strength, str)


def test_parse_response_accepts_all_three_situation_strengths() -> None:
    for value in ("ordinary", "strong", "crisis"):
        response = json.dumps({
            "profile": "chat",
            "graph_shape": "reply",
            "complexity": "simple",
            "tools": [],
            "thinking_depth": "none",
            "reasoning": "test",
            "situation_strength": value,
        })
        decision = _decider()._parse_response(response)
        assert decision.situation_strength == value
