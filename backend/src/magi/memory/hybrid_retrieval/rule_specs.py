"""Centralized rule specs for hybrid retrieval query heuristics."""

from __future__ import annotations

import re
from typing import Sequence

from .models import SemanticConstraint

# Layer routing keywords removed — routing is now handled entirely by the
# LLM intent decider, with a simple default fallback (L1 primary + L2
# fallback) when the LLM is unavailable.  Keyword-based routing suffered
# from semantic ambiguity (e.g. "画像" matching L2 even for L1 queries).

# Answer-kind keyword tables removed — answer_kind inference is handled by
# the LLM semantic frame.  Keyword-based inference suffered from the same
# "whack-a-mole" coverage problem as routing keywords.

SOURCE_DOMAIN_SIGNAL_SPECS: list[tuple[list[str], list[str], list[str]]] = [
    (["浏览", "browsing", "网页", "webpage", "browser"], ["chrome_history"], ["external_activity"]),
    (["聊天", "对话", "chat", "conversation"], ["chat"], ["user_authored"]),
    (["终端", "terminal", "git", "命令行", "command"], ["terminal", "git"], ["external_activity"]),
    (["日记", "笔记", "journal", "note", "diary"], ["journal", "note"], ["user_authored"]),
    (["日历", "开会", "会议", "calendar", "meeting"], ["calendar"], ["external_activity"]),
    (["音乐", "听了", "music", "listened"], ["music"], ["external_activity"]),
]

NEGATIVE_POLARITY_KEYWORDS = ("讨厌", "不喜欢", "dislike", "hate")
POSITIVE_POLARITY_KEYWORDS = ("喜欢", "偏好", "关注", "常看", "love", "like", "prefer")

_BOOLEAN_TRAILING_PATTERN = re.compile(r"(?<!什)(吗|么)\s*[?？]?\s*$")
_INTERACTION_LOCATION_PATTERN = re.compile(r"在([\u4e00-\u9fffA-Za-z]{2,12})的时候喜欢去")
_TARGET_LOCATION_PATTERN = re.compile(r"在([\u4e00-\u9fffA-Za-z]{2,12})喜欢去")


def contains_any(text: str, tokens: Sequence[str]) -> bool:
    """Return whether the text contains any token."""
    return any(token in text for token in tokens)


# "什么" must not match inside "为什么" (why vs. what).
_LIST_QUERY_PATTERN = re.compile(
    r"哪些|(?<!为)什么|谁|哪几个|which|what", re.IGNORECASE,
)


def infer_answer_shape(query_lower: str) -> str:
    """Infer whether the query expects a list, single answer, or boolean."""
    query_lower = query_lower.lower()
    if "是否" in query_lower or "是不是" in query_lower:
        return "boolean"
    if _BOOLEAN_TRAILING_PATTERN.search(query_lower):
        return "boolean"
    if _LIST_QUERY_PATTERN.search(query_lower):
        return "list"
    return "single"


def infer_polarity(query_lower: str) -> str:
    """Infer query polarity from lexical cues."""
    query_lower = query_lower.lower()
    if contains_any(query_lower, NEGATIVE_POLARITY_KEYWORDS):
        return "negative"
    if contains_any(query_lower, POSITIVE_POLARITY_KEYWORDS):
        return "positive"
    return "any"


def infer_source_domain_filters(query: str) -> tuple[list[str] | None, list[str] | None]:
    """Infer source and domain filters from query text."""
    query_lower = query.lower()
    for keywords, sources, domains in SOURCE_DOMAIN_SIGNAL_SPECS:
        if contains_any(query_lower, keywords):
            return sources, domains
    return None, None


def extract_location_constraint(query: str) -> SemanticConstraint | None:
    """Extract a location constraint from the query."""
    interaction_location_match = _INTERACTION_LOCATION_PATTERN.search(query)
    if interaction_location_match:
        return SemanticConstraint(
            scope="interaction",
            facet="located_in",
            raw_value=interaction_location_match.group(1),
        )

    target_location_match = _TARGET_LOCATION_PATTERN.search(query)
    if target_location_match:
        return SemanticConstraint(
            scope="target",
            facet="located_in",
            raw_value=target_location_match.group(1),
        )
    return None


def infer_semantic_constraints(query: str) -> list[SemanticConstraint]:
    """Infer structured semantic constraints from query text."""
    constraints: list[SemanticConstraint] = []
    location_constraint = extract_location_constraint(query)
    if location_constraint is not None:
        constraints.append(location_constraint)
    return constraints
