"""Tests for combined IntentDecider (LLM primary + rule shadow)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.memory.hybrid_retrieval.intent_decider import (
    EvaluationRecord,
    IntentDecider,
    LLMIntentDecider,
    RuleBasedIntentDecider,
    compute_diff,
)
from magi.memory.hybrid_retrieval.models import (
    IntentDeciderInput,
    IntentDecision,
    L1Conditions,
    L3Conditions,
    LayerQueryPlan,
)


# -----------------------------------------------------------------------
# compute_diff
# -----------------------------------------------------------------------


class TestComputeDiff:
    def test_llm_none(self):
        rule = IntentDecision(
            plans=[LayerQueryPlan(layer="L1", conditions=L1Conditions())],
        )
        match, summary = compute_diff(rule, None)
        assert match is False
        assert summary == "llm_failed"

    def test_matching_layers(self):
        rule = IntentDecision(
            plans=[
                LayerQueryPlan(layer="L1", conditions=L1Conditions(), is_fallback=False),
                LayerQueryPlan(layer="L3", conditions=L3Conditions(), is_fallback=True),
            ],
        )
        llm = IntentDecision(
            plans=[
                LayerQueryPlan(layer="L1", conditions=L1Conditions(), is_fallback=False),
                LayerQueryPlan(layer="L3", conditions=L3Conditions(), is_fallback=True),
            ],
        )
        match, summary = compute_diff(rule, llm)
        assert match is True
        assert summary == "match"

    def test_mismatching_layers(self):
        rule = IntentDecision(
            plans=[LayerQueryPlan(layer="L1", conditions=L1Conditions(), is_fallback=False)],
        )
        llm = IntentDecision(
            plans=[LayerQueryPlan(layer="L2", conditions=L1Conditions(), is_fallback=False)],
        )
        match, summary = compute_diff(rule, llm)
        assert match is False
        assert "rule=L1" in summary
        assert "llm=L2" in summary

    def test_fallback_layers_ignored_in_diff(self):
        """Only non-fallback layers are compared."""
        rule = IntentDecision(
            plans=[
                LayerQueryPlan(layer="L1", conditions=L1Conditions(), is_fallback=False),
                LayerQueryPlan(layer="L3", conditions=L3Conditions(), is_fallback=True),
            ],
        )
        llm = IntentDecision(
            plans=[
                LayerQueryPlan(layer="L1", conditions=L1Conditions(), is_fallback=False),
                LayerQueryPlan(layer="L4", conditions=L1Conditions(), is_fallback=True),
            ],
        )
        match, summary = compute_diff(rule, llm)
        assert match is True


# -----------------------------------------------------------------------
# Combined IntentDecider
# -----------------------------------------------------------------------


@pytest.fixture
def rule_engine():
    return RuleBasedIntentDecider()


@pytest.fixture
def mock_llm_bridge():
    return AsyncMock()


@pytest.fixture
def eval_callback():
    return AsyncMock()


class TestCombinedDecider:
    @pytest.mark.asyncio
    async def test_llm_success_uses_llm_routing(self, rule_engine, mock_llm_bridge, eval_callback):
        mock_llm_bridge.chat.return_value = json.dumps({
            "layers": [
                {"layer": "L4", "is_fallback": False, "content_query": "deploy app"},
                {"layer": "L1", "is_fallback": True, "content_query": "deploy"},
            ],
            "reasoning": "procedural query",
        })
        llm_decider = LLMIntentDecider(mock_llm_bridge)
        decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=llm_decider,
            llm_enabled=True,
            shadow_eval_enabled=False,
        )

        inp = IntentDeciderInput(query="how to deploy the app")
        result = await decider.decide(inp)

        assert result.source == "llm"
        assert result.plans[0].layer == "L4"

    @pytest.mark.asyncio
    async def test_llm_failure_uses_rule_fallback(self, rule_engine, mock_llm_bridge):
        mock_llm_bridge.chat.side_effect = TimeoutError("timeout")
        llm_decider = LLMIntentDecider(mock_llm_bridge)
        decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=llm_decider,
            llm_enabled=True,
            shadow_eval_enabled=False,
        )

        inp = IntentDeciderInput(query="hello world")
        result = await decider.decide(inp)

        assert result.source == "rule_fallback"

    @pytest.mark.asyncio
    async def test_llm_disabled_uses_rules(self, rule_engine, mock_llm_bridge):
        llm_decider = LLMIntentDecider(mock_llm_bridge)
        decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=llm_decider,
            llm_enabled=False,
            shadow_eval_enabled=False,
        )

        inp = IntentDeciderInput(query="总结一下")
        result = await decider.decide(inp)

        assert result.source == "rule_fallback"
        mock_llm_bridge.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_llm_decider_uses_rules(self, rule_engine):
        decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=None,
            llm_enabled=True,
            shadow_eval_enabled=False,
        )

        inp = IntentDeciderInput(query="hello")
        result = await decider.decide(inp)

        assert result.source == "rule_fallback"

    @pytest.mark.asyncio
    async def test_time_range_from_rules_applied_to_llm_decision(
        self, rule_engine, mock_llm_bridge
    ):
        mock_llm_bridge.chat.return_value = json.dumps({
            "layers": [{"layer": "L1", "is_fallback": False, "content_query": "stuff"}],
            "reasoning": "ok",
        })
        llm_decider = LLMIntentDecider(mock_llm_bridge)
        decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=llm_decider,
            llm_enabled=True,
            shadow_eval_enabled=False,
        )

        inp = IntentDeciderInput(query="昨天做了什么")
        result = await decider.decide(inp)

        assert result.source == "llm"
        # Time range should come from rule layer
        assert result.time_range is not None
        assert result.time_range.start is not None
        for plan in result.plans:
            assert plan.time_range is not None

    @pytest.mark.asyncio
    async def test_shadow_eval_callback_called(self, rule_engine, mock_llm_bridge, eval_callback):
        mock_llm_bridge.chat.return_value = json.dumps({
            "layers": [{"layer": "L1", "is_fallback": False, "content_query": "x"}],
            "reasoning": "ok",
        })
        llm_decider = LLMIntentDecider(mock_llm_bridge)
        decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=llm_decider,
            llm_enabled=True,
            shadow_eval_enabled=True,
            eval_callback=eval_callback,
        )

        inp = IntentDeciderInput(query="hello world")
        await decider.decide(inp)

        # Give the background task a chance to complete
        import asyncio
        await asyncio.sleep(0.05)

        eval_callback.assert_called_once()
        record = eval_callback.call_args[0][0]
        assert isinstance(record, EvaluationRecord)
        assert record.query == "hello world"
        assert record.decision_source == "llm"

    @pytest.mark.asyncio
    async def test_shadow_eval_error_does_not_propagate(self, rule_engine, mock_llm_bridge):
        mock_llm_bridge.chat.return_value = json.dumps({
            "layers": [{"layer": "L1", "is_fallback": False, "content_query": "x"}],
            "reasoning": "ok",
        })
        llm_decider = LLMIntentDecider(mock_llm_bridge)
        failing_callback = AsyncMock(side_effect=RuntimeError("db error"))
        decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=llm_decider,
            llm_enabled=True,
            shadow_eval_enabled=True,
            eval_callback=failing_callback,
        )

        inp = IntentDeciderInput(query="test")
        result = await decider.decide(inp)

        # Should succeed despite callback error
        assert result is not None

        import asyncio
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_llm_invalid_json_falls_back(self, rule_engine, mock_llm_bridge):
        mock_llm_bridge.chat.return_value = "not json"
        llm_decider = LLMIntentDecider(mock_llm_bridge)
        decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=llm_decider,
            llm_enabled=True,
            shadow_eval_enabled=False,
        )

        inp = IntentDeciderInput(query="test")
        result = await decider.decide(inp)

        assert result.source == "rule_fallback"
