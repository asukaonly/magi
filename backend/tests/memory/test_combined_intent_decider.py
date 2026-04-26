"""Tests for combined IntentDecider (rule-canonical routing + LLM refinement)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval.intent_decider import (
    EvaluationRecord,
    IntentDecider,
    LLMIntentDecider,
    LLMRefinement,
    RuleBasedIntentDecider,
    compute_diff,
)
from magi.memory.hybrid_retrieval.models import (
    IntentDecision,
    IntentDeciderInput,
    L1Conditions,
    L2Conditions,
    LayerQueryPlan,
)


# -----------------------------------------------------------------------
# compute_diff
# -----------------------------------------------------------------------


class TestComputeDiff:
    def test_llm_none_returns_failed(self):
        rule = IntentDecision(
            plans=[LayerQueryPlan(layer="L1", conditions=L1Conditions())],
        )
        applied, summary = compute_diff(rule, None)
        assert applied is False
        assert summary == "llm_failed"

    def test_refinement_with_changed_content_query(self):
        rule = IntentDecision(
            plans=[LayerQueryPlan(layer="L1", conditions=L1Conditions(content_query="orig"))],
        )
        refinement = LLMRefinement(content_query="refined", reasoning="r")
        applied, summary = compute_diff(rule, refinement)
        assert applied is True
        assert "content_query" in summary

    def test_refinement_with_l2_fields(self):
        rule = IntentDecision(
            plans=[LayerQueryPlan(layer="L2", conditions=L2Conditions(content_query="x"))],
        )
        refinement = LLMRefinement(
            content_query="x",  # same as rule → not flagged
            entities=["Alice"],
            subject_hint="explicit",
            predicate_family="relationship",
        )
        applied, summary = compute_diff(rule, refinement)
        assert applied is True
        assert "entities" in summary
        assert "subject_hint" in summary
        assert "predicate_family" in summary

    def test_empty_refinement(self):
        rule = IntentDecision(
            plans=[LayerQueryPlan(layer="L1", conditions=L1Conditions(content_query="x"))],
        )
        refinement = LLMRefinement(content_query="x")  # same content → no fields changed
        applied, summary = compute_diff(rule, refinement)
        assert applied is True
        assert summary == "applied: empty"


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
    async def test_llm_success_overlays_refinement_onto_rule_plans(
        self, rule_engine, mock_llm_bridge
    ):
        mock_llm_bridge.chat.return_value = json.dumps({
            "content_query": "deploy app",
            "reasoning": "procedural query",
        })
        llm_decider = LLMIntentDecider(mock_llm_bridge)
        decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=llm_decider,
            llm_enabled=True,
            shadow_eval_enabled=False,
        )

        inp = IntentDeciderInput(query="how to deploy the app", query_mode_hint="strategy")
        result = await decider.decide(inp)

        assert result.source == "llm"
        # Routing comes from the rule engine (strategy → L4 primary).
        primary_layers = {p.layer for p in result.plans if not p.is_fallback}
        assert "L4" in primary_layers
        # Refinement applies content_query.
        l4_plan = next(p for p in result.plans if p.layer == "L4")
        assert l4_plan.conditions.content_query == "deploy app"

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
    async def test_llm_failure_keeps_rule_query_mode_routing(self, rule_engine, mock_llm_bridge):
        mock_llm_bridge.chat.side_effect = TimeoutError("timeout")
        llm_decider = LLMIntentDecider(mock_llm_bridge)
        decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=llm_decider,
            llm_enabled=True,
            shadow_eval_enabled=False,
        )

        inp = IntentDeciderInput(query="我喜欢什么天气", query_mode_hint="exact_fact")
        result = await decider.decide(inp)

        assert result.source == "rule_fallback"
        primary = {p.layer for p in result.plans if not p.is_fallback}
        assert "L2" in primary

    @pytest.mark.asyncio
    async def test_llm_disabled_uses_rules(self, rule_engine, mock_llm_bridge):
        llm_decider = LLMIntentDecider(mock_llm_bridge)
        decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=llm_decider,
            llm_enabled=False,
            shadow_eval_enabled=False,
        )

        inp = IntentDeciderInput(query="总结一下", query_mode_hint="summary")
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
    async def test_time_range_owned_by_rule_engine(self, rule_engine, mock_llm_bridge):
        mock_llm_bridge.chat.return_value = json.dumps({
            "content_query": "stuff",
            "reasoning": "ok",
        })
        llm_decider = LLMIntentDecider(mock_llm_bridge)
        decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=llm_decider,
            llm_enabled=True,
            shadow_eval_enabled=False,
        )

        inp = IntentDeciderInput(query="昨天做了什么", query_mode_hint="episode_recall")
        result = await decider.decide(inp)

        assert result.source == "llm"
        # Time range still comes from the rule engine.
        assert result.time_range is not None
        assert result.time_range.start is not None
        for plan in result.plans:
            assert plan.time_range is not None

    @pytest.mark.asyncio
    async def test_shadow_eval_callback_called_with_refinement(
        self, rule_engine, mock_llm_bridge, eval_callback
    ):
        mock_llm_bridge.chat.return_value = json.dumps({
            "content_query": "x",
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

        import asyncio
        await asyncio.sleep(0.05)

        eval_callback.assert_called_once()
        record = eval_callback.call_args[0][0]
        assert isinstance(record, EvaluationRecord)
        assert record.query == "hello world"
        assert record.decision_source == "llm"
        assert record.llm_refinement is not None
        assert record.refinement_applied is True

    @pytest.mark.asyncio
    async def test_shadow_eval_error_does_not_propagate(self, rule_engine, mock_llm_bridge):
        mock_llm_bridge.chat.return_value = json.dumps({
            "content_query": "x",
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
