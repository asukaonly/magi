"""Tests for personality.interaction_analyzer module."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.personality.interaction_analyzer import (
    DEFAULT_ANALYSIS,
    InteractionAnalysis,
    InteractionObservation,
    _build_system_prompt,
    analyze_interaction,
    parse_analysis,
)
from magi.llm.provider_bridge.models import ProviderResponse, ProviderToolCall
from magi.personality.behavior_evolution import SatisfactionLevel
from magi.personality.emotional_state import EngagementLevel, InteractionOutcome


# ---------- parse_analysis ----------


class TestParseAnalysis:
    def test_valid_json(self):
        raw = json.dumps({
            "sentiment": 0.7,
            "engagement": "high",
            "complexity": 0.8,
            "outcome": "success",
            "satisfaction": "high",
        })
        result = parse_analysis(raw)
        assert result.sentiment == pytest.approx(0.7)
        assert result.engagement == EngagementLevel.HIGH
        assert result.complexity == pytest.approx(0.8)
        assert result.outcome == InteractionOutcome.SUCCESS
        assert result.satisfaction == SatisfactionLevel.HIGH

    def test_negative_sentiment(self):
        raw = json.dumps({
            "sentiment": -0.5,
            "engagement": "low",
            "complexity": 0.2,
            "outcome": "failure",
            "satisfaction": "very_low",
        })
        result = parse_analysis(raw)
        assert result.sentiment == pytest.approx(-0.5)
        assert result.engagement == EngagementLevel.LOW
        assert result.outcome == InteractionOutcome.FAILURE
        assert result.satisfaction == SatisfactionLevel.VERY_LOW

    def test_partial_outcome(self):
        raw = json.dumps({
            "sentiment": 0.1,
            "engagement": "medium",
            "complexity": 0.5,
            "outcome": "partial",
            "satisfaction": "neutral",
        })
        result = parse_analysis(raw)
        assert result.outcome == InteractionOutcome.PARTIAL_SUCCESS

    def test_clamp_sentiment_above(self):
        raw = json.dumps({"sentiment": 2.5, "engagement": "medium", "complexity": 0.5, "outcome": "success", "satisfaction": "neutral"})
        result = parse_analysis(raw)
        assert result.sentiment == pytest.approx(1.0)

    def test_clamp_sentiment_below(self):
        raw = json.dumps({"sentiment": -3.0, "engagement": "medium", "complexity": 0.5, "outcome": "success", "satisfaction": "neutral"})
        result = parse_analysis(raw)
        assert result.sentiment == pytest.approx(-1.0)

    def test_clamp_complexity_above(self):
        raw = json.dumps({"sentiment": 0.0, "engagement": "medium", "complexity": 1.5, "outcome": "success", "satisfaction": "neutral"})
        result = parse_analysis(raw)
        assert result.complexity == pytest.approx(1.0)

    def test_clamp_complexity_below(self):
        raw = json.dumps({"sentiment": 0.0, "engagement": "medium", "complexity": -0.3, "outcome": "success", "satisfaction": "neutral"})
        result = parse_analysis(raw)
        assert result.complexity == pytest.approx(0.0)

    def test_missing_fields_use_defaults(self):
        raw = json.dumps({})
        result = parse_analysis(raw)
        assert result.sentiment == pytest.approx(0.0)
        assert result.engagement == EngagementLevel.MEDIUM
        assert result.complexity == pytest.approx(0.5)
        assert result.outcome == InteractionOutcome.SUCCESS
        assert result.satisfaction == SatisfactionLevel.NEUTRAL

    def test_unknown_enum_values_use_defaults(self):
        raw = json.dumps({
            "sentiment": 0.0,
            "engagement": "super_high",
            "complexity": 0.5,
            "outcome": "unknown_status",
            "satisfaction": "ecstatic",
        })
        result = parse_analysis(raw)
        assert result.engagement == EngagementLevel.MEDIUM
        assert result.outcome == InteractionOutcome.SUCCESS
        assert result.satisfaction == SatisfactionLevel.NEUTRAL

    def test_invalid_json_returns_default(self):
        result = parse_analysis("not valid json {{{")
        assert result == DEFAULT_ANALYSIS

    def test_none_input_returns_default(self):
        result = parse_analysis(None)  # type: ignore[arg-type]
        assert result == DEFAULT_ANALYSIS

    def test_non_numeric_sentiment_defaults(self):
        raw = json.dumps({"sentiment": "very positive", "complexity": "hard"})
        result = parse_analysis(raw)
        assert result.sentiment == pytest.approx(0.0)
        assert result.complexity == pytest.approx(0.5)


# ---------- InteractionAnalysis.outcome_str ----------


class TestOutcomeStr:
    def test_success(self):
        a = InteractionAnalysis(0.0, EngagementLevel.MEDIUM, 0.5, InteractionOutcome.SUCCESS, SatisfactionLevel.NEUTRAL)
        assert a.outcome_str == "success"

    def test_partial(self):
        a = InteractionAnalysis(0.0, EngagementLevel.MEDIUM, 0.5, InteractionOutcome.PARTIAL_SUCCESS, SatisfactionLevel.NEUTRAL)
        assert a.outcome_str == "partial"

    def test_failure(self):
        a = InteractionAnalysis(0.0, EngagementLevel.MEDIUM, 0.5, InteractionOutcome.FAILURE, SatisfactionLevel.NEUTRAL)
        assert a.outcome_str == "failure"


# ---------- analyze_interaction ----------


class TestAnalyzeInteraction:
    @pytest.mark.asyncio
    async def test_returns_default_when_pool_unavailable(self):
        with patch(
            "magi.personality.interaction_analyzer.get_scenario_llm_pool",
            side_effect=RuntimeError("no pool"),
        ):
            result = await analyze_interaction("hello", "hi there")
            assert result == DEFAULT_ANALYSIS

    @pytest.mark.asyncio
    async def test_returns_default_when_no_scenario_adapter(self):
        mock_pool = MagicMock()
        mock_pool.get.side_effect = ValueError("no adapter")
        with patch(
            "magi.personality.interaction_analyzer.get_scenario_llm_pool",
            return_value=mock_pool,
        ):
            result = await analyze_interaction("hello", "hi there")
            assert result == DEFAULT_ANALYSIS

    @pytest.mark.asyncio
    async def test_successful_analysis(self):
        llm_response = json.dumps({
            "sentiment": 0.6,
            "engagement": "high",
            "complexity": 0.3,
            "outcome": "success",
            "satisfaction": "high",
        })

        mock_adapter = MagicMock()
        mock_bridge = MagicMock()
        mock_bridge.chat = AsyncMock(return_value=llm_response)

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_adapter

        with (
            patch(
                "magi.personality.interaction_analyzer.get_scenario_llm_pool",
                return_value=mock_pool,
            ),
            patch(
                "magi.personality.interaction_analyzer.LLMProviderBridge",
                return_value=mock_bridge,
            ),
        ):
            result = await analyze_interaction("Thank you, that was helpful!", "You're welcome!")
            assert result.sentiment == pytest.approx(0.6)
            assert result.engagement == EngagementLevel.HIGH
            assert result.satisfaction == SatisfactionLevel.HIGH

    @pytest.mark.asyncio
    async def test_tool_observer_returns_analysis_and_memory_observations(self):
        mock_adapter = MagicMock()
        mock_bridge = MagicMock()
        mock_bridge.chat_with_tools = AsyncMock(
            return_value=ProviderResponse(
                content="",
                tool_calls=[
                    ProviderToolCall(
                        id="call-analysis",
                        name="submit_interaction_analysis",
                        arguments={
                            "sentiment": 0.4,
                            "engagement": "high",
                            "complexity": 0.6,
                            "outcome": "success",
                            "satisfaction": "high",
                        },
                    ),
                    ProviderToolCall(
                        id="call-profile",
                        name="remember_profile_signal",
                        arguments={
                            "trait_family": "communication_profile",
                            "trait_name": "communication.response_style.preferred",
                            "trait_value": "先说结论，再说风险",
                            "evidence_text": "以后这种方案讨论，先说结论，再说风险。",
                            "confidence": 0.9,
                        },
                    ),
                    ProviderToolCall(
                        id="call-relationship",
                        name="record_persona_relationship_signal",
                        arguments={
                            "signal_type": "milestone",
                            "milestone_key": "seven_guard_down",
                            "evidence_text": "七号这里可以稍微软一点。",
                            "confidence": 0.86,
                        },
                    ),
                ],
            )
        )

        mock_pool = MagicMock()
        mock_pool.get.return_value = mock_adapter

        with (
            patch(
                "magi.personality.interaction_analyzer.get_scenario_llm_pool",
                return_value=mock_pool,
            ),
            patch(
                "magi.personality.interaction_analyzer.LLMProviderBridge",
                return_value=mock_bridge,
            ),
        ):
            result = await analyze_interaction(
                "以后这种方案讨论，先说结论，再说风险。",
                "好，我按这个顺序说。",
                milestone_conditions={"seven_guard_down": "User earns deeper trust."},
            )

        assert result.sentiment == pytest.approx(0.4)
        assert result.engagement == EngagementLevel.HIGH
        assert result.satisfaction == SatisfactionLevel.HIGH
        assert result.memory_observations == [
            InteractionObservation(
                kind="profile_signal",
                arguments={
                    "trait_family": "communication_profile",
                    "trait_name": "communication.response_style.preferred",
                    "trait_value": "先说结论，再说风险",
                    "evidence_text": "以后这种方案讨论，先说结论，再说风险。",
                    "confidence": 0.9,
                },
            ),
            InteractionObservation(
                kind="persona_relationship_signal",
                arguments={
                    "signal_type": "milestone",
                    "milestone_key": "seven_guard_down",
                    "evidence_text": "七号这里可以稍微软一点。",
                    "confidence": 0.86,
                },
            ),
        ]
        mock_bridge.chat.assert_not_called()
        assert mock_bridge.chat_with_tools.call_args[1]["max_tokens"] <= 256

    @pytest.mark.asyncio
    async def test_llm_call_failure_returns_default(self):
        mock_bridge = MagicMock()
        mock_bridge.chat = AsyncMock(side_effect=RuntimeError("LLM error"))

        mock_pool = MagicMock()
        mock_pool.get.return_value = MagicMock()

        with (
            patch(
                "magi.personality.interaction_analyzer.get_scenario_llm_pool",
                return_value=mock_pool,
            ),
            patch(
                "magi.personality.interaction_analyzer.LLMProviderBridge",
                return_value=mock_bridge,
            ),
        ):
            result = await analyze_interaction("hello", "hi")
            assert result == DEFAULT_ANALYSIS

    @pytest.mark.asyncio
    async def test_falls_back_to_core_scenario(self):
        """When CONTEXT_DECIDER is unavailable, falls back to CORE."""
        llm_response = json.dumps({
            "sentiment": 0.0,
            "engagement": "medium",
            "complexity": 0.5,
            "outcome": "success",
            "satisfaction": "neutral",
        })

        mock_adapter = MagicMock()
        mock_bridge = MagicMock()
        mock_bridge.chat = AsyncMock(return_value=llm_response)

        call_count = 0

        def get_side_effect(scenario):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("no CONTEXT_DECIDER")
            return mock_adapter

        mock_pool = MagicMock()
        mock_pool.get.side_effect = get_side_effect

        with (
            patch(
                "magi.personality.interaction_analyzer.get_scenario_llm_pool",
                return_value=mock_pool,
            ),
            patch(
                "magi.personality.interaction_analyzer.LLMProviderBridge",
                return_value=mock_bridge,
            ),
        ):
            result = await analyze_interaction("hello", "hi")
            assert result.outcome == InteractionOutcome.SUCCESS
            assert call_count == 2


# ---------- trigger_type in parse_analysis ----------


class TestParseAnalysisTriggerType:
    def test_valid_trigger_type_parsed_with_matching_rules(self):
        raw = json.dumps({
            "sentiment": 0.0,
            "engagement": "medium",
            "complexity": 0.5,
            "outcome": "success",
            "satisfaction": "neutral",
            "trigger_type": "crisis",
        })
        rules = [{"trigger_type": "crisis", "trigger_condition": "User in danger"}]
        result = parse_analysis(raw, stp_rules=rules)
        assert result.trigger_type == "crisis"

    def test_valid_trigger_type_ignored_without_rules(self):
        raw = json.dumps({
            "sentiment": 0.0,
            "engagement": "medium",
            "complexity": 0.5,
            "outcome": "success",
            "satisfaction": "neutral",
            "trigger_type": "crisis",
        })
        result = parse_analysis(raw)
        assert result.trigger_type is None

    def test_unknown_trigger_type_ignored(self):
        raw = json.dumps({
            "sentiment": 0.0,
            "engagement": "medium",
            "complexity": 0.5,
            "outcome": "success",
            "satisfaction": "neutral",
            "trigger_type": "unknown_type",
        })
        rules = [{"trigger_type": "crisis", "trigger_condition": "User in danger"}]
        result = parse_analysis(raw, stp_rules=rules)
        assert result.trigger_type is None

    def test_null_trigger_type(self):
        raw = json.dumps({
            "sentiment": 0.0,
            "engagement": "medium",
            "complexity": 0.5,
            "outcome": "success",
            "satisfaction": "neutral",
            "trigger_type": None,
        })
        result = parse_analysis(raw)
        assert result.trigger_type is None

    def test_missing_trigger_type_defaults_to_none(self):
        raw = json.dumps({
            "sentiment": 0.0,
            "engagement": "medium",
            "complexity": 0.5,
            "outcome": "success",
            "satisfaction": "neutral",
        })
        result = parse_analysis(raw)
        assert result.trigger_type is None

    def test_all_four_trigger_types_with_rules(self):
        for tt in ("crisis", "intimacy", "hostility", "absurdity"):
            raw = json.dumps({
                "sentiment": 0.0,
                "engagement": "medium",
                "complexity": 0.5,
                "outcome": "success",
                "satisfaction": "neutral",
                "trigger_type": tt,
            })
            rules = [{"trigger_type": tt, "trigger_condition": "test"}]
            result = parse_analysis(raw, stp_rules=rules)
            assert result.trigger_type == tt

    def test_custom_trigger_type_accepted(self):
        raw = json.dumps({
            "sentiment": 0.0,
            "engagement": "medium",
            "complexity": 0.5,
            "outcome": "success",
            "satisfaction": "neutral",
            "trigger_type": "focus_mode",
        })
        rules = [{"trigger_type": "focus_mode", "trigger_condition": "User requests focus"}]
        result = parse_analysis(raw, stp_rules=rules)
        assert result.trigger_type == "focus_mode"


# ---------- _build_system_prompt ----------


class TestBuildSystemPrompt:
    def test_no_rules_returns_base_prompt(self):
        prompt = _build_system_prompt(None)
        assert "trigger_type" not in prompt

    def test_empty_rules_returns_base_prompt(self):
        prompt = _build_system_prompt([])
        assert "trigger_type" not in prompt

    def test_with_rules_appends_stp_block(self):
        rules = [
            {"trigger_type": "crisis", "trigger_condition": "User is in danger"},
            {"trigger_type": "hostility", "trigger_condition": "User is aggressive"},
        ]
        prompt = _build_system_prompt(rules)
        assert '"crisis"' in prompt
        assert "User is in danger" in prompt
        assert '"hostility"' in prompt
        assert "trigger_type" in prompt


# ---------- analyze_interaction with stp_rules ----------


class TestAnalyzeInteractionWithStp:
    @pytest.mark.asyncio
    async def test_stp_trigger_detected(self):
        llm_response = json.dumps({
            "sentiment": -0.3,
            "engagement": "high",
            "complexity": 0.4,
            "outcome": "success",
            "satisfaction": "neutral",
            "trigger_type": "hostility",
        })

        mock_bridge = MagicMock()
        mock_bridge.chat = AsyncMock(return_value=llm_response)

        mock_pool = MagicMock()
        mock_pool.get.return_value = MagicMock()

        stp_rules = [
            {"trigger_type": "hostility", "trigger_condition": "User is aggressive"},
        ]

        with (
            patch(
                "magi.personality.interaction_analyzer.get_scenario_llm_pool",
                return_value=mock_pool,
            ),
            patch(
                "magi.personality.interaction_analyzer.LLMProviderBridge",
                return_value=mock_bridge,
            ),
        ):
            result = await analyze_interaction("You're useless!", "I'm sorry.", stp_rules=stp_rules)
            assert result.trigger_type == "hostility"
            # Verify the system prompt included STP context.
            call_kwargs = mock_bridge.chat.call_args[1]
            assert "hostility" in call_kwargs["system_prompt"]

    @pytest.mark.asyncio
    async def test_no_stp_rules_still_works(self):
        llm_response = json.dumps({
            "sentiment": 0.5,
            "engagement": "medium",
            "complexity": 0.3,
            "outcome": "success",
            "satisfaction": "high",
        })

        mock_bridge = MagicMock()
        mock_bridge.chat = AsyncMock(return_value=llm_response)

        mock_pool = MagicMock()
        mock_pool.get.return_value = MagicMock()

        with (
            patch(
                "magi.personality.interaction_analyzer.get_scenario_llm_pool",
                return_value=mock_pool,
            ),
            patch(
                "magi.personality.interaction_analyzer.LLMProviderBridge",
                return_value=mock_bridge,
            ),
        ):
            result = await analyze_interaction("Great job!", "Thanks!")
            assert result.trigger_type is None
            assert result.satisfaction == SatisfactionLevel.HIGH


# ---------- milestone_keys in parse_analysis ----------


class TestParseAnalysisMilestoneKeys:
    def test_valid_milestone_keys_parsed(self):
        raw = json.dumps({
            "sentiment": 0.0,
            "engagement": "medium",
            "complexity": 0.5,
            "outcome": "success",
            "satisfaction": "neutral",
            "milestone_keys": ["seven_guard_down"],
        })
        result = parse_analysis(raw)
        assert result.milestone_keys == ["seven_guard_down"]

    def test_multiple_milestone_keys(self):
        raw = json.dumps({
            "sentiment": 0.0,
            "engagement": "medium",
            "complexity": 0.5,
            "outcome": "success",
            "satisfaction": "neutral",
            "milestone_keys": ["alan_depth_reached", "kai_trust_earned"],
        })
        result = parse_analysis(raw)
        assert result.milestone_keys == ["alan_depth_reached", "kai_trust_earned"]

    def test_empty_milestone_keys(self):
        raw = json.dumps({
            "sentiment": 0.0,
            "engagement": "medium",
            "complexity": 0.5,
            "outcome": "success",
            "satisfaction": "neutral",
            "milestone_keys": [],
        })
        result = parse_analysis(raw)
        assert result.milestone_keys == []

    def test_missing_milestone_keys_defaults_to_empty(self):
        raw = json.dumps({
            "sentiment": 0.0,
            "engagement": "medium",
            "complexity": 0.5,
            "outcome": "success",
            "satisfaction": "neutral",
        })
        result = parse_analysis(raw)
        assert result.milestone_keys == []

    def test_null_milestone_keys(self):
        raw = json.dumps({
            "sentiment": 0.0,
            "engagement": "medium",
            "complexity": 0.5,
            "outcome": "success",
            "satisfaction": "neutral",
            "milestone_keys": None,
        })
        result = parse_analysis(raw)
        assert result.milestone_keys == []

    def test_non_string_milestone_keys_filtered(self):
        raw = json.dumps({
            "sentiment": 0.0,
            "engagement": "medium",
            "complexity": 0.5,
            "outcome": "success",
            "satisfaction": "neutral",
            "milestone_keys": ["valid_key", 123, None, "", "another_key"],
        })
        result = parse_analysis(raw)
        assert result.milestone_keys == ["valid_key", "another_key"]


# ---------- _build_system_prompt with milestone_conditions ----------


class TestBuildSystemPromptMilestones:
    def test_no_milestones_returns_base_prompt(self):
        prompt = _build_system_prompt(None, None)
        assert "milestone_keys" not in prompt

    def test_empty_milestones_returns_base_prompt(self):
        prompt = _build_system_prompt(None, {})
        assert "milestone_keys" not in prompt

    def test_with_milestones_appends_block(self):
        conditions = {
            "seven_guard_down": "User protects her innocence",
            "alan_depth_reached": "User shares deep confusion",
        }
        prompt = _build_system_prompt(None, conditions)
        assert '"seven_guard_down"' in prompt
        assert "User protects her innocence" in prompt
        assert '"alan_depth_reached"' in prompt
        assert "milestone_keys" in prompt

    def test_both_stp_and_milestones(self):
        stp_rules = [
            {"trigger_type": "crisis", "trigger_condition": "User is in danger"},
        ]
        conditions = {
            "seven_guard_down": "User protects her innocence",
        }
        prompt = _build_system_prompt(stp_rules, conditions)
        assert "trigger_type" in prompt
        assert "milestone_keys" in prompt
        assert '"crisis"' in prompt
        assert '"seven_guard_down"' in prompt


# ---------- analyze_interaction with milestone_conditions ----------


class TestAnalyzeInteractionWithMilestones:
    @pytest.mark.asyncio
    async def test_milestone_detected(self):
        llm_response = json.dumps({
            "sentiment": 0.8,
            "engagement": "very_high",
            "complexity": 0.7,
            "outcome": "success",
            "satisfaction": "very_high",
            "milestone_keys": ["seven_guard_down"],
        })

        mock_bridge = MagicMock()
        mock_bridge.chat = AsyncMock(return_value=llm_response)

        mock_pool = MagicMock()
        mock_pool.get.return_value = MagicMock()

        conditions = {"seven_guard_down": "User protects her innocence"}

        with (
            patch(
                "magi.personality.interaction_analyzer.get_scenario_llm_pool",
                return_value=mock_pool,
            ),
            patch(
                "magi.personality.interaction_analyzer.LLMProviderBridge",
                return_value=mock_bridge,
            ),
        ):
            result = await analyze_interaction(
                "I know you push everyone away, but I see you",
                "...fine. Maybe you do.",
                milestone_conditions=conditions,
            )
            assert result.milestone_keys == ["seven_guard_down"]
            call_kwargs = mock_bridge.chat.call_args[1]
            assert "seven_guard_down" in call_kwargs["system_prompt"]

    @pytest.mark.asyncio
    async def test_no_milestones_still_works(self):
        llm_response = json.dumps({
            "sentiment": 0.5,
            "engagement": "medium",
            "complexity": 0.3,
            "outcome": "success",
            "satisfaction": "high",
        })

        mock_bridge = MagicMock()
        mock_bridge.chat = AsyncMock(return_value=llm_response)

        mock_pool = MagicMock()
        mock_pool.get.return_value = MagicMock()

        with (
            patch(
                "magi.personality.interaction_analyzer.get_scenario_llm_pool",
                return_value=mock_pool,
            ),
            patch(
                "magi.personality.interaction_analyzer.LLMProviderBridge",
                return_value=mock_bridge,
            ),
        ):
            result = await analyze_interaction("Hello!", "Hi there!")
            assert result.milestone_keys == []
