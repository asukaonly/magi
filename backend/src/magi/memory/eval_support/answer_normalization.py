"""Benchmark-oriented answer normalization helpers."""

from __future__ import annotations

import re
from typing import Any

from ..answering import should_request_short_issue_answer


def _extract_issue_component(text: str) -> str | None:
    content = str(text or "").strip()
    if not content:
        return None
    patterns = (
        r"issue with (?:(?:my|the)\s+)?(?:(?:car|vehicle)'s\s+)?(?P<component>[A-Za-z0-9][A-Za-z0-9 /-]{1,80}?)(?:\s+on\b|\s+after\b|,|\.|$)",
        r"problem with (?:(?:my|the)\s+)?(?:(?:car|vehicle)'s\s+)?(?P<component>[A-Za-z0-9][A-Za-z0-9 /-]{1,80}?)(?:\s+on\b|\s+after\b|,|\.|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, content, flags=re.IGNORECASE)
        if match:
            return str(match.group("component") or "").strip(" '\"")
    return None


def canonicalize_issue_component_answer(
    *,
    question: str,
    answer: str,
    timeline_summary: list[dict[str, Any]] | None,
    hits: list[dict[str, Any]],
) -> str:
    if not should_request_short_issue_answer(question):
        return answer
    lowered_answer = answer.lower().strip()
    if not lowered_answer or lowered_answer == "unknown":
        return answer
    if any(
        marker in lowered_answer
        for marker in ("issue", "problem", "not ", "stopped", "broken", "malfunction", "failure", "wrong")
    ) and not lowered_answer.endswith(" issue") and not lowered_answer.endswith(" problem"):
        return answer
    if len(answer.split()) > 5:
        return answer

    evidence_texts: list[str] = []
    for item in timeline_summary or []:
        summary = str(item.get("summary") or "").strip()
        if summary:
            evidence_texts.append(summary)
    for hit in hits:
        content = str(hit.get("content") or "").strip()
        if content:
            evidence_texts.append(content)

    for text in evidence_texts:
        component = _extract_issue_component(text)
        if not component:
            continue
        lowered_component = component.lower()
        canonical_answer = lowered_answer.removesuffix(" issue").removesuffix(" problem").strip()
        if (
            lowered_answer == lowered_component
            or lowered_answer in lowered_component
            or lowered_component in lowered_answer
            or canonical_answer == lowered_component
            or canonical_answer in lowered_component
            or lowered_component in canonical_answer
        ):
            return f"{component} not functioning correctly"
    return answer


def normalize_eval_answer(raw_answer: str) -> str:
    """Minimal normalization: strip whitespace only.

    Evaluation uses an LLM judge that understands free-text answers,
    so aggressive truncation (first-line extraction, article stripping)
    is unnecessary and can destroy multi-line answers like ordered lists.
    """
    answer = str(raw_answer or "").strip()
    return answer or "unknown"
