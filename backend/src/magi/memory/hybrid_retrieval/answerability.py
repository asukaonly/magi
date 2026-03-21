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
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?\b",
        re.IGNORECASE,
    ),
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

_TEMPORAL_DISTANCE_PATTERNS = (
    re.compile(
        r"how many\s+(?:day|week|month|year)s?\s+before\s+(?P<anchor_b>.+?)\s+did\s+i\s+(?P<anchor_a>.+?)\??$",
        re.IGNORECASE,
    ),
    re.compile(
        r"how many\s+(?:day|week|month|year)s?\s+after\s+(?P<anchor_b>.+?)\s+did\s+i\s+(?P<anchor_a>.+?)\??$",
        re.IGNORECASE,
    ),
    re.compile(
        r"how long\s+had\s+i\s+been\s+(?P<anchor_a>.+?)\s+when\s+(?P<anchor_b>.+?)\??$",
        re.IGNORECASE,
    ),
)

_TEMPORAL_ANCHOR_NOISE = {
    "a",
    "an",
    "and",
    "after",
    "ago",
    "am",
    "at",
    "before",
    "been",
    "did",
    "do",
    "for",
    "had",
    "have",
    "how",
    "i",
    "in",
    "many",
    "my",
    "of",
    "on",
    "that",
    "the",
    "to",
    "was",
    "were",
    "when",
}

_EVENT_TYPE_HINTS = (
    "appointment",
    "birthday",
    "class",
    "conference",
    "course",
    "gift",
    "job",
    "meeting",
    "meetup",
    "orientation",
    "party",
    "presentation",
    "repair",
    "service",
    "trip",
    "webinar",
    "workshop",
)


def _normalize_query_token(token: str) -> str:
    """Apply lightweight normalization so simple inflections still match."""
    normalized = str(token or "").strip().lower()
    if len(normalized) <= 3:
        return normalized
    if normalized.endswith("ied") and len(normalized) > 4:
        return f"{normalized[:-3]}y"
    if normalized.endswith("ed") and len(normalized) > 4:
        if normalized[:-1].endswith("e"):
            return normalized[:-1]
        return normalized[:-2]
    if normalized.endswith("ing") and len(normalized) > 5:
        stem = normalized[:-3]
        if stem.endswith(("v", "c", "g")):
            return f"{stem}e"
        return stem
    if normalized.endswith("s") and len(normalized) > 4 and not normalized.endswith("ss"):
        return normalized[:-1]
    return normalized


def extract_query_tokens(text: str) -> list[str]:
    """Extract normalized ranking tokens from a query or event body."""
    lowered = str(text or "").lower()
    raw_tokens = re.findall(r"[a-z0-9]+", lowered)
    return [
        normalized
        for token in raw_tokens
        for normalized in [_normalize_query_token(token)]
        if len(normalized) >= 2 and normalized not in _RERANK_STOP_WORDS
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


def extract_comparison_spans(text: str) -> list[str]:
    """Extract lightweight unquoted comparison candidates from a query."""
    spans: list[str] = []
    query = str(text or "")
    pattern = re.compile(
        r"(?:^|[,:;]|\bbetween\b)\s*(?:the\s+)?([a-z][a-z0-9]*(?:\s+[a-z0-9]+){0,3})\s+or\s+"
        r"(?:the\s+)?([a-z][a-z0-9]*(?:\s+[a-z0-9]+){0,3})(?=$|[?.!,])",
        re.IGNORECASE,
    )
    for match in pattern.finditer(query):
        for group in (1, 2):
            normalized = " ".join(extract_query_tokens(match.group(group)))
            if normalized and normalized not in spans:
                spans.append(normalized)
    return spans


def _extract_surface_tokens(text: str) -> list[str]:
    """Extract lower-cased tokens while preserving readable surface forms."""
    return [token for token in re.findall(r"[a-z0-9]+", str(text or "").lower()) if token]


def _build_temporal_anchor_query(anchor_text: str) -> str:
    """Build a compact retrieval query for a temporal anchor phrase."""
    raw_anchor = str(anchor_text or "").strip()
    if not raw_anchor:
        return ""

    quoted_matches = re.findall(r"""["']([^"']{3,})["']""", raw_anchor)
    event_type = next((hint for hint in _EVENT_TYPE_HINTS if re.search(rf"\b{re.escape(hint)}\b", raw_anchor, re.IGNORECASE)), "")
    if quoted_matches:
        base = " ".join(_extract_surface_tokens(quoted_matches[0]))
        if event_type and event_type not in base.split():
            return f"{base} {event_type}".strip()
        return base

    tokens = [token for token in _extract_surface_tokens(raw_anchor) if token not in _TEMPORAL_ANCHOR_NOISE]
    deduped_tokens = list(dict.fromkeys(tokens))
    return " ".join(deduped_tokens[:4]).strip()


def extract_temporal_distance_queries(text: str) -> list[str]:
    """Extract anchor-specific backstop queries for temporal distance questions."""
    query = str(text or "").strip()
    if not query:
        return []

    for pattern in _TEMPORAL_DISTANCE_PATTERNS:
        match = pattern.search(query)
        if not match:
            continue
        candidate_queries: list[str] = []
        for key in ("anchor_a", "anchor_b"):
            anchor_query = _build_temporal_anchor_query(match.group(key))
            if anchor_query and anchor_query not in candidate_queries:
                candidate_queries.append(anchor_query)
        return candidate_queries
    return []


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
