"""Tests for LongMemEval dataset adaptation."""

from __future__ import annotations

from datetime import datetime, timezone

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


def test_adapter_parses_session_dates_into_real_timestamps() -> None:
    entry = {
        "question_id": "q-3",
        "question_type": "single-session-user",
        "question": "When did I mention this?",
        "answer": "March 10",
        "question_date": "2024-01-10",
        "answer_session_ids": ["sess-1"],
        "haystack_session_ids": ["sess-1"],
        "haystack_dates": ["2023/03/10 (Fri) 23:15"],
        "haystack_sessions": [
            [
                {"role": "user", "content": "First message."},
                {"role": "assistant", "content": "Second message."},
            ]
        ],
    }

    adapted = adapt_longmemeval_entry(
        entry,
        namespace="benchmark/longmemeval/run-1/q-3",
    )

    expected_base = datetime.strptime("2023/03/10 (Fri) 23:15", "%Y/%m/%d (%a) %H:%M").replace(
        tzinfo=timezone.utc
    ).timestamp()
    assert adapted.replay_records[0].timestamp == expected_base
    assert adapted.replay_records[1].timestamp > adapted.replay_records[0].timestamp
    assert adapted.replay_records[1].timestamp < expected_base + 60.0


def test_adapter_query_timestamp_uses_question_date_when_available() -> None:
    entry = {
        "question_id": "q-4",
        "question_type": "temporal-reasoning",
        "question": "How many days ago did X happen?",
        "answer": "4 days",
        "question_date": "2023/04/10 (Mon) 10:28",
        "answer_session_ids": ["sess-1"],
        "haystack_session_ids": ["sess-1"],
        "haystack_dates": ["2023/04/06 (Thu) 23:42"],
        "haystack_sessions": [
            [{"role": "user", "content": "X happened today."}],
        ],
    }

    adapted = adapt_longmemeval_entry(
        entry,
        namespace="benchmark/longmemeval/run-1/q-4",
    )

    expected_ts = datetime.strptime("2023/04/10 (Mon) 10:28", "%Y/%m/%d (%a) %H:%M").replace(
        tzinfo=timezone.utc
    ).timestamp()
    assert adapted.query.query_timestamp == expected_ts


def test_adapter_query_timestamp_falls_back_to_replay_max_when_no_question_date() -> None:
    entry = {
        "question_id": "q-5",
        "question_type": "single-session-user",
        "question": "What did I say?",
        "answer": "Hello",
        "answer_session_ids": ["sess-1"],
        "haystack_session_ids": ["sess-1"],
        "haystack_dates": ["2024-01-05"],
        "haystack_sessions": [
            [{"role": "user", "content": "Hello."}],
        ],
    }

    adapted = adapt_longmemeval_entry(
        entry,
        namespace="benchmark/longmemeval/run-1/q-5",
    )

    max_replay_ts = max(r.timestamp for r in adapted.replay_records)
    assert adapted.query.query_timestamp == max_replay_ts + 1.0
