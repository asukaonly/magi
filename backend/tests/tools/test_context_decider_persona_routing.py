"""Tests for ContextDecider persona-routing JSON parsing (P1 unified router)."""

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
        "intent": "chat",
        "tools": [],
        "thinking_depth": "none",
        "reasoning": "casual",
        "orchestration_strategy": {"mode": "direct", "planner": "task_agent"},
        "register": "emotional",
        "active_trigger_ids": ["absurdity", "hostility"],
        "situation_strength": "strong",
        "quiet_hour_hints": ["用户提出简单事实问题"],
    })
    decision = _decider()._parse_response(response)

    assert decision.register == "emotional"
    assert decision.active_trigger_ids == ["absurdity", "hostility"]
    assert decision.situation_strength == "strong"
    assert decision.quiet_hour_hints == ["用户提出简单事实问题"]


def test_parse_response_missing_persona_fields_keeps_defaults() -> None:
    response = json.dumps({
        "intent": "chat",
        "tools": [],
        "thinking_depth": "none",
        "reasoning": "no persona fields",
        "orchestration_strategy": {"mode": "direct", "planner": "task_agent"},
    })
    decision = _decider()._parse_response(response)

    assert decision.register is None
    assert decision.active_trigger_ids == []
    assert decision.situation_strength == "ordinary"
    assert decision.quiet_hour_hints == []


def test_parse_response_drops_unknown_register_value() -> None:
    response = json.dumps({
        "intent": "chat",
        "tools": [],
        "thinking_depth": "none",
        "reasoning": "test",
        "orchestration_strategy": {"mode": "direct", "planner": "task_agent"},
        "register": "not_a_real_register",
    })
    decision = _decider()._parse_response(response)
    assert decision.register is None


def test_parse_response_caps_active_trigger_ids_at_two() -> None:
    response = json.dumps({
        "intent": "chat",
        "tools": [],
        "thinking_depth": "none",
        "reasoning": "test",
        "orchestration_strategy": {"mode": "direct", "planner": "task_agent"},
        "active_trigger_ids": ["a", "b", "c", "d"],
    })
    decision = _decider()._parse_response(response)
    assert len(decision.active_trigger_ids) == 2


def test_parse_response_filters_non_string_trigger_ids() -> None:
    response = json.dumps({
        "intent": "chat",
        "tools": [],
        "thinking_depth": "none",
        "reasoning": "test",
        "orchestration_strategy": {"mode": "direct", "planner": "task_agent"},
        "active_trigger_ids": [None, 42, "ok", ""],
    })
    decision = _decider()._parse_response(response)
    assert decision.active_trigger_ids == ["ok"]


def test_parse_response_normalizes_situation_strength_default() -> None:
    response = json.dumps({
        "intent": "chat",
        "tools": [],
        "thinking_depth": "none",
        "reasoning": "test",
        "orchestration_strategy": {"mode": "direct", "planner": "task_agent"},
        "situation_strength": "WEIRD_VALUE",
    })
    decision = _decider()._parse_response(response)
    assert decision.situation_strength == "ordinary"


def test_parse_response_accepts_all_three_situation_strengths() -> None:
    for value in ("ordinary", "strong", "crisis"):
        response = json.dumps({
            "intent": "chat",
            "tools": [],
            "thinking_depth": "none",
            "reasoning": "test",
            "orchestration_strategy": {"mode": "direct", "planner": "task_agent"},
            "situation_strength": value,
        })
        decision = _decider()._parse_response(response)
        assert decision.situation_strength == value
