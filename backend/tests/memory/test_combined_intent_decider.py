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
    TimeRange,
)


# -----------------------------------------------------------------------
# compute_diff
# -----------------------------------------------------------------------


class TestComputeDiff:

    @pytest.mark.parametrize(
        "refinement,expected",
        [
            (None, (False, "llm_failed")),
            (LLMRefinement(content_query="orig"), (True, "applied: empty")),
            (LLMRefinement(content_query=""), (True, "applied: empty")),
            (LLMRefinement(content_query="refined"), (True, "applied: content_query")),
        ],
    )
    def test_content_refinement_diagnostics_distinguish_failure_noop_and_change(
        self, refinement, expected
    ):
        rule = IntentDecision(
            plans=[LayerQueryPlan(layer="L1", conditions=L1Conditions(content_query="orig"))]
        )
        assert compute_diff(rule, refinement) == expected

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
    @pytest.mark.parametrize("failure", ["missing", "disabled", "timeout", "invalid_json"])
    @pytest.mark.parametrize("mode", ["exact_fact", "summary"])
    async def test_unavailable_refinement_preserves_the_complete_rule_decision(
        self, rule_engine, mock_llm_bridge, failure, mode
    ):
        if failure == "timeout":
            mock_llm_bridge.chat.side_effect = TimeoutError("timeout")
        else:
            mock_llm_bridge.chat.return_value = "not json"
        decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=None if failure == "missing" else LLMIntentDecider(mock_llm_bridge),
            llm_enabled=failure != "disabled",
            shadow_eval_enabled=False,
        )
        inp = IntentDeciderInput(
            query="我喜欢什么天气",
            query_mode_hint=mode,
            raw_time_range={"start": 100.0, "end": 200.0},
            source_filters=["journal"],
        )
        expected = rule_engine.evaluate(inp)
        assert await decider.decide(inp) == expected
        assert expected.source == "rule_fallback"
        if failure in {"missing", "disabled"}:
            mock_llm_bridge.chat.assert_not_awaited()
        else:
            mock_llm_bridge.chat.assert_awaited_once()


    @pytest.mark.asyncio
    async def test_time_range_owned_by_rule_engine(self, rule_engine, mock_llm_bridge):
        mock_llm_bridge.chat.return_value = json.dumps(
            {
                "content_query": "stuff",
                "reasoning": "ok",
            }
        )
        llm_decider = LLMIntentDecider(mock_llm_bridge)
        decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=llm_decider,
            llm_enabled=True,
            shadow_eval_enabled=False,
        )

        inp = IntentDeciderInput(
            query="昨天做了什么",
            query_mode_hint="episode_recall",
            raw_time_range={"start": 100.0, "end": 200.0},
        )
        result = await decider.decide(inp)

        assert result.source == "llm"
        assert result.time_range == TimeRange(start=100.0, end=200.0)
        assert result.plans
        assert all(plan.time_range == TimeRange(start=100.0, end=200.0) for plan in result.plans)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("callback_fails", [False, True])
    async def test_shadow_evaluation_is_awaited_without_changing_the_decision(
        self, rule_engine, mock_llm_bridge, callback_fails
    ):
        import asyncio

        mock_llm_bridge.chat.return_value = json.dumps({"content_query": "x", "reasoning": "ok"})
        callback = AsyncMock(side_effect=RuntimeError("db error") if callback_fails else None)
        decider = IntentDecider(
            rule_engine=rule_engine,
            llm_decider=LLMIntentDecider(mock_llm_bridge),
            llm_enabled=True,
            shadow_eval_enabled=True,
            eval_callback=callback,
        )
        result = await decider.decide(IntentDeciderInput(query="hello world"))
        tasks = tuple(decider._background_tasks)
        assert len(tasks) == 1
        assert await asyncio.wait_for(asyncio.gather(*tasks), timeout=1) == [None]
        callback.assert_awaited_once()
        record = callback.await_args.args[0]
        assert isinstance(record, EvaluationRecord)
        assert record.query == "hello world"
        assert record.decision_source == result.source == "llm"
        assert record.final_decision is result
        assert record.llm_refinement.content_query == "x"
        assert record.refinement_applied is True
        assert [plan.conditions.content_query for plan in result.plans] == ["x", "x"]
