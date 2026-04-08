"""Tests for LongMemEval error analysis reporting."""

from __future__ import annotations

import json

from benchmark.longmemeval.error_report import (
    analyze_prediction_errors,
    export_error_report,
)


def _build_reference(
    *,
    question_id: str,
    question_type: str,
    question: str,
    answer: str,
    session_turns: list[tuple[str, list[dict[str, object]]]],
) -> dict[str, object]:
    return {
        "question_id": question_id,
        "question_type": question_type,
        "question": question,
        "answer": answer,
        "haystack_session_ids": [session_id for session_id, _ in session_turns],
        "haystack_sessions": [turns for _, turns in session_turns],
    }


def test_analyze_prediction_errors_buckets_retrieval_bundle_and_synthesis() -> None:
    references = [
        _build_reference(
            question_id="q-session-miss",
            question_type="single-session-user",
            question="How many bikes do I own?",
            answer="three",
            session_turns=[
                (
                    "gold-session-a",
                    [
                        {"role": "user", "content": "I own three bikes.", "has_answer": True},
                    ],
                ),
            ],
        ),
        _build_reference(
            question_id="q-bundle-miss",
            question_type="single-session-user",
            question="Where do I take yoga classes?",
            answer="Serenity Yoga",
            session_turns=[
                (
                    "gold-session-b",
                    [
                        {"role": "user", "content": "Warm up.", "has_answer": False},
                        {"role": "assistant", "content": "Sure.", "has_answer": False},
                        {"role": "user", "content": "I go to Serenity Yoga.", "has_answer": True},
                        {"role": "assistant", "content": "Nice.", "has_answer": False},
                        {"role": "user", "content": "Home practice helps too.", "has_answer": False},
                        {"role": "assistant", "content": "Makes sense.", "has_answer": False},
                        {"role": "user", "content": "I like Down Dog.", "has_answer": False},
                    ],
                ),
            ],
        ),
        _build_reference(
            question_id="q-synthesis-miss",
            question_type="knowledge-update",
            question="What is my current 5K personal best?",
            answer="25:50",
            session_turns=[
                (
                    "gold-session-c-old",
                    [
                        {"role": "user", "content": "My PB was 27:12.", "has_answer": True},
                    ],
                ),
                (
                    "gold-session-c-new",
                    [
                        {"role": "user", "content": "My current PB is 25:50.", "has_answer": True},
                    ],
                ),
            ],
        ),
    ]
    predictions = [
        {
            "question_id": "q-session-miss",
            "question_type": "single-session-user",
            "hypothesis": "unknown",
            "answer_session_ids": ["gold-session-a"],
            "retrieved_session_ids": ["other-session"],
            "retrieved_turn_ids": ["other-session:turn-0"],
            "metadata": {"is_abstention": False},
        },
        {
            "question_id": "q-bundle-miss",
            "question_type": "single-session-user",
            "hypothesis": "Down Dog",
            "answer_session_ids": ["gold-session-b"],
            "retrieved_session_ids": ["gold-session-b", "other-session"],
            "retrieved_turn_ids": ["gold-session-b:turn-8"],
            "metadata": {"is_abstention": False},
        },
        {
            "question_id": "q-synthesis-miss",
            "question_type": "knowledge-update",
            "hypothesis": "27:12",
            "answer_session_ids": ["gold-session-c-old", "gold-session-c-new"],
            "retrieved_session_ids": ["gold-session-c-old", "gold-session-c-new"],
            "retrieved_turn_ids": ["gold-session-c-old:turn-0", "gold-session-c-new:turn-0"],
            "metadata": {"is_abstention": False},
        },
    ]
    eval_rows = [
        {"question_id": "q-session-miss", "autoeval_label": {"label": False}},
        {"question_id": "q-bundle-miss", "autoeval_label": {"label": False}},
        {"question_id": "q-synthesis-miss", "autoeval_label": {"label": False}},
    ]

    report = analyze_prediction_errors(
        references=references,
        predictions=predictions,
        eval_rows=eval_rows,
    )

    assert report.summary["wrong_question_count"] == 3
    assert report.summary["primary_buckets"] == {
        "A. session miss": 1,
        "B. same session, answer turn not in bundle": 1,
        "C. answer turn likely present, synthesis/judge miss": 1,
    }
    rows_by_qid = {row["question_id"]: row for row in report.rows}
    assert rows_by_qid["q-session-miss"]["secondary_bucket"] == "single/temporal retrieval miss"
    assert rows_by_qid["q-bundle-miss"]["secondary_bucket"] == "same-session local window miss"
    assert rows_by_qid["q-synthesis-miss"]["secondary_bucket"] == "stale-vs-updated fact selection"
    assert rows_by_qid["q-synthesis-miss"]["gold_turn_in_bundle"] is True


def test_export_error_report_writes_csv_jsonl_and_summary(tmp_path) -> None:
    references = [
        _build_reference(
            question_id="q-1",
            question_type="single-session-user",
            question="How many bikes do I own?",
            answer="three",
            session_turns=[
                (
                    "gold-session",
                    [
                        {"role": "user", "content": "I own three bikes.", "has_answer": True},
                    ],
                ),
            ],
        )
    ]
    predictions = [
        {
            "question_id": "q-1",
            "question_type": "single-session-user",
            "hypothesis": "unknown",
            "answer_session_ids": ["gold-session"],
            "retrieved_session_ids": [],
            "retrieved_turn_ids": [],
            "metadata": {"is_abstention": False},
        }
    ]
    eval_rows = [{"question_id": "q-1", "autoeval_label": {"label": False}}]

    report = analyze_prediction_errors(
        references=references,
        predictions=predictions,
        eval_rows=eval_rows,
    )

    artifacts = export_error_report(tmp_path, report)

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    table_rows = [json.loads(line) for line in artifacts.jsonl_path.read_text(encoding="utf-8").splitlines()]
    csv_lines = artifacts.csv_path.read_text(encoding="utf-8").splitlines()

    assert summary["wrong_question_count"] == 1
    assert table_rows[0]["question_id"] == "q-1"
    assert csv_lines[0].startswith("question_id,question_type,primary_bucket,secondary_bucket")
