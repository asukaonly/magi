"""Tests for RuleBasedIntentDecider."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from magi.memory.hybrid_retrieval.intent_decider import RuleBasedIntentDecider
from magi.memory.hybrid_retrieval.models import (
    IntentDeciderInput,
    L1Conditions,
    L2Conditions,
    L3Conditions,
    L4Conditions,
    TimeRange,
)


@pytest.fixture
def decider():
    return RuleBasedIntentDecider()


# -----------------------------------------------------------------------
# Time parsing: static keywords
# -----------------------------------------------------------------------


class TestTimeParsingStatic:
    def test_yesterday_zh(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="昨天我做了什么")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        now = datetime.now(tz=timezone.utc)
        yesterday = now - timedelta(days=1)
        expected_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        assert abs(result.time_range.start - expected_start) < 2

    def test_yesterday_en(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="What did I do yesterday")
        result = decider.evaluate(inp)
        assert result.time_range is not None

    def test_today_zh(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="今天有什么事")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        now = datetime.now(tz=timezone.utc)
        expected_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        assert abs(result.time_range.start - expected_start) < 2
        # end should cover at least up to now (dateparser returns day range)
        assert result.time_range.end >= now.timestamp() - 5

    def test_this_week_zh(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="这周发生了什么")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        now = datetime.now(tz=timezone.utc)
        monday = now - timedelta(days=now.weekday())
        expected_start = monday.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        assert abs(result.time_range.start - expected_start) < 2

    def test_last_week_en(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="What happened last week")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        now = datetime.now(tz=timezone.utc)
        last_monday = now - timedelta(days=now.weekday() + 7)
        expected_start = last_monday.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        assert abs(result.time_range.start - expected_start) < 2

    def test_last_month_zh(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="上个月的总结")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        assert result.time_range.start < result.time_range.end

    def test_recently_zh(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="最近有什么事")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        now = time.time()
        seven_days_ago = now - 7 * 86400
        assert abs(result.time_range.start - seven_days_ago) < 5

    def test_day_before_yesterday(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="前天聊了什么")
        result = decider.evaluate(inp)
        assert result.time_range is not None


# -----------------------------------------------------------------------
# Time parsing: relative N-ago patterns
# -----------------------------------------------------------------------


class TestTimeParsingRelative:
    def test_n_days_ago_zh(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="3天前我做了什么")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        now = datetime.now(tz=timezone.utc)
        target = now - timedelta(days=3)
        expected = target.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        assert abs(result.time_range.start - expected) < 2

    def test_n_days_ago_en(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="What did I do 5 days ago")
        result = decider.evaluate(inp)
        assert result.time_range is not None

    def test_n_hours_ago(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="2小时前发生了什么")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        now = time.time()
        assert abs(result.time_range.end - now) < 5
        assert abs(result.time_range.start - (now - 7200)) < 5

    def test_n_weeks_ago(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="2 weeks ago something happened")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        # Should produce an entire week range
        diff = result.time_range.end - result.time_range.start
        assert diff >= 6 * 86400  # at least 6 days span

    def test_n_months_ago_zh(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="2个月前的事")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        # Should be an entire month range
        diff = result.time_range.end - result.time_range.start
        assert diff >= 27 * 86400  # at least 27 days


# -----------------------------------------------------------------------
# Time parsing: weekday patterns
# -----------------------------------------------------------------------


class TestTimeParsingWeekday:
    def test_last_wednesday_zh(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="上周三做了什么")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        # Should be a single-day range
        diff = result.time_range.end - result.time_range.start
        assert diff < 86401  # not more than 1 day

    def test_last_friday_en(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="What happened last Friday")
        result = decider.evaluate(inp)
        assert result.time_range is not None


# -----------------------------------------------------------------------
# Time parsing: specific dates
# -----------------------------------------------------------------------


class TestTimeParsingSpecificDate:
    def test_chinese_date(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="3月10号发生了什么")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        now = datetime.now(tz=timezone.utc)
        expected = datetime(now.year, 3, 10, tzinfo=timezone.utc)
        expected_start = expected.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        assert abs(result.time_range.start - expected_start) < 2

    def test_english_date(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="what happened on March 5th")
        result = decider.evaluate(inp)
        assert result.time_range is not None

    def test_chinese_date_ri(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="12月25日有什么活动")
        result = decider.evaluate(inp)
        assert result.time_range is not None


# -----------------------------------------------------------------------
# Time parsing: dateparser-based English patterns
# -----------------------------------------------------------------------


class TestDateparserEnglish:
    """Tests that exercise the dateparser.search_dates path (English)."""

    def test_two_days_ago_en(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="what happened two days ago")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        now = datetime.now(tz=timezone.utc)
        target = now - timedelta(days=2)
        expected = target.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        assert abs(result.time_range.start - expected) < 2

    def test_last_month_en(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="Give me a summary of last month")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        diff = result.time_range.end - result.time_range.start
        assert diff >= 27 * 86400

    def test_no_temporal_expression(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="tell me about Python programming")
        result = decider.evaluate(inp)
        assert result.time_range is None


# -----------------------------------------------------------------------
# Time parsing: range width heuristics
# -----------------------------------------------------------------------


class TestRangeWidthHeuristics:
    """Verify _range_from_match correctly widens to hour/week/month."""

    def test_hours_ago_gives_hour_range(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="3 hours ago there was a meeting")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        diff = result.time_range.end - result.time_range.start
        # Hour range should be around 3 hours, not a full day
        assert diff < 86400

    def test_weeks_ago_gives_week_range(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="3 weeks ago we discussed the project")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        diff = result.time_range.end - result.time_range.start
        assert diff >= 6 * 86400


# -----------------------------------------------------------------------
# Time parsing: raw_time_range
# -----------------------------------------------------------------------


class TestRawTimeRange:
    def test_absolute_start_end(self, decider: RuleBasedIntentDecider):
        now = time.time()
        raw = {"start": now - 3600, "end": now}
        inp = IntentDeciderInput(query="something", raw_time_range=raw)
        result = decider.evaluate(inp)
        assert result.time_range is not None
        assert result.time_range.start == now - 3600
        assert result.time_range.end == now

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
        now = time.time()
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
    def test_mode_detail(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="what happened", query_mode_hint="detail")
        result = decider.evaluate(inp)
        layers = [p.layer for p in result.plans]
        assert layers[0] == "L1"
        assert layers[1] == "L3"
        assert not result.plans[0].is_fallback
        assert result.plans[1].is_fallback

    def test_mode_summary(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="what happened", query_mode_hint="summary")
        result = decider.evaluate(inp)
        assert result.plans[0].layer == "L3"
        assert not result.plans[0].is_fallback

    def test_mode_experience(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="experience", query_mode_hint="experience")
        result = decider.evaluate(inp)
        assert result.plans[0].layer == "L4"

    def test_mode_graph(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="who", query_mode_hint="graph")
        result = decider.evaluate(inp)
        assert result.plans[0].layer == "L2"

    def test_recall_intent_preference_prefers_l2_with_l1_fallback(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="我喜欢什么天气", recall_intent_hint="preference_recall")
        result = decider.evaluate(inp)

        assert [plan.layer for plan in result.plans[:2]] == ["L2", "L1"]
        assert result.plans[0].is_fallback is False
        assert result.plans[1].is_fallback is True

    def test_recall_intent_profile_fact_prefers_l2_with_l1_fallback(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="我的默认工作目录是什么", recall_intent_hint="profile_fact_recall")
        result = decider.evaluate(inp)

        assert [plan.layer for plan in result.plans[:2]] == ["L2", "L1"]

    def test_recall_intent_relationship_prefers_l2_with_l1_fallback(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="你记得我们之前约定了什么", recall_intent_hint="relationship_recall")
        result = decider.evaluate(inp)

        assert [plan.layer for plan in result.plans[:2]] == ["L2", "L1"]

    def test_recall_intent_workflow_prefers_l4_with_l1_fallback(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="按之前那套流程修一下这个 bug", recall_intent_hint="workflow_reuse")
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
        assert result.plans[0].layer == "L1"
        assert result.plans[1].layer == "L2"
        assert not result.plans[0].is_fallback
        assert result.plans[1].is_fallback

    def test_relationship_query_defaults_to_l1(self, decider: RuleBasedIntentDecider):
        """Without recall_intent_hint, relationship keywords no longer route to L2."""
        inp = IntentDeciderInput(query="我和小明的关系是什么")
        result = decider.evaluate(inp)
        assert result.plans[0].layer == "L1"
        assert result.plans[1].layer == "L2"

    def test_preference_query_defaults_to_l1(self, decider: RuleBasedIntentDecider):
        """Without recall_intent_hint, preference keywords no longer route to L2."""
        inp = IntentDeciderInput(query="我讨厌什么天气")
        result = decider.evaluate(inp)
        assert result.plans[0].layer == "L1"

    def test_summary_query_defaults_to_l1(self, decider: RuleBasedIntentDecider):
        """Without query_mode_hint, summary keywords no longer route to L3."""
        inp = IntentDeciderInput(query="帮我总结一下上周")
        result = decider.evaluate(inp)
        assert result.plans[0].layer == "L1"

    def test_browsing_l1(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="我看了什么网页")
        result = decider.evaluate(inp)
        assert result.plans[0].layer == "L1"


class TestSemanticFrameEnrichment:
    """Semantic frame enrichment via enrich_l2_conditions (recall_intent_hint routes to L2)."""

    def test_l2_creator_affinity_semantic_frame(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="我喜欢哪些up主", recall_intent_hint="preference_recall")
        result = decider.evaluate(inp)

        assert result.plans[0].layer == "L2"
        conditions = result.plans[0].conditions
        assert isinstance(conditions, L2Conditions)
        assert conditions.semantic_frame is not None
        assert conditions.semantic_frame.query_family == "affinity"
        assert conditions.semantic_frame.subject_scope == "self"
        assert conditions.semantic_frame.answer_kind == "unknown"
        assert conditions.semantic_frame.answer_unit == "mixed"

    def test_l2_place_affinity_semantic_frame_with_location(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="我在杭州喜欢去哪些咖啡馆", recall_intent_hint="preference_recall")
        result = decider.evaluate(inp)

        assert result.plans[0].layer == "L2"
        conditions = result.plans[0].conditions
        assert isinstance(conditions, L2Conditions)
        assert conditions.semantic_frame is not None
        assert conditions.semantic_frame.query_family == "affinity"
        assert conditions.semantic_frame.subject_scope == "self"
        assert conditions.semantic_frame.answer_kind == "unknown"
        assert conditions.semantic_frame.answer_unit == "mixed"

    def test_l2_place_affinity_semantic_frame_no_rule_constraints(
        self,
        decider: RuleBasedIntentDecider,
    ):
        inp = IntentDeciderInput(query="我在杭州的时候喜欢去哪些咖啡馆", recall_intent_hint="preference_recall")
        result = decider.evaluate(inp)

        conditions = result.plans[0].conditions
        assert isinstance(conditions, L2Conditions)
        assert conditions.semantic_frame is not None
        assert conditions.semantic_frame.constraints == []

    def test_l2_topic_affinity_semantic_frame_for_topic_query(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="我喜欢什么题材", recall_intent_hint="preference_recall")
        result = decider.evaluate(inp)

        assert result.plans[0].layer == "L2"
        conditions = result.plans[0].conditions
        assert isinstance(conditions, L2Conditions)
        assert conditions.semantic_frame is not None
        assert conditions.semantic_frame.query_family == "affinity"
        assert conditions.semantic_frame.subject_scope == "self"
        assert conditions.semantic_frame.answer_kind == "unknown"
        assert conditions.semantic_frame.answer_unit == "mixed"

    def test_l2_topic_affinity_semantic_frame_for_creator_topic_question(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="上次我看的主播他说的主题是什么", recall_intent_hint="preference_recall")
        result = decider.evaluate(inp)

        assert result.plans[0].layer == "L2"
        conditions = result.plans[0].conditions
        assert isinstance(conditions, L2Conditions)
        assert conditions.semantic_frame is not None
        assert conditions.semantic_frame.answer_kind == "unknown"

    def test_l2_affinity_boolean_query(self, decider: RuleBasedIntentDecider):
        inp = IntentDeciderInput(query="我喜欢B站吗", recall_intent_hint="preference_recall")
        result = decider.evaluate(inp)

        assert result.plans[0].layer == "L2"
        conditions = result.plans[0].conditions
        assert isinstance(conditions, L2Conditions)
        assert conditions.semantic_frame is not None
        assert conditions.semantic_frame.query_family == "affinity"
        assert conditions.semantic_frame.subject_scope == "self"


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
        l1_plan = result.plans[0]
        assert isinstance(l1_plan.conditions, L1Conditions)
        assert l1_plan.conditions.source_filters == ["custom_source"]
        assert l1_plan.conditions.domain_filters == ["custom_domain"]

    def test_no_keyword_source_inference(self, decider: RuleBasedIntentDecider):
        """Without caller-provided filters, rule engine returns no source filters."""
        inp = IntentDeciderInput(query="我浏览了哪些网站")
        result = decider.evaluate(inp)
        l1_plan = result.plans[0]
        assert isinstance(l1_plan.conditions, L1Conditions)
        assert l1_plan.conditions.source_filters is None


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
        inp = IntentDeciderInput(query="昨天做了什么")
        result = decider.evaluate(inp)
        assert result.time_range is not None
        for plan in result.plans:
            assert plan.time_range is not None
            assert plan.time_range.start == result.time_range.start
