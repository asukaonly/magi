"""Tests for ResultFusion."""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval.models import RetrievalConfig, RetrievalPayload
from magi.memory.hybrid_retrieval.result_fusion import (
    ResultFusion,
    estimate_tokens,
    truncate_to_budget,
)


# -----------------------------------------------------------------------
# estimate_tokens
# -----------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens([]) == 0

    def test_basic(self):
        items = [{"content": "abc"}]  # "content" = 7 chars, "abc" = 3 chars → 10 / 3 ≈ 3
        tokens = estimate_tokens(items, char_per_token=3.0)
        assert tokens > 0

    def test_multiple_items(self):
        items = [{"a": "x"}, {"b": "y"}]
        tokens = estimate_tokens(items, char_per_token=1.0)
        assert tokens > 0


# -----------------------------------------------------------------------
# truncate_to_budget
# -----------------------------------------------------------------------


class TestTruncateToBudget:
    def test_all_fit(self):
        items = [{"content": "short"}]
        result = truncate_to_budget(items, budget_tokens=1000)
        assert len(result) == 1

    def test_truncation(self):
        items = [{"content": "a" * 300} for _ in range(10)]
        result = truncate_to_budget(items, budget_tokens=100, char_per_token=3.0)
        assert len(result) < 10

    def test_zero_budget(self):
        items = [{"content": "x"}]
        result = truncate_to_budget(items, budget_tokens=0)
        assert len(result) == 0

    def test_negative_budget(self):
        items = [{"content": "x"}]
        result = truncate_to_budget(items, budget_tokens=-100)
        assert len(result) == 0


# -----------------------------------------------------------------------
# ResultFusion.dedup
# -----------------------------------------------------------------------


class TestDedup:
    def test_l1_dedup_by_event_id(self):
        fusion = ResultFusion()
        payload = RetrievalPayload(
            l1_events=[
                {"event_id": "e1", "content": "first"},
                {"event_id": "e1", "content": "duplicate"},
                {"event_id": "e2", "content": "second"},
            ],
        )
        result = fusion.apply(payload, max_tokens=100000)
        event_ids = [e["event_id"] for e in result.l1_events]
        assert event_ids == ["e1", "e2"]

    def test_l2_dedup_by_entity_id(self):
        fusion = ResultFusion()
        payload = RetrievalPayload(
            l2_entity_cards=[
                {"entity_id": "alice"},
                {"entity_id": "alice"},
                {"entity_id": "bob"},
            ],
        )
        result = fusion.apply(payload, max_tokens=100000)
        assert len(result.l2_entity_cards) == 2

    def test_l3_dedup_by_summary_id(self):
        fusion = ResultFusion()
        payload = RetrievalPayload(
            l3_reflections=[
                {"summary_id": "s1", "content": "a"},
                {"summary_id": "s1", "content": "b"},
            ],
        )
        result = fusion.apply(payload, max_tokens=100000)
        assert len(result.l3_reflections) == 1

    def test_l3_dedup_fallback_id(self):
        fusion = ResultFusion()
        payload = RetrievalPayload(
            l3_reflections=[
                {"id": "s1", "content": "a"},
                {"id": "s1", "content": "b"},
            ],
        )
        result = fusion.apply(payload, max_tokens=100000)
        assert len(result.l3_reflections) == 1

    def test_items_without_id_preserved(self):
        fusion = ResultFusion()
        payload = RetrievalPayload(
            l1_events=[
                {"content": "no id 1"},
                {"content": "no id 2"},
            ],
        )
        result = fusion.apply(payload, max_tokens=100000)
        assert len(result.l1_events) == 2


# -----------------------------------------------------------------------
# Token budget
# -----------------------------------------------------------------------


class TestTokenBudget:
    def test_budget_limits_l1(self):
        fusion = ResultFusion(RetrievalConfig(default_max_tokens=50))
        # Generate lots of L1 events
        payload = RetrievalPayload(
            l1_events=[{"event_id": f"e{i}", "content": "x" * 300} for i in range(100)],
        )
        result = fusion.apply(payload)
        assert len(result.l1_events) < 100

    def test_l0_l2_consume_budget(self):
        fusion = ResultFusion(RetrievalConfig(default_max_tokens=100))
        payload = RetrievalPayload(
            l0_workbench=[{"session": "x" * 200}],  # consumes budget
            l1_events=[{"event_id": f"e{i}", "content": "y" * 100} for i in range(10)],
        )
        result = fusion.apply(payload)
        # L0 eats budget, so fewer L1 events fit
        assert len(result.l1_events) < 10

    def test_large_l0_is_soft_capped_before_it_starves_other_layers(self):
        fusion = ResultFusion(RetrievalConfig(default_max_tokens=120))
        payload = RetrievalPayload(
            l0_workbench=[
                {"session": "x" * 180},
                {"session": "y" * 180},
                {"session": "z" * 180},
            ],
            l1_events=[{"event_id": "e1", "content": "useful evidence" * 8}],
        )

        result = fusion.apply(payload)

        assert len(result.l0_workbench) < 3
        assert len(result.l1_events) == 1

    def test_explicit_max_tokens_overrides_config(self):
        fusion = ResultFusion(RetrievalConfig(default_max_tokens=100000))
        payload = RetrievalPayload(
            l1_events=[{"event_id": f"e{i}", "content": "y" * 300} for i in range(100)],
        )
        result = fusion.apply(payload, max_tokens=50)
        assert len(result.l1_events) < 100

    def test_budget_preserves_top_l1_event_per_session_when_possible(self):
        fusion = ResultFusion(RetrievalConfig(default_max_tokens=100000))
        session_one_first = {
            "event_id": "s1-a",
            "session_id": "session-1",
            "content": "first session event about workshop",
            "retrieval_score": 0.9,
        }
        session_one_second = {
            "event_id": "s1-b",
            "session_id": "session-1",
            "content": "second session event about workshop",
            "retrieval_score": 0.8,
        }
        session_two_first = {
            "event_id": "s2-a",
            "session_id": "session-2",
            "content": "other session event about webinar",
            "retrieval_score": 0.85,
        }
        payload = RetrievalPayload(
            l1_events=[session_one_first, session_one_second, session_two_first],
        )

        budget = estimate_tokens([session_one_first, session_two_first])
        result = fusion.apply(payload, max_tokens=budget)

        assert [item["event_id"] for item in result.l1_events] == ["s1-a", "s2-a"]

    def test_budget_prefers_best_scored_user_anchor_within_session(self):
        fusion = ResultFusion(RetrievalConfig(default_max_tokens=100000))
        assistant_guidance = {
            "event_id": "assistant-generic",
            "session_id": "session-1",
            "content": "Here are some tips and suggestions for comparing workshop notes and webinar reminders.",
            "author_type": "assistant",
            "retrieval_score": 0.4,
        }
        user_anchor = {
            "event_id": "user-anchor",
            "session_id": "session-1",
            "content": "I attended the Effective Time Management workshop last Saturday.",
            "author_type": "user",
            "retrieval_score": 0.9,
        }
        payload = RetrievalPayload(
            l1_events=[assistant_guidance, user_anchor],
        )

        budget = estimate_tokens([user_anchor])
        result = fusion.apply(payload, max_tokens=budget)

        assert [item["event_id"] for item in result.l1_events] == ["user-anchor"]


# -----------------------------------------------------------------------
# Full integration
# -----------------------------------------------------------------------


class TestResultFusionIntegration:
    def test_full_payload(self):
        fusion = ResultFusion(RetrievalConfig(default_max_tokens=10000))
        payload = RetrievalPayload(
            l0_workbench=[{"session": "active"}],
            l1_events=[{"event_id": f"e{i}", "content": f"event {i}"} for i in range(5)],
            l2_entity_cards=[{"entity_id": "alice"}],
            l2_relationships=[{"subject": "alice", "object": "bob"}],
            l3_reflections=[{"summary_id": "s1", "content": "weekly summary"}],
            l4_procedures=[{"id": "p1", "content": "deploy steps"}],
        )
        result = fusion.apply(payload)

        # All data preserved with generous budget
        assert len(result.l0_workbench) == 1
        assert len(result.l1_events) == 5
        assert len(result.l2_entity_cards) == 1
        assert len(result.l3_reflections) == 1
        assert len(result.l4_procedures) == 1

    def test_empty_payload(self):
        fusion = ResultFusion()
        payload = RetrievalPayload()
        result = fusion.apply(payload)
        assert result.l1_events == []
        assert result.l3_reflections == []
