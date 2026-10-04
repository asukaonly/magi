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
    @pytest.mark.parametrize(
        "items,ratio,expected",
        [
            ([], 3.0, 0),
            ([{"content": "abcdef"}], 3.0, 2),
            ([{"content": "abcdef"}], 2.0, 3),
            ([{"a": "xy"}, {"b": "abcde"}], 2.0, 3),
            ([{"long-key-is-not-content": "xy", "number": 123}], 1.0, 5),
        ],
    )
    def test_estimates_value_characters_across_items(self, items, ratio, expected):
        assert estimate_tokens(items, char_per_token=ratio) == expected


# -----------------------------------------------------------------------
# truncate_to_budget
# -----------------------------------------------------------------------


class TestTruncateToBudget:
    @pytest.mark.parametrize(
        "budget,expected_count", [(-1, 0), (0, 0), (2, 0), (3, 1), (6, 1), (7, 2), (8, 3), (100, 3)]
    )
    def test_preserves_the_largest_fitting_prefix(self, budget, expected_count):
        items = [{"content": "abc"}, {"content": "defg"}, {"content": "h"}]
        assert (
            truncate_to_budget(items, budget_tokens=budget, char_per_token=1.0)
            == items[:expected_count]
        )


# -----------------------------------------------------------------------
# ResultFusion.dedup
# -----------------------------------------------------------------------


class TestDedup:
    @pytest.mark.parametrize(
        "section,key",
        [
            ("l1_events", "event_id"),
            ("l2_entity_cards", "entity_id"),
            ("l2_assertions", "assertion_id"),
            ("l2_experiences", "experience_id"),
            ("l3_reflections", "summary_id"),
            ("l3_reflections", "id"),
            ("l4_procedures", "id"),
        ],
    )
    def test_dedup_keeps_first_record_and_distinct_or_unidentified_records(self, section, key):
        first = {key: "a", "content": "first"}
        duplicate = {key: "a", "content": "must not replace first"}
        other = {key: "b", "content": "second"}
        no_id = [{"content": "no id 1"}, {"content": "no id 2"}]
        payload = RetrievalPayload(**{section: [first, duplicate, other, *no_id]})
        result = ResultFusion().apply(payload, max_tokens=100000)
        assert getattr(result, section) == [first, other, *no_id]


# -----------------------------------------------------------------------
# Token budget
# -----------------------------------------------------------------------


class TestTokenBudget:
    @pytest.mark.parametrize(
        "configured,override,expected_count",
        [(100, None, 5), (40, None, 2), (100, 40, 2), (40, 100, 5)],
    )
    def test_l1_selection_honors_configured_or_explicit_budget(
        self, configured, override, expected_count
    ):
        # Each record costs ten characters; L1 receives half the total budget.
        rows = [{"event_id": f"e{i}", "content": "abcdefgh"} for i in range(6)]
        config = RetrievalConfig(default_max_tokens=configured, char_per_token_ratio=1.0)
        result = ResultFusion(config).apply(RetrievalPayload(l1_events=rows), max_tokens=override)
        assert result.l1_events == rows[:expected_count]

    @pytest.mark.parametrize(
        "with_l0,with_l2,l1_count,l3_count",
        [
            (False, False, 5, 2),
            (True, False, 4, 1),
            (False, True, 5, 1),
            (True, True, 4, 1),
        ],
    )
    def test_layer_costs_reduce_only_lower_priority_allocations(
        self, with_l0, with_l2, l1_count, l3_count
    ):
        l0 = [{"session": "x" * 20}] if with_l0 else []
        l1 = [{"event_id": f"e{i}", "content": "abcdefgh"} for i in range(6)]
        l2 = [{"entity_id": "p1", "content": "abcdefghij"}] if with_l2 else []
        l3 = [{"summary_id": f"s{i}", "content": "abcdefgh"} for i in range(3)]
        payload = RetrievalPayload(l0_workbench=l0, l1_events=l1, l2_entity_cards=l2, l3_reflections=l3)
        result = ResultFusion(RetrievalConfig(default_max_tokens=100, char_per_token_ratio=1.0)).apply(
            payload
        )
        assert result.l0_workbench == l0
        assert result.l1_events == l1[:l1_count]
        assert result.l2_entity_cards == l2
        assert result.l3_reflections == l3[:l3_count]

    def test_large_l0_is_soft_capped_before_it_starves_other_layers(self):
        fusion = ResultFusion(RetrievalConfig(default_max_tokens=120, l0_budget_ratio=0.3))
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

        # L1 gets 50% of remaining budget, so we need 2x the token count
        # to ensure both session anchors fit within the L1 slice.
        budget = estimate_tokens([session_one_first, session_two_first]) * 2 + 1
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

        # L1 gets 50% of budget, so provide enough room.
        budget = estimate_tokens([user_anchor]) * 2 + 1
        result = fusion.apply(payload, max_tokens=budget)

        assert [item["event_id"] for item in result.l1_events] == ["user-anchor"]


# -----------------------------------------------------------------------
# Full integration
# -----------------------------------------------------------------------


class TestResultFusionIntegration:
    @pytest.mark.parametrize("populated", [False, True])
    def test_generous_budget_preserves_every_payload_section(self, populated):
        from copy import deepcopy
        from dataclasses import fields

        payload = RetrievalPayload()
        if populated:
            for field in fields(payload):
                value = {"content": f"content for {field.name}"}
                setattr(payload, field.name, value if field.name == "trace" else [value])
        expected = deepcopy(payload)
        result = ResultFusion(RetrievalConfig(default_max_tokens=10000)).apply(payload)
        assert result == expected
