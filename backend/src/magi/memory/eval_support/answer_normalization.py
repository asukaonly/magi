"""Benchmark-oriented answer normalization helpers."""

from __future__ import annotations


def normalize_eval_answer(raw_answer: str) -> str:
    """Minimal normalization: strip whitespace only.

    Evaluation uses an LLM judge that understands free-text answers,
    so aggressive truncation (first-line extraction, article stripping)
    is unnecessary and can destroy multi-line answers like ordered lists.
    """
    answer = str(raw_answer or "").strip()
    return answer or "unknown"
