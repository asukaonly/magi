"""Tests for LoCoMo wrong-answer analysis."""

from __future__ import annotations

import json

from benchmark.locomo.error_report import analyze_prediction_errors, export_error_report


def _prediction_row(**overrides):
    row = {
        "question_id": "conv-test:qa-1",
        "sample_id": "conv-test",
        "qa_index": 0,
        "category": 4,
        "category_label": "single-hop",
        "question": "What did Caroline join?",
        "expected_answer": "support group",
        "evidence": ["D1:1"],
        "answer_session_ids": ["session_1"],
        "hypothesis": "unknown",
        "retrieved_session_ids": ["session_2"],
        "retrieved_turn_ids": ["D2:1"],
    }
    row.update(overrides)
    return row


def test_locomo_error_report_buckets_non_perfect_answers() -> None:
    report = analyze_prediction_errors(
        [
            _prediction_row(),
            _prediction_row(
                question_id="conv-test:qa-2",
                category=2,
                category_label="temporal",
                question="When did Melanie ask?",
                expected_answer="The week before 9 June 2023",
                hypothesis="last week",
                retrieved_session_ids=["session_1"],
                retrieved_turn_ids=["D1:1"],
            ),
            _prediction_row(
                question_id="conv-test:qa-3",
                expected_answer="support group",
                hypothesis="support group",
                retrieved_session_ids=["session_1"],
                retrieved_turn_ids=["D1:1"],
            ),
        ],
        top_k=1,
    )

    assert [row["question_id"] for row in report.rows] == [
        "conv-test:qa-1",
        "conv-test:qa-2",
    ]
    assert report.rows[0]["primary_bucket"] == "A. answer session miss"
    assert report.rows[0]["answer_session_hit"] is False
    assert report.rows[1]["primary_bucket"] == "C. partial answer / strict scoring"
    assert 0.0 < report.rows[1]["score"] < 1.0
    assert report.summary["non_perfect_question_count"] == 2
    assert report.summary["primary_buckets"] == {
        "A. answer session miss": 1,
        "C. partial answer / strict scoring": 1,
    }


def test_locomo_error_report_exports_jsonl_csv_and_summary(tmp_path) -> None:
    report = analyze_prediction_errors([_prediction_row()], top_k=5)

    artifacts = export_error_report(tmp_path, report)

    assert artifacts.jsonl_path.exists()
    assert artifacts.csv_path.exists()
    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["non_perfect_question_count"] == 1
    assert "conv-test:qa-1" in artifacts.jsonl_path.read_text(encoding="utf-8")
