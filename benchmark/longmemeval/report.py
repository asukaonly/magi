"""Local retrieval reporting helpers for LongMemEval benchmark runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from benchmark.common.io import write_jsonl


def build_official_predictions(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "question_id": str(row.get("question_id") or ""),
            "hypothesis": str(row.get("hypothesis") or ""),
        }
        for row in rows
    ]


def compute_session_recall_summary(
    rows: Iterable[Mapping[str, Any]],
    *,
    k: int = 1,
) -> dict[str, Any]:
    total_questions = 0
    evaluated_questions = 0
    abstention_questions = 0
    recall_hits = 0

    for row in rows:
        total_questions += 1
        metadata = row.get("metadata") or {}
        if bool(metadata.get("is_abstention", False)):
            abstention_questions += 1
            continue

        evaluated_questions += 1
        expected_ids = [str(item) for item in row.get("answer_session_ids") or [] if str(item).strip()]
        retrieved_ids = [str(item) for item in row.get("retrieved_session_ids") or [] if str(item).strip()]
        if not expected_ids:
            continue
        candidate_ids = retrieved_ids[: max(k, 0)]
        if any(expected_id in candidate_ids for expected_id in expected_ids):
            recall_hits += 1

    recall_at_k = (recall_hits / evaluated_questions) if evaluated_questions else 0.0
    return {
        "total_questions": total_questions,
        "evaluated_questions": evaluated_questions,
        "abstention_questions": abstention_questions,
        "session_recall_at_k": recall_at_k,
        "k": k,
    }


def export_official_predictions(path: str | Path, rows: Iterable[Mapping[str, Any]]) -> Path:
    return write_jsonl(path, build_official_predictions(rows))
