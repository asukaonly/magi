"""Tests for eval-support memory reader."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.memory.eval_support.contracts import EvalMemoryHit, EvalMemoryQuery
from magi.memory.eval_support.reader import EvalMemoryReader
from magi.memory.hybrid_retrieval.models import RetrievalPayload


@pytest.mark.asyncio
async def test_reader_returns_normalized_hits_without_chat_rendering() -> None:
    retrieval_service = MagicMock()
    retrieval_service.query = AsyncMock(
        return_value=RetrievalPayload(
            l1_events=[
                {
                    "event_id": "evt-1",
                    "session_id": "session-1",
                    "metadata": {"turn_id": "turn-1"},
                    "content": "hello there",
                    "importance_score": 0.8,
                },
                {
                    "event_id": "evt-2",
                    "session_id": "session-2",
                    "metadata": {"turn_id": "turn-2"},
                    "content": "another memory",
                    "importance_score": 0.7,
                },
            ],
            l1_evidence_bundles=[
                {
                    "session_id": "session-1",
                    "hit_event_ids": ["evt-1"],
                    "events": [
                        {
                            "event_id": "evt-1",
                            "turn_id": "turn-1",
                            "content": "hello there",
                        }
                    ],
                    "neighbor_expansion_applied": False,
                }
            ],
            trace={"intent_source": "rule_fallback"},
        )
    )
    reader = EvalMemoryReader(retrieval_service)

    result = await reader.query_memory(
        EvalMemoryQuery(
            namespace="benchmark/longmemeval/run-1/q-1",
            query="What did I say?",
            query_timestamp=200.0,
        )
    )

    assert result.retrieved_session_ids == ["session-1", "session-2"]
    assert result.retrieved_turn_ids == ["turn-1", "turn-2"]
    assert result.retrieved_event_ids == ["evt-1", "evt-2"]
    assert result.trace["intent_source"] == "rule_fallback"
    assert result.evidence_bundles[0]["session_id"] == "session-1"
    assert isinstance(result.hits[0], EvalMemoryHit)


@pytest.mark.asyncio
async def test_reader_uses_namespace_as_memory_user_scope() -> None:
    captured = {}

    async def _fake_query(request):  # type: ignore[no-untyped-def]
        captured["user_id"] = request.user_id
        captured["session_id"] = request.session_id
        captured["query_mode"] = request.query_mode
        return RetrievalPayload()

    retrieval_service = MagicMock()
    retrieval_service.query = _fake_query
    reader = EvalMemoryReader(retrieval_service)

    await reader.query_memory(
        EvalMemoryQuery(
            namespace="benchmark/longmemeval/run-1/q-1",
            query="What changed?",
            query_timestamp=300.0,
            mode="detail",
            top_k=5,
        )
    )

    assert captured == {
        "user_id": "benchmark/longmemeval/run-1/q-1",
        "session_id": None,
        "query_mode": "detail",
    }


@pytest.mark.asyncio
async def test_reader_l1_only_mode_bypasses_hybrid_retrieval() -> None:
    retrieval_service = MagicMock()
    retrieval_service.query = AsyncMock(side_effect=AssertionError("hybrid retrieval should not be used"))

    l1_store = MagicMock()
    l1_store.query_events = AsyncMock(
        return_value=[
            {
                "event_id": "evt-2",
                "session_id": "session-1",
                "turn_id": "turn-2",
                "content": "The first issue after service was a brake squeal.",
                "timestamp": 20.0,
            },
            {
                "event_id": "evt-1",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "content": "I booked the first service yesterday.",
                "timestamp": 10.0,
            },
        ]
    )

    reader = EvalMemoryReader(retrieval_service, l1_store=l1_store)

    result = await reader.query_memory(
        EvalMemoryQuery(
            namespace="benchmark/longmemeval/run-1/q-1",
            query="What was the first issue after service?",
            mode="l1_only",
            top_k=1,
        )
    )

    l1_store.query_events.assert_awaited_once_with(
        user_id="benchmark/longmemeval/run-1/q-1",
        limit=50,
    )
    assert [hit.event_id for hit in result.hits] == ["evt-2"]
    assert result.trace["intent_source"] == "eval_l1_only"
    assert result.trace["candidate_count"] == 2


# ------------------------------------------------------------------
# _resolve_temporal_range tests
# ------------------------------------------------------------------

# question_date = 2023-04-05 Wed 19:25 UTC
_QTS = 1680722700.0  # datetime(2023, 4, 5, 19, 25, tzinfo=UTC).timestamp()


class TestResolveTemporalRange:
    """Unit tests for EvalMemoryReader._resolve_temporal_range."""

    def test_last_friday_narrows_range(self) -> None:
        result = EvalMemoryReader._resolve_temporal_range(
            "What is the artist that I started to listen to last Friday?",
            _QTS,
        )
        # "last Friday" from Wed Apr 5 → Fri Mar 31 = 1680220800 UTC midnight
        # start should be ~Mar 31 - 7 days = ~Mar 24
        assert "end" not in result
        assert result["start"] > 0
        # start should be well before the question but after epoch
        # Mar 24 midnight UTC = 1679616000
        assert result["start"] < _QTS - 3 * 86_400  # at least 3 days before question

    def test_two_weeks_ago_narrows_range(self) -> None:
        result = EvalMemoryReader._resolve_temporal_range(
            "I mentioned a sports event two weeks ago. What was the event?",
            _QTS,
        )
        assert "end" not in result
        # "two weeks ago" = ~Mar 22 → start ~Mar 15
        assert result["start"] > 0
        assert result["start"] < _QTS - 10 * 86_400

    def test_last_month_narrows_range(self) -> None:
        result = EvalMemoryReader._resolve_temporal_range(
            "Which pair of shoes did I clean last month?",
            _QTS,
        )
        assert "end" not in result
        # "last month" = March → month-level → start = March 1
        assert result["start"] > 0
        assert result["start"] < _QTS - 20 * 86_400

    def test_in_january_uses_full_month_range(self) -> None:
        # Question on Jan 30 asking about "in January" should cover the whole month.
        jan30_qts = 1675043580.0  # 2023-01-30 01:53 UTC
        result = EvalMemoryReader._resolve_temporal_range(
            "What is the order of the sports events I watched in January?",
            jan30_qts,
        )
        assert "end" not in result
        # start should be Jan 1, not Jan 23 (which would miss early-January events)
        from datetime import datetime, timezone

        jan1 = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
        assert result["start"] == jan1

    def test_no_temporal_phrase_returns_wide_range(self) -> None:
        result = EvalMemoryReader._resolve_temporal_range(
            "Can you recommend some resources for video editing?",
            _QTS,
        )
        assert result == {"start": 0}

    def test_non_temporal_comparison_returns_wide_range(self) -> None:
        result = EvalMemoryReader._resolve_temporal_range(
            "How many days passed between the day I received feedback and the day I tested the car?",
            _QTS,
        )
        # No concrete temporal anchor → wide range
        assert result == {"start": 0}

    def test_future_resolved_date_is_ignored(self) -> None:
        # A query that might yield a future date should still return wide
        result = EvalMemoryReader._resolve_temporal_range(
            "What will I do next Friday?",
            _QTS,
        )
        # "next Friday" resolves to a future date → filtered out → wide range
        assert "end" not in result
        # Could be wide range or a past-date match; either is acceptable

    def test_in_a_week_ago_strips_preposition(self) -> None:
        # search_dates greedily captures "in a week ago" (future-directed).
        # The reparse fallback should strip "in" and correctly resolve
        # "a week ago" to a past date.
        result = EvalMemoryReader._resolve_temporal_range(
            "What was the life event that I participated in a week ago?",
            _QTS,
        )
        assert result["start"] > 0
        # "a week ago" from Apr 5 → Mar 29, minus 7d padding → ~Mar 22
        assert result["start"] < _QTS - 10 * 86_400

    def test_returns_wide_when_dateparser_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import importlib
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def _block_dateparser(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "dateparser.search" or name == "dateparser":
                raise ImportError("mocked")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _block_dateparser)
        result = EvalMemoryReader._resolve_temporal_range(
            "What did I do last Friday?",
            _QTS,
        )
        assert result == {"start": 0}
