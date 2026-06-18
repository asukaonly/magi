"""Tests for LoCoMo reporting helpers."""

from __future__ import annotations

from benchmark.locomo.report import (
    CATEGORY_LABELS,
    build_locomo_predictions_payload,
    compute_locomo_summary,
    score_locomo_qa,
)


def test_report_scores_single_multi_and_adversarial_categories() -> None:
    assert score_locomo_qa(category=4, prediction="support group", answer="the support group") > 0.6
    assert score_locomo_qa(
        category=1,
        prediction="pottery, camping",
        answer="camping, pottery",
    ) == 1.0
    assert score_locomo_qa(
        category=5,
        prediction="No information available",
        answer="Paris",
    ) == 1.0


def test_report_builds_summary_by_category() -> None:
    rows = [
        {
            "category": 4,
            "category_label": CATEGORY_LABELS[4],
            "hypothesis": "support group",
            "expected_answer": "support group",
            "answer_session_ids": ["session_1"],
            "retrieved_session_ids": ["session_1"],
        },
        {
            "category": 5,
            "category_label": CATEGORY_LABELS[5],
            "hypothesis": "No information available",
            "expected_answer": "Paris",
            "answer_session_ids": [],
            "retrieved_session_ids": [],
        },
    ]

    summary = compute_locomo_summary(rows)

    assert summary["total_questions"] == 2
    assert summary["overall_f1"] == 1.0
    assert summary["retrieval"]["evaluated_questions"] == 1
    assert summary["retrieval"]["session_recall_at_1"] == 1.0


def test_report_exports_official_shaped_locomo_predictions() -> None:
    samples = [
        {
            "sample_id": "conv-test",
            "conversation": {},
            "qa": [
                {"question": "Q1", "answer": "A1", "category": 4, "evidence": ["D1:1"]},
                {"question": "Q2", "answer": "A2", "category": 5, "evidence": []},
            ],
        }
    ]
    rows = [
        {
            "sample_id": "conv-test",
            "qa_index": 0,
            "hypothesis": "A1",
            "retrieved_turn_ids": ["D1:1"],
        },
        {
            "sample_id": "conv-test",
            "qa_index": 1,
            "hypothesis": "No information available",
            "retrieved_turn_ids": [],
        },
    ]

    payload = build_locomo_predictions_payload(samples=samples, prediction_rows=rows)

    assert payload[0]["sample_id"] == "conv-test"
    assert payload[0]["qa"][0]["magi_prediction"] == "A1"
    assert payload[0]["qa"][0]["magi_context"] == ["D1:1"]
