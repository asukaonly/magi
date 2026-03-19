"""Tests for LongMemEval local reporting helpers."""

from __future__ import annotations

from benchmark.common.io import read_jsonl
from benchmark.longmemeval.report import (
    build_official_predictions,
    compute_session_recall_summary,
    export_official_predictions,
)


def test_report_computes_session_recall_and_tracks_abstention() -> None:
    rows = [
        {
            "question_id": "q-1",
            "hypothesis": "A",
            "answer_session_ids": ["sess-2"],
            "retrieved_session_ids": ["sess-2", "sess-1"],
            "metadata": {"is_abstention": False},
        },
        {
            "question_id": "q-2",
            "hypothesis": "B",
            "answer_session_ids": ["sess-9"],
            "retrieved_session_ids": ["sess-1"],
            "metadata": {"is_abstention": False},
        },
        {
            "question_id": "q-3_abs",
            "hypothesis": "unknown",
            "answer_session_ids": [],
            "retrieved_session_ids": [],
            "metadata": {"is_abstention": True},
        },
    ]

    summary = compute_session_recall_summary(rows, k=1)

    assert summary == {
        "total_questions": 3,
        "evaluated_questions": 2,
        "abstention_questions": 1,
        "session_recall_at_k": 0.5,
        "k": 1,
    }


def test_report_exports_longmemeval_compatible_predictions(tmp_path) -> None:
    rows = [
        {"question_id": "q-1", "hypothesis": "Answer A", "trace": {"ignored": True}},
        {"question_id": "q-2", "hypothesis": "Answer B", "metadata": {"foo": "bar"}},
    ]

    assert build_official_predictions(rows) == [
        {"question_id": "q-1", "hypothesis": "Answer A"},
        {"question_id": "q-2", "hypothesis": "Answer B"},
    ]

    output_path = export_official_predictions(tmp_path / "predictions.jsonl", rows)
    assert read_jsonl(output_path) == [
        {"question_id": "q-1", "hypothesis": "Answer A"},
        {"question_id": "q-2", "hypothesis": "Answer B"},
    ]
