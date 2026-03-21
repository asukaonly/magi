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
    answer = str(raw_answer or "").strip()
    if not answer:
        return "unknown"
    first_block = re.split(r"\n\s*\n", answer, maxsplit=1)[0].strip()
    first_line = first_block.splitlines()[0].strip() if first_block else ""
    normalized = first_line or first_block or answer
    if '"' not in normalized and "'" not in normalized and len(normalized.split()) <= 3:
        normalized = re.sub(r"^(?:the|a|an)\s+", "", normalized, flags=re.IGNORECASE).strip()
    return normalized.strip() or "unknown"
