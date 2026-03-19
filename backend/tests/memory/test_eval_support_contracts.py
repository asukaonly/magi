"""Tests for benchmark-agnostic memory eval support contracts."""

from __future__ import annotations

from dataclasses import asdict

from magi.memory.eval_support.contracts import (
    EvalMemoryHit,
    EvalMemoryQuery,
    EvalMemoryQueryResult,
    EvalMemoryWriteRecord,
)


def test_eval_memory_write_record_requires_core_fields() -> None:
    record = EvalMemoryWriteRecord(
        namespace="benchmark/longmemeval/run-1/q-1",
        session_id="session-1",
        timestamp=123.0,
        role="user",
        content="hello",
    )

    assert record.namespace == "benchmark/longmemeval/run-1/q-1"
    assert record.session_id == "session-1"
    assert record.timestamp == 123.0
    assert record.role == "user"
    assert record.content == "hello"
    assert record.turn_id is None
    assert record.metadata == {}


def test_eval_memory_query_defaults_mode_and_top_k() -> None:
    query = EvalMemoryQuery(
        namespace="benchmark/longmemeval/run-1/q-1",
        query="What did I say?",
        query_timestamp=456.0,
    )

    assert query.namespace == "benchmark/longmemeval/run-1/q-1"
    assert query.top_k == 10
    assert query.mode == "auto"
    assert query.query_timestamp == 456.0


def test_eval_memory_hit_keeps_traceable_ids() -> None:
    hit = EvalMemoryHit(
        event_id="evt-1",
        session_id="session-1",
        turn_id="turn-1",
        score=0.87,
        content="remember this",
        metadata={"source": "benchmark"},
    )

    assert asdict(hit)["event_id"] == "evt-1"
    assert asdict(hit)["session_id"] == "session-1"
    assert asdict(hit)["turn_id"] == "turn-1"
    assert asdict(hit)["score"] == 0.87


def test_eval_memory_query_result_deduplicates_retrieved_ids() -> None:
    result = EvalMemoryQueryResult(
        hits=[
            EvalMemoryHit(
                event_id="evt-1",
                session_id="session-1",
                turn_id="turn-1",
                score=0.9,
                content="one",
                metadata={},
            ),
            EvalMemoryHit(
                event_id="evt-2",
                session_id="session-1",
                turn_id="turn-2",
                score=0.8,
                content="two",
                metadata={},
            ),
            EvalMemoryHit(
                event_id="evt-3",
                session_id="session-2",
                turn_id="turn-2",
                score=0.7,
                content="three",
                metadata={},
            ),
        ]
    )

    assert result.retrieved_session_ids == ["session-1", "session-2"]
    assert result.retrieved_turn_ids == ["turn-1", "turn-2"]
    assert result.retrieved_event_ids == ["evt-1", "evt-2", "evt-3"]
    assert result.trace == {}
