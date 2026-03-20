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
