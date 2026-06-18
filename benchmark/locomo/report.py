"""Local LoCoMo QA reporting helpers."""

from __future__ import annotations

import copy
import re
import string
from collections import Counter
from typing import Any, Sequence

from .adapter import CATEGORY_LABELS


def build_prediction_row(
    *,
    sample_id: str,
    qa_index: int,
    question_id: str,
    category: int,
    category_label: str,
    question: str,
    expected_answer: str,
    evidence: list[str],
    answer_session_ids: list[str],
    hypothesis: str,
    namespace: str,
    retrieved_session_ids: list[str],
    retrieved_turn_ids: list[str],
    retrieved_event_ids: list[str],
    trace: dict[str, Any],
    answer_trace: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Build a trace-rich prediction row for LoCoMo outputs."""
    return {
        "question_id": question_id,
        "sample_id": sample_id,
        "qa_index": qa_index,
        "category": category,
        "category_label": category_label,
        "question": question,
        "expected_answer": expected_answer,
        "evidence": evidence,
        "answer_session_ids": answer_session_ids,
        "namespace": namespace,
        "hypothesis": hypothesis,
        "retrieved_session_ids": retrieved_session_ids,
        "retrieved_turn_ids": retrieved_turn_ids,
        "retrieved_event_ids": retrieved_event_ids,
        "trace": trace,
        "answer_trace": answer_trace,
        "metadata": metadata,
    }


def build_official_predictions(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return compact JSONL rows similar to the LongMemEval predictions file."""
    return [
        {
            "question_id": str(row.get("question_id") or ""),
            "sample_id": str(row.get("sample_id") or ""),
            "qa_index": int(row.get("qa_index") or 0),
            "category": int(row.get("category") or 0),
            "category_label": str(row.get("category_label") or ""),
            "hypothesis": str(row.get("hypothesis") or ""),
        }
        for row in rows
    ]


def build_locomo_predictions_payload(
    *,
    samples: Sequence[dict[str, Any]],
    prediction_rows: Sequence[dict[str, Any]],
    prediction_key: str = "magi_prediction",
    context_key: str = "magi_context",
) -> list[dict[str, Any]]:
    """Build a LoCoMo-shaped JSON payload with Magi predictions inside QA rows."""
    by_sample_and_index = {
        (str(row.get("sample_id") or ""), int(row.get("qa_index") or 0)): row
        for row in prediction_rows
    }
    payload: list[dict[str, Any]] = []
    for sample in samples:
        sample_id = str(sample.get("sample_id") or "")
        out_sample = {
            "sample_id": sample_id,
            "qa": copy.deepcopy(list(sample.get("qa") or [])),
        }
        for qa_index, qa in enumerate(out_sample["qa"]):
            row = by_sample_and_index.get((sample_id, qa_index), {})
            qa[prediction_key] = str(row.get("hypothesis") or "")
            qa[context_key] = [str(item) for item in row.get("retrieved_turn_ids") or []]
        payload.append(out_sample)
    return payload


def compute_locomo_summary(rows: Sequence[dict[str, Any]], *, k: int = 1) -> dict[str, Any]:
    """Compute official-style F1 plus lightweight retrieval diagnostics."""
    scores: list[float] = []
    by_category: dict[int, list[float]] = {}
    retrieval_scores: list[float] = []

    for row in rows:
        category = int(row.get("category") or 0)
        score = score_locomo_qa(
            category=category,
            prediction=str(row.get("hypothesis") or ""),
            answer=str(row.get("expected_answer") or ""),
        )
        scores.append(score)
        by_category.setdefault(category, []).append(score)

        answer_sessions = [str(item) for item in row.get("answer_session_ids") or []]
        if answer_sessions:
            retrieved = [str(item) for item in row.get("retrieved_session_ids") or []][:k]
            overlap = len(set(answer_sessions) & set(retrieved))
            retrieval_scores.append(overlap / len(set(answer_sessions)))

    category_metrics = {
        str(category): {
            "label": CATEGORY_LABELS.get(category, f"category-{category}"),
            "f1": _round4(sum(values) / len(values)),
            "count": len(values),
        }
        for category, values in sorted(by_category.items())
    }
    return {
        "total_questions": len(rows),
        "overall_f1": _round4(sum(scores) / len(scores)) if scores else 0.0,
        "category_metrics": category_metrics,
        "retrieval": {
            "evaluated_questions": len(retrieval_scores),
            f"session_recall_at_{k}": _round4(sum(retrieval_scores) / len(retrieval_scores))
            if retrieval_scores
            else 0.0,
        },
    }


def score_locomo_qa(*, category: int, prediction: str, answer: str) -> float:
    """Score one LoCoMo QA item using the reference task's broad rules."""
    if int(category) == 5:
        lowered = str(prediction or "").lower()
        return 1.0 if any(
            marker in lowered
            for marker in (
                "no information available",
                "not mentioned",
                "unknown",
                "cannot be determined",
                "cannot determine",
            )
        ) else 0.0
    if int(category) == 1:
        return _multi_answer_f1(prediction, answer)
    return _token_f1(prediction, answer)


def _multi_answer_f1(prediction: str, answer: str) -> float:
    predictions = [part.strip() for part in str(prediction or "").split(",") if part.strip()]
    answers = [part.strip() for part in str(answer or "").split(",") if part.strip()]
    if not predictions or not answers:
        return 0.0
    return sum(max(_token_f1(pred, gold) for pred in predictions) for gold in answers) / len(answers)


def _token_f1(prediction: str, answer: str) -> float:
    prediction_tokens = _normalize_tokens(prediction)
    answer_tokens = _normalize_tokens(answer)
    if not prediction_tokens or not answer_tokens:
        return 0.0
    common = Counter(prediction_tokens) & Counter(answer_tokens)
    same = sum(common.values())
    if same == 0:
        return 0.0
    precision = same / len(prediction_tokens)
    recall = same / len(answer_tokens)
    return (2 * precision * recall) / (precision + recall)


def _normalize_tokens(text: str) -> list[str]:
    lowered = str(text or "").lower().replace(",", "")
    without_punc = "".join(ch for ch in lowered if ch not in set(string.punctuation))
    without_articles = re.sub(r"\b(a|an|the|and)\b", " ", without_punc)
    return [token for token in without_articles.split() if token]


def _round4(value: float) -> float:
    return round(float(value), 4)


__all__ = [
    "CATEGORY_LABELS",
    "build_locomo_predictions_payload",
    "build_official_predictions",
    "build_prediction_row",
    "compute_locomo_summary",
    "score_locomo_qa",
]
