"""Tests for shared interaction-analysis contracts and parsing."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest

from magi.config.models import LLMScenario
from magi.personality.models import SatisfactionLevel
from magi.personality.emotional_state import EngagementLevel, InteractionOutcome
from magi.personality.interaction_analyzer import (
    DEFAULT_ANALYSIS,
    InteractionAnalysis,
    InteractionObservation,
    _compact_observation_args,
    _resolve_analysis_bridge,
    _with_memory_observations,
    parse_analysis,
)


def _payload(**overrides: object) -> str:
    data: dict[str, object] = {
        "sentiment": 0.7,
        "engagement": "high",
        "complexity": 0.8,
        "outcome": "success",
        "satisfaction": "high",
    }
    data.update(overrides)
    return json.dumps(data)


def test_parse_analysis_maps_valid_values() -> None:
    result = parse_analysis(_payload())

    assert result.sentiment == pytest.approx(0.7)
    assert result.engagement == EngagementLevel.HIGH
    assert result.complexity == pytest.approx(0.8)
    assert result.outcome == InteractionOutcome.SUCCESS
    assert result.satisfaction == SatisfactionLevel.HIGH


def test_parse_analysis_clamps_numbers_and_defaults_unknown_enums() -> None:
    result = parse_analysis(
        _payload(
            sentiment=3,
            complexity=-1,
            engagement="unknown",
            outcome="unknown",
            satisfaction="unknown",
        )
    )

    assert result.sentiment == pytest.approx(1.0)
    assert result.complexity == pytest.approx(0.0)
    assert result.engagement == EngagementLevel.MEDIUM
    assert result.outcome == InteractionOutcome.SUCCESS
    assert result.satisfaction == SatisfactionLevel.NEUTRAL


@pytest.mark.parametrize("raw", ["not json", None])
def test_parse_analysis_returns_default_for_invalid_input(raw: str | None) -> None:
    assert parse_analysis(raw) == DEFAULT_ANALYSIS  # type: ignore[arg-type]


def test_parse_analysis_accepts_only_configured_trigger_types() -> None:
    rules = [{"trigger_type": "focus", "trigger_condition": "User requests focus"}]

    assert parse_analysis(_payload(trigger_type="focus"), stp_rules=rules).trigger_type == "focus"
    assert parse_analysis(_payload(trigger_type="other"), stp_rules=rules).trigger_type is None
    assert parse_analysis(_payload(trigger_type="focus")).trigger_type is None


def test_parse_analysis_filters_milestone_keys() -> None:
    result = parse_analysis(
        _payload(milestone_keys=["seven_guard_down", 123, None, "", "trust_earned"])
    )

    assert result.milestone_keys == ["seven_guard_down", "trust_earned"]


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (InteractionOutcome.SUCCESS, "success"),
        (InteractionOutcome.PARTIAL_SUCCESS, "partial"),
        (InteractionOutcome.FAILURE, "failure"),
    ],
)
def test_outcome_str(outcome: InteractionOutcome, expected: str) -> None:
    analysis = InteractionAnalysis(
        sentiment=0.0,
        engagement=EngagementLevel.MEDIUM,
        complexity=0.5,
        outcome=outcome,
        satisfaction=SatisfactionLevel.NEUTRAL,
    )

    assert analysis.outcome_str == expected


def test_compact_observation_args_normalizes_supported_values() -> None:
    result = _compact_observation_args(
        {
            " evidence ": "  concise   evidence  ",
            "confidence": 0.9,
            "tags": [" one ", "", "two"],
            "nested": {"ignored": True},
            "": "ignored",
        }
    )

    assert result == {
        "evidence": "concise evidence",
        "confidence": 0.9,
        "tags": ["one", "two"],
    }


def test_with_memory_observations_preserves_analysis_fields() -> None:
    observation = InteractionObservation(
        kind="profile_signal",
        arguments={"trait_name": "communication.style"},
    )

    result = _with_memory_observations(DEFAULT_ANALYSIS, [observation])

    assert result.sentiment == DEFAULT_ANALYSIS.sentiment
    assert result.outcome == DEFAULT_ANALYSIS.outcome
    assert result.memory_observations == [observation]


def test_resolve_analysis_bridge_returns_none_when_pool_is_unavailable() -> None:
    with patch(
        "magi.personality.interaction_analyzer.get_scenario_llm_pool",
        side_effect=RuntimeError("unavailable"),
    ):
        assert _resolve_analysis_bridge() is None


def test_resolve_analysis_bridge_falls_back_to_core() -> None:
    pool = MagicMock()
    adapter = object()
    bridge = object()
    pool.get.side_effect = [ValueError("missing"), adapter]

    with (
        patch(
            "magi.personality.interaction_analyzer.get_scenario_llm_pool",
            return_value=pool,
        ),
        patch(
            "magi.personality.interaction_analyzer.LLMProviderBridge",
            return_value=bridge,
        ),
    ):
        assert _resolve_analysis_bridge() is bridge

    assert pool.get.call_args_list == [
        call(LLMScenario.AUXILIARY),
        call(LLMScenario.CORE),
    ]
