"""Tests for hybrid retrieval data contracts."""

from __future__ import annotations

from dataclasses import asdict

from magi.memory.hybrid_retrieval.models import (
    IntentDeciderInput,
    IntentDecision,
    L1Conditions,
    L2Conditions,
    L3Conditions,
    L4Conditions,
    LayerQueryPlan,
    RetrievalConfig,
    RetrievalPayload,
    RetrievalQuery,
    TimeRange,
)


class TestTimeRange:
    def test_defaults_to_none(self):
        tr = TimeRange()
        assert tr.start is None
        assert tr.end is None

    def test_with_values(self):
        tr = TimeRange(start=1000.0, end=2000.0)
        assert tr.start == 1000.0
        assert tr.end == 2000.0

    def test_serialization(self):
        tr = TimeRange(start=100.0, end=200.0)
        d = asdict(tr)
        assert d == {"start": 100.0, "end": 200.0}


class TestLayerConditions:
    def test_l1_defaults(self):
        c = L1Conditions(content_query="hello")
        assert c.event_types is None
        assert c.limit == 10

    def test_l2_defaults(self):
        c = L2Conditions()
        assert c.include_tom_snapshot is True
        assert c.include_relationships is True

    def test_l3_defaults(self):
        c = L3Conditions(content_query="summary")
        assert c.summary_types is None
        assert c.summary_categories is None
        assert c.limit == 5

    def test_l4_defaults(self):
        c = L4Conditions(content_query="skill")
        assert c.skill_categories is None
        assert c.limit == 5


class TestLayerQueryPlan:
    def test_primary_plan(self):
        plan = LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(content_query="test"),
            is_fallback=False,
        )
        assert plan.layer == "L1"
        assert plan.is_fallback is False
        assert plan.time_range is None

    def test_fallback_plan_with_time(self):
        plan = LayerQueryPlan(
            layer="L3",
            conditions=L3Conditions(content_query="summary"),
            time_range=TimeRange(start=100.0),
            is_fallback=True,
        )
        assert plan.is_fallback is True
        assert plan.time_range.start == 100.0


class TestIntentDecision:
    def test_empty_decision(self):
        d = IntentDecision()
        assert d.plans == []
        assert d.source == "llm"

    def test_full_decision_serialization(self):
        d = IntentDecision(
            plans=[
                LayerQueryPlan(layer="L1", conditions=L1Conditions(content_query="q")),
                LayerQueryPlan(layer="L3", conditions=L3Conditions(content_query="q"), is_fallback=True),
            ],
            time_range=TimeRange(start=1000.0, end=2000.0),
            reasoning="test",
            source="rule_fallback",
        )
        serialized = asdict(d)
        assert len(serialized["plans"]) == 2
        assert serialized["source"] == "rule_fallback"
        assert serialized["time_range"]["start"] == 1000.0


class TestIntentDeciderInput:
    def test_minimal(self):
        inp = IntentDeciderInput(query="hello")
        assert inp.user_id is None
        assert inp.source_filters == []

    def test_full(self):
        inp = IntentDeciderInput(
            query="what did I browse yesterday",
            user_id="u1",
            session_id="s1",
            raw_time_range={"relative": "1d"},
            source_filters=["chrome_history"],
            domain_filters=["external_activity"],
            recall_intent_hint="event_recall",
            query_mode_hint="detail",
        )
        assert inp.query_mode_hint == "detail"
        assert inp.recall_intent_hint == "event_recall"


class TestRetrievalQueryBackwardCompat:
    def test_query_mode_now_optional(self):
        q = RetrievalQuery(
            query="test",
            user_id="u1",
            session_id="s1",
            time_range={},
        )
        assert q.query_mode is None

    def test_query_mode_still_accepted(self):
        q = RetrievalQuery(
            query="test",
            user_id="u1",
            session_id="s1",
            time_range={},
            recall_intent="preference_recall",
            query_mode="detail",
        )
        assert q.query_mode == "detail"
        assert q.recall_intent == "preference_recall"


class TestRetrievalConfig:
    def test_defaults(self):
        cfg = RetrievalConfig()
        assert cfg.default_max_tokens == 8192
        assert cfg.fallback_trigger_threshold == 1
        assert cfg.vector_max_distance == 0.7
        assert cfg.rrf_k == 60
        assert cfg.intent_decider_llm_enabled is True

    def test_custom(self):
        cfg = RetrievalConfig(default_max_tokens=4096, vector_max_distance=0.5)
        assert cfg.default_max_tokens == 4096
        assert cfg.vector_max_distance == 0.5


class TestRetrievalPayload:
    def test_empty(self):
        p = RetrievalPayload()
        assert p.l0_workbench == []
        assert p.trace == {}
