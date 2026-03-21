"""Utilities for answerability-aware L1 reranking."""

from __future__ import annotations

import re
from typing import Sequence

_RERANK_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "did",
    "do",
    "does",
    "for",
    "had",
    "has",
    "have",
    "i",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "there",
    "they",
    "this",
    "to",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
}

_EVENT_PATTERNS = (
    re.compile(r"\b(i|we)\s+(attended|joined|participated|went|visited|took|had|experienced)\b", re.IGNORECASE),
    re.compile(r"\b(i|we)\s+(attend|join|participate|go|visit|take part in)\b", re.IGNORECASE),
)

_TEMPORAL_PATTERNS = (
    re.compile(r"\b\d{1,2}[/-]\d{1,2}\b"),
    re.compile(r"\b\d{1,2}:\d{2}\b"),
    re.compile(
        r"\b(last|yesterday|today|tomorrow|ago|week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        re.IGNORECASE,
    ),
)

_GUIDANCE_PATTERNS = (
    re.compile(r"\bhere (are|is)\b", re.IGNORECASE),
    re.compile(r"\b(tips|suggestions|recommendations)\b", re.IGNORECASE),
    re.compile(r"\byou can\b", re.IGNORECASE),
    re.compile(r"\bconsider\b", re.IGNORECASE),
    re.compile(r"\bcheck\b", re.IGNORECASE),
)


def extract_query_tokens(text: str) -> list[str]:
    """Extract normalized ranking tokens from a query or event body."""
    lowered = str(text or "").lower()
    raw_tokens = re.findall(r"[a-z0-9]+", lowered)
    return [
        token
        for token in raw_tokens
        if len(token) >= 2 and token not in _RERANK_STOP_WORDS
    ]


def extract_query_phrases(tokens: Sequence[str]) -> list[str]:
    """Extract short contiguous phrases for stronger exact-match boosts."""
    phrases: list[str] = []
    for window in (4, 3, 2):
        for index in range(0, max(len(tokens) - window + 1, 0)):
            phrase = " ".join(tokens[index : index + window]).strip()
            if phrase:
                phrases.append(phrase)
    return phrases


def extract_quoted_spans(text: str) -> list[str]:
    """Extract normalized quoted spans from a query."""
    quoted: list[str] = []
    for match in re.finditer(r"""["']([^"']{3,})["']""", str(text or "")):
        normalized = " ".join(extract_query_tokens(match.group(1)))
        if normalized:
            quoted.append(normalized)
    return quoted


def score_eventness(content: str, *, author_type: str) -> float:
    """Score how much a content block looks like a concrete event statement."""
    if author_type != "user":
        return 0.0
    if any(pattern.search(content) for pattern in _EVENT_PATTERNS):
        return 0.25
    return 0.0


def score_temporal_anchor(content: str) -> float:
    """Score the presence of concrete time anchors."""
    if any(pattern.search(content) for pattern in _TEMPORAL_PATTERNS):
        return 0.15
    return 0.0


def score_generic_guidance_penalty(content: str, *, author_type: str) -> float:
    """Penalty for generic assistant guidance that is related but not answer-bearing."""
    if author_type != "assistant":
        return 0.0

    penalty = 0.0
    if len(content) > 180:
        penalty += min((len(content) - 180) / 500.0, 0.2)
    if any(pattern.search(content) for pattern in _GUIDANCE_PATTERNS):
        penalty += 0.15
    if re.search(r"(^|\n)\s*(?:[-*]|\d+\.)\s+", content):
        penalty += 0.1
    return min(penalty, 0.35)
