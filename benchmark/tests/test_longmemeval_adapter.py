"""Tests for LongMemEval dataset adaptation."""

from __future__ import annotations

from benchmark.longmemeval.adapter import adapt_longmemeval_entry


def test_adapter_converts_entry_into_replay_records_and_query() -> None:
    entry = {
        "question_id": "q-1",
        "question_type": "multi-session",
        "question": "What food do I prefer?",
        "answer": "Sushi",
        "question_date": "2024-01-10",
        "answer_session_ids": ["sess-2"],
        "haystack_session_ids": ["sess-1", "sess-2"],
        "haystack_dates": ["2024-01-01", "2024-01-05"],
        "haystack_sessions": [
            [
                {"role": "user", "content": "I like pasta."},
                {"role": "assistant", "content": "Noted."},
            ],
            [
                {"role": "user", "content": "Actually sushi is my favorite.", "has_answer": True},
            ],
        ],
    }

    adapted = adapt_longmemeval_entry(
        entry,
        namespace="benchmark/longmemeval/run-1/q-1",
    )

    assert adapted.question_id == "q-1"
    assert adapted.question_type == "multi-session"
    assert adapted.expected_answer == "Sushi"
    assert adapted.answer_session_ids == ["sess-2"]
    assert adapted.query.namespace == "benchmark/longmemeval/run-1/q-1"
    assert adapted.query.query == "What food do I prefer?"
    assert [record.session_id for record in adapted.replay_records] == ["sess-1", "sess-1", "sess-2"]
    assert adapted.replay_records[0].role == "user"
    assert adapted.replay_records[1].role == "assistant"
    assert adapted.replay_records[2].metadata["has_answer"] is True


def test_adapter_marks_abstention_questions() -> None:
    entry = {
        "question_id": "q-2_abs",
        "question_type": "single-session-user",
        "question": "What is my passport number?",
        "answer": "unknown",
        "question_date": "2024-01-10",
        "answer_session_ids": [],
        "haystack_session_ids": [],
        "haystack_dates": [],
        "haystack_sessions": [],
    }

    adapted = adapt_longmemeval_entry(
        entry,
        namespace="benchmark/longmemeval/run-1/q-2_abs",
    )

    assert adapted.metadata["is_abstention"] is True
