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

# Consonants that commonly appear doubled in base English words (call, miss, stuff)
# and should NOT be de-duplicated when stripping -ed/-ing suffixes.
_NATURAL_DOUBLE_CONSONANTS = frozenset("lsf")


def _normalize_query_token(token: str) -> str:
    """Apply lightweight normalization so simple inflections still match.

    NOTE: this stemmer intentionally re-attaches a silent ``e`` for stems
    ending in ``c/g/s/z/v`` (placed → place, changed → change). That makes
    it suitable for *token-equality* reranking where we compare against the
    indexed surface form. ``fts_utils._stem_english_token`` does the same
    suffix stripping but stops there because FTS5 prefix wildcards
    (``plac*``) handle the silent-``e`` case at query time.

    The two stemmers must stay behaviorally close on the suffix-stripping
    side; if you change one, audit the other or you will see retrieval
    recall and rerank scoring drift apart (this is exactly the regression
    that motivated the M3 finding).
    """
    normalized = str(token or "").strip().lower()
    if len(normalized) <= 3:
        return normalized
    if normalized.endswith("ied") and len(normalized) > 4:
        return f"{normalized[:-3]}y"
    if normalized.endswith("ed") and len(normalized) > 4:
        base = normalized[:-2]
        # Doubled consonant from suffixing: stopped → stopp → stop
        if (
            len(base) >= 2
            and base[-1] == base[-2]
            and base[-1] not in "aeiou"
            and base[-1] not in _NATURAL_DOUBLE_CONSONANTS
        ):
            return base[:-1]
        # Vowel-ending base: the 'e' is part of the stem (freed → free)
        if base and base[-1] in "aeiou":
            return normalized[:-1]
        # Consonants that commonly precede silent-e in English stems:
        # serviced → service, placed → place, changed → change, loved → love
        if base and base[-1] in "cgszv":
            return base + "e"
        return base
    if normalized.endswith("ing") and len(normalized) > 5:
        stem = normalized[:-3]
        # Doubled consonant from suffixing: running → runn → run
        if (
            len(stem) >= 2
            and stem[-1] == stem[-2]
            and stem[-1] not in "aeiou"
            and stem[-1] not in _NATURAL_DOUBLE_CONSONANTS
        ):
            return stem[:-1]
        if stem.endswith(("v", "c", "g")):
            return f"{stem}e"
        return stem
    if normalized.endswith("s") and len(normalized) > 4 and not normalized.endswith("ss"):
        return normalized[:-1]
    return normalized


_CJK_RANGE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff]")
# Split text into CJK segments vs Latin/numeric segments for separate tokenization.
_SEGMENT_RE = re.compile(
    r"([\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff]+)",
)


def _jieba_cut(text: str) -> list[str]:
    """Segment CJK text with jieba; fall back to character-level split."""
    try:
        import jieba
        return [w for w in jieba.cut_for_search(text) if w.strip()]
    except ImportError:
        return list(text)


def extract_query_tokens(text: str) -> list[str]:
    """Extract normalized ranking tokens from a query or event body.

    Latin/numeric tokens are stemmed via ``_normalize_query_token``.
    CJK text is segmented with jieba (falls back to character unigrams).
    """
    lowered = str(text or "").lower()
    result: list[str] = []
    for segment in _SEGMENT_RE.split(lowered):
        if not segment:
            continue
        if _CJK_RANGE.search(segment):
            # CJK segment → jieba word-level tokenization
            for word in _jieba_cut(segment):
                word = word.strip()
                if word:
                    result.append(word)
        else:
            # Latin/numeric segment → regex + stemmer
            for token in re.findall(r"[a-z0-9]+", segment):
                normalized = _normalize_query_token(token)
                if normalized and normalized not in _RERANK_STOP_WORDS:
                    result.append(normalized)
    return result


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


def has_temporal_anchor(content: str) -> bool:
    """Check whether content contains concrete time anchors."""
    return any(pattern.search(content) for pattern in _TEMPORAL_PATTERNS)


# Richer regex for extracting human-readable event-date mentions from content.
_EVENT_DATE_RE = re.compile(
    r"(?:on\s+)?"
    r"(?:"
    # "March 3rd" / "January 15, 2024"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?"
    r")"
    r"|"
    # "3/15" / "03-15-2024"
    r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?"
    r"|"
    # "last Monday" / "this Friday"
    r"(?:last|this)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"|"
    # "3 days ago" / "two weeks ago"
    r"(?:\d+\s+(?:days?|weeks?|months?|years?)\s+ago)"
    r"|"
    # "yesterday" / "last week" / "last night"
    r"(?:yesterday|today|last\s+(?:week|month|year|night))",
    re.IGNORECASE,
)


def extract_event_dates(content: str) -> list[str]:
    """Extract human-readable date mentions from content text."""
    return [m.group(0).strip() for m in _EVENT_DATE_RE.finditer(str(content or ""))]
