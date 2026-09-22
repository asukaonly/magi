"""Tests for RuleBasedIntentDecider."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from magi.memory.hybrid_retrieval.intent_decider import RuleBasedIntentDecider
from magi.memory.hybrid_retrieval.models import (
    IntentDeciderInput,
    L1Conditions,
    L2Conditions,
)


@pytest.fixture
def decider():
    return RuleBasedIntentDecider()


# Natural language requires typed semantic intent, including formerly recognized
# phrases. The host never turns matching words into a hard date restriction.
@pytest.mark.parametrize(
    "query",
    [
        "昨天我做了什么",
        "What did I do yesterday",
        "今天有什么事",
        "这周发生了什么",
        "What happened last week",
        "上个月的总结",
        "最近有什么事",
        "看看我最近1小时在玩什么",
        "最近30分钟我做了什么",
        "最近3天的活动总结",
        "最近2周做了哪些项目",
        "what did I do in the past 2 hours",
        "summarize the last 5 days",
        "前天聊了什么",
        "3天前我做了什么",
        "What did I do 5 days ago",
        "2小时前发生了什么",
        "2 weeks ago something happened",
        "2个月前的事",
        "24年前我去过哪里",
        "What was the event that I participated in a week ago?",
        "上周三做了什么",
        "What happened last Friday",
        "我24年去东京拍了什么照片",
        "我2024年去东京拍了什么照片",
        "2022年9月我在哪里拍了照片",
        "24年12月在东京拍了什么",
        "2024年12月28日我拍了什么",
        "3月10号发生了什么",
        "what happened on March 5th",
        "12月25日有什么活动",
        "what happened two days ago",
        "Give me a summary of last month",
        "what photos did I take in 2024",
        "what photos did I take in 24",
        "photos from Dec 2024",
        "what happened 24 years ago",
        "tell me about Python programming",
        "3 hours ago there was a meeting",
        "3 weeks ago we discussed the project",
    ],
)
def test_query_prose_without_semantic_judgment_has_no_time_filter(decider, query):
    result = decider.evaluate(IntentDeciderInput(query=query))
    assert result.time_range is None
    assert all(plan.time_range is None for plan in result.plans)


# -----------------------------------------------------------------------
# Time parsing: raw_time_range
# -----------------------------------------------------------------------


class TestRawTimeRange:
    def test_as_of_accepts_point_in_time(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(
            query="where did I live then",
            raw_time_range={"as_of": "2026-05-10T12:34:56+08:00"},
        )

        result = decider.evaluate(inp)

        assert result.time_range is not None
        assert (
            result.time_range.as_of
            == datetime.fromisoformat("2026-05-10T12:34:56+08:00").timestamp()
        )
        assert result.time_range.start is None
        assert result.time_range.end is None

    def test_absolute_start_end(self, decider: RuleBasedIntentDecider):
        now = time.time()
        raw = {"start": now - 3600, "end": now}
        inp = IntentDeciderInput(query="something", raw_time_range=raw)
        result = decider.evaluate(inp)
        assert result.time_range is not None
        assert result.time_range.start == now - 3600
        assert result.time_range.end == now

    def test_absolute_start_end_accepts_iso8601(self, decider: RuleBasedIntentDecider):
        start = "2026-05-10T00:00:00+08:00"
        end = "2026-05-10T23:59:59+08:00"
        inp = IntentDeciderInput(query="something", raw_time_range={"start": start, "end": end})

        result = decider.evaluate(inp)

        assert result.time_range is not None
        assert result.time_range.start == datetime.fromisoformat(start).timestamp()
        assert result.time_range.end == datetime.fromisoformat(end).timestamp()

    def test_absolute_start_end_accepts_common_date_strings(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(
            query="something",
            raw_time_range={
                "start": "2026/05/10",
                "end": "2026-05-10 12:34:56",
            },
        )

        result = decider.evaluate(inp)

        assert result.time_range is not None
        assert result.time_range.start == datetime(2026, 5, 10, tzinfo=timezone.utc).timestamp()
        assert (
            result.time_range.end
            == datetime(2026, 5, 10, 12, 34, 56, tzinfo=timezone.utc).timestamp()
        )

    def test_end_date_only_expands_to_end_of_day(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(
            query="something",
            raw_time_range={
                "start": "2026-05-10",
                "end": "2026-05-10",
            },
        )

        result = decider.evaluate(inp)

        assert result.time_range is not None
        assert (
            result.time_range.start
            == datetime(2026, 5, 10, 0, 0, 0, tzinfo=timezone.utc).timestamp()
        )
        assert (
            result.time_range.end
            == datetime(2026, 5, 10, 23, 59, 59, 999999, tzinfo=timezone.utc).timestamp()
        )

    def test_relative_7d(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="recent", raw_time_range={"relative": "7d"})
        result = decider.evaluate(inp)
        assert result.time_range is not None
        now = time.time()
        assert abs(result.time_range.end - now) < 5
        assert abs(result.time_range.start - (now - 7 * 86400)) < 5

    def test_relative_24h(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="recent", raw_time_range={"relative": "24h"})
        result = decider.evaluate(inp)
        assert result.time_range is not None
        now = time.time()
        assert abs(result.time_range.start - (now - 86400)) < 5

    def test_raw_overrides_query_keywords(self, decider: RuleBasedIntentDecider):
        """raw_time_range should override query text parsing."""
        raw = {"start": 1000, "end": 2000}
        inp = IntentDeciderInput(query="昨天发生了什么", raw_time_range=raw)
        result = decider.evaluate(inp)
        assert result.time_range.start == 1000
        assert result.time_range.end == 2000

    def test_start_only_raw_time_range(self, decider: RuleBasedIntentDecider):
        """Partial raw_time_range with start-only should not set end."""
        raw = {"start": 0}
        inp = IntentDeciderInput(query="something", raw_time_range=raw)
        result = decider.evaluate(inp)
        assert result.time_range is not None
        assert result.time_range.start == 0
        assert result.time_range.end is None

    def test_no_time_range(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="tell me about Python")
        result = decider.evaluate(inp)
        assert result.time_range is None


# -----------------------------------------------------------------------
# Layer routing: query_mode_hint
# -----------------------------------------------------------------------


class TestLayerRouting:
    def test_mode_exact_fact(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="what happened", query_mode_hint="exact_fact")
        result = decider.evaluate(inp)
        layers = [p.layer for p in result.plans]
        assert layers[0] == "L2"
        assert layers[1] == "L1"
        assert not result.plans[0].is_fallback
        assert result.plans[1].is_fallback

    def test_mode_summary(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="what happened", query_mode_hint="summary")
        result = decider.evaluate(inp)
        assert result.plans[0].layer == "L3"
        assert not result.plans[0].is_fallback

    def test_mode_strategy(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="experience", query_mode_hint="strategy")
        result = decider.evaluate(inp)
        assert result.plans[0].layer == "L4"

    def test_mode_current_state(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="who", query_mode_hint="current_state")
        result = decider.evaluate(inp)
        assert result.plans[0].layer == "L2"

    def test_mode_event_stream_queries_l1_only(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="what happened", query_mode_hint="event_stream")
        result = decider.evaluate(inp)

        assert [plan.layer for plan in result.plans] == ["L1"]
        assert result.plans[0].is_fallback is False

    def test_query_mode_exact_fact_prefers_l2_with_l1_fallback(
        self, decider: RuleBasedIntentDecider
    ):
        inp = IntentDeciderInput(query="我喜欢什么天气", query_mode_hint="exact_fact")
        result = decider.evaluate(inp)

        assert [plan.layer for plan in result.plans[:2]] == ["L2", "L1"]
        assert result.plans[0].is_fallback is False
        assert result.plans[1].is_fallback is True
        assert isinstance(result.plans[0].conditions, L2Conditions)
        assert result.plans[0].conditions.include_episodes is False

    def test_query_mode_current_state_prefers_l2_with_l1_fallback(
        self, decider: RuleBasedIntentDecider
    ):
        inp = IntentDeciderInput(query="我的默认工作目录是什么", query_mode_hint="current_state")
        result = decider.evaluate(inp)

        assert [plan.layer for plan in result.plans[:2]] == ["L2", "L1"]

    def test_query_mode_episode_recall_prefers_l1_with_l2_fallback(
        self, decider: RuleBasedIntentDecider
    ):
        inp = IntentDeciderInput(query="你记得我们之前约定了什么", query_mode_hint="episode_recall")
        result = decider.evaluate(inp)

        assert [plan.layer for plan in result.plans[:2]] == ["L2", "L1"]

    def test_query_mode_episode_recall_checks_experiences_without_episode_substrate(
        self, decider: RuleBasedIntentDecider
    ):
        inp = IntentDeciderInput(query="那次日本旅行发生了什么", query_mode_hint="episode_recall")
        result = decider.evaluate(inp)

        l2_plan = next(plan for plan in result.plans if plan.layer == "L2")
        assert isinstance(l2_plan.conditions, L2Conditions)
        assert l2_plan.conditions.include_episodes is False
        assert l2_plan.conditions.include_experiences is True

    def test_query_mode_experience_recall_prefers_experience_layer(
        self, decider: RuleBasedIntentDecider
    ):
        inp = IntentDeciderInput(query="回忆一下日本旅行", query_mode_hint="experience_recall")
        result = decider.evaluate(inp)

        assert [plan.layer for plan in result.plans[:2]] == ["L2", "L1"]
        assert result.plans[0].is_fallback is False
        assert isinstance(result.plans[0].conditions, L2Conditions)
        assert result.plans[0].conditions.include_episodes is False
        assert result.plans[0].conditions.include_experiences is True

    def test_query_mode_strategy_prefers_l4_with_l1_fallback(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="按之前那套流程修一下这个 bug", query_mode_hint="strategy")
        result = decider.evaluate(inp)

        assert [plan.layer for plan in result.plans[:2]] == ["L4", "L1"]


# -----------------------------------------------------------------------
# Layer routing: keyword signals
# -----------------------------------------------------------------------


class TestDefaultRouting:
    """Without explicit hints, rule engine defaults to L1 primary + L2 fallback."""

    def test_default_l1_l2(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="tell me about cats")
        result = decider.evaluate(inp)
        assert result.plans[0].layer == "L2"
        assert result.plans[1].layer == "L1"
        assert not result.plans[0].is_fallback
        assert result.plans[1].is_fallback

    def test_relationship_query_defaults_to_l2(self, decider: RuleBasedIntentDecider):
        """Without query_mode_hint, relationship keywords no longer route to L2."""
        inp = IntentDeciderInput(query="我和小明的关系是什么")
        result = decider.evaluate(inp)
        assert result.plans[0].layer == "L2"
        assert result.plans[1].layer == "L1"

    def test_preference_query_defaults_to_l2(self, decider: RuleBasedIntentDecider):
        """Without query_mode_hint, preference queries default to exact_fact (L2 primary)."""
        inp = IntentDeciderInput(query="我讨厌什么天气")
        result = decider.evaluate(inp)
        assert result.plans[0].layer == "L2"

    def test_summary_words_do_not_change_fallback(self, decider: RuleBasedIntentDecider):
        """Unknown intent uses the neutral default, regardless of wording."""
        inp = IntentDeciderInput(query="帮我总结一下上周")
        result = decider.evaluate(inp)
        assert result.plans[0].layer == "L2"

    def test_browsing_defaults_to_l2(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="我看了什么网页")
        result = decider.evaluate(inp)
        assert result.plans[0].layer == "L2"


class TestSemanticFrameEnrichment:
    @pytest.mark.parametrize(
        "query", ["我喜欢哪些up主", "我在杭州喜欢去哪些咖啡馆", "我喜欢B站吗", "Alice prefers jazz"]
    )
    def test_rules_do_not_invent_semantic_frame(self, decider, query):
        decision = decider.evaluate(IntentDeciderInput(query=query, query_mode_hint="exact_fact"))
        conditions = decision.plans[0].conditions
        assert isinstance(conditions, L2Conditions)
        assert conditions.semantic_frame is None
        assert conditions.subject_hint is None
        assert conditions.predicate_family is None


# -----------------------------------------------------------------------
# Source/domain inference
# -----------------------------------------------------------------------


class TestSourceDomainInference:
    def test_caller_filters_preserved(self, decider: RuleBasedIntentDecider):
        """Caller-provided filters should take precedence over inference."""
        inp = IntentDeciderInput(
            query="浏览了什么",
            source_filters=["custom_source"],
            domain_filters=["custom_domain"],
        )
        result = decider.evaluate(inp)
        l1_plans = [p for p in result.plans if isinstance(p.conditions, L1Conditions)]
        assert len(l1_plans) >= 1
        assert l1_plans[0].conditions.source_filters == ["custom_source"]
        assert l1_plans[0].conditions.domain_filters == ["custom_domain"]

    def test_no_keyword_source_inference(self, decider: RuleBasedIntentDecider):
        """Without caller-provided filters, rule engine returns no source filters."""
        inp = IntentDeciderInput(query="我浏览了哪些网站")
        result = decider.evaluate(inp)
        l1_plans = [p for p in result.plans if isinstance(p.conditions, L1Conditions)]
        assert len(l1_plans) >= 1
        assert l1_plans[0].conditions.source_filters is None


# -----------------------------------------------------------------------
# Decision metadata
# -----------------------------------------------------------------------


class TestDecisionMetadata:
    def test_source_is_rule_fallback(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="hello")
        result = decider.evaluate(inp)
        assert result.source == "rule_fallback"

    def test_reasoning_not_empty(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="hello")
        result = decider.evaluate(inp)
        assert result.reasoning is not None
        assert len(result.reasoning) > 0

    def test_time_range_propagated_to_plans(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(
            query="昨天做了什么", raw_time_range={"start": 100.0, "end": 200.0}
        )
        result = decider.evaluate(inp)
        assert result.time_range is not None
        for plan in result.plans:
            assert plan.time_range is not None
            assert plan.time_range.start == result.time_range.start
