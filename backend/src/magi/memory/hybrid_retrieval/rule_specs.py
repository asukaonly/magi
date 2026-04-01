"""Centralized rule specs for hybrid retrieval query heuristics."""

from __future__ import annotations

import re
from typing import Sequence

from .models import SemanticConstraint

# Layer routing keywords removed — routing is now handled entirely by the
# LLM intent decider, with a simple default fallback (L1 primary + L2
# fallback) when the LLM is unavailable.  Keyword-based routing suffered
# from semantic ambiguity (e.g. "画像" matching L2 even for L1 queries).

SOURCE_DOMAIN_SIGNAL_SPECS: list[tuple[list[str], list[str], list[str]]] = [
    (["浏览", "browsing", "网页", "webpage", "browser"], ["chrome_history"], ["external_activity"]),
    (["聊天", "对话", "chat", "conversation"], ["chat"], ["user_authored"]),
    (["终端", "terminal", "git", "命令行", "command"], ["terminal", "git"], ["external_activity"]),
    (["日记", "笔记", "journal", "note", "diary"], ["journal", "note"], ["user_authored"]),
    (["日历", "开会", "会议", "calendar", "meeting"], ["calendar"], ["external_activity"]),
    (["音乐", "听了", "music", "listened"], ["music"], ["external_activity"]),
]

CREATOR_KEYWORDS = ("up主", "up", "博主", "youtuber", "主播", "creator", "频道", "channel")
PLACE_KEYWORDS = ("咖啡馆", "餐厅", "店", "饭馆", "cafe", "restaurant", "shop")
TOPIC_KEYWORDS = ("题材", "主题", "topic")
SOFTWARE_KEYWORDS = ("软件", "网站", "app", "平台", "b站", "bilibili", "youtube")
PERSON_KEYWORDS = ("谁", "人", "person")

LIST_QUERY_KEYWORDS = ("哪些", "什么", "谁", "哪几个", "which", "what")
NEGATIVE_POLARITY_KEYWORDS = ("讨厌", "不喜欢", "dislike", "hate")
POSITIVE_POLARITY_KEYWORDS = ("喜欢", "偏好", "关注", "常看", "love", "like", "prefer")

ENTITY_SURFACE_SPECS: list[tuple[tuple[str, ...], str]] = [
    (("B站", "b站", "bilibili"), "B站"),
    (("youtube", "油管"), "YouTube"),
]

CATEGORY_FACET_MAP = {
    "咖啡馆": "coffee_shop",
    "咖啡店": "coffee_shop",
    "餐厅": "restaurant",
    "饭馆": "restaurant",
}

_BOOLEAN_TRAILING_PATTERN = re.compile(r"(?<!什)(吗|么)\s*[?？]?\s*$")
_TOPIC_PRIMARY_PATTERNS = (
    re.compile(r"(什么|哪些|哪种|哪类).*(题材|主题|topic)", re.IGNORECASE),
    re.compile(r"(题材|主题|topic).*(是什么|是啥|有哪些|有哪|是什么样)", re.IGNORECASE),
)
_CREATOR_PRIMARY_PATTERNS = (
    re.compile(r"(哪些|什么|谁|哪几个).*(up主|主播|博主|youtuber|creator|频道|channel)", re.IGNORECASE),
    re.compile(r"(up主|主播|博主|youtuber|creator|频道|channel).*(是谁|有哪些|有什么)", re.IGNORECASE),
)
_PLACE_PRIMARY_PATTERNS = (
    re.compile(r"(什么|哪些|哪家|哪几个).*(咖啡馆|餐厅|店|饭馆|cafe|restaurant|shop)", re.IGNORECASE),
    re.compile(r"(咖啡馆|餐厅|店|饭馆|cafe|restaurant|shop).*(是哪|有哪些|有什么)", re.IGNORECASE),
)
_SOFTWARE_PRIMARY_PATTERNS = (
    re.compile(r"(喜欢|常用|用).*(软件|网站|app|平台|b站|bilibili|youtube).*(吗|么|是否|是不是)?", re.IGNORECASE),
)
_BILIBILI_USAGE_PATTERN = re.compile(r"用\s*(B站|b站|bilibili)\s*(?:的时候)?", re.IGNORECASE)
_BILIBILI_TIME_PATTERN = re.compile(r"在\s*(B站|b站|bilibili)\s*的时候", re.IGNORECASE)
_YOUTUBE_USAGE_PATTERN = re.compile(r"用\s*(youtube|油管)\s*(?:的时候)?", re.IGNORECASE)
_YOUTUBE_TIME_PATTERN = re.compile(r"(?:在|用)\s*(youtube|油管)\s*的时候", re.IGNORECASE)
_INTERACTION_LOCATION_PATTERN = re.compile(r"在([\u4e00-\u9fffA-Za-z]{2,12})的时候喜欢去")
_TARGET_LOCATION_PATTERN = re.compile(r"在([\u4e00-\u9fffA-Za-z]{2,12})喜欢去")


def contains_any(text: str, tokens: Sequence[str]) -> bool:
    """Return whether the text contains any token."""
    return any(token in text for token in tokens)


def extract_answer_object_mentions(query: str) -> list[str]:
    """Extract explicit mentions that likely denote the answer object itself."""
    query_lower = query.lower()
    mentions: list[str] = []
    if any(pattern.search(query_lower) for pattern in _TOPIC_PRIMARY_PATTERNS):
        mentions.extend([token for token in TOPIC_KEYWORDS if token in query_lower or token in query])
    elif any(pattern.search(query_lower) for pattern in _CREATOR_PRIMARY_PATTERNS):
        mentions.extend([token for token in CREATOR_KEYWORDS if token in query_lower or token in query])
    elif any(pattern.search(query_lower) for pattern in _PLACE_PRIMARY_PATTERNS):
        mentions.extend([token for token in PLACE_KEYWORDS if token in query_lower or token in query])
    elif any(pattern.search(query_lower) for pattern in _SOFTWARE_PRIMARY_PATTERNS):
        mentions.extend([token for token in SOFTWARE_KEYWORDS if token in query_lower or token in query])

    deduped: list[str] = []
    for mention in mentions:
        if mention not in deduped:
            deduped.append(mention)
    return deduped


def _answer_kind_from_mentions(mentions: Sequence[str]) -> str | None:
    if any(mention in CREATOR_KEYWORDS for mention in mentions):
        return "creator"
    if any(mention in PLACE_KEYWORDS for mention in mentions):
        return "place"
    if any(mention in TOPIC_KEYWORDS for mention in mentions):
        return "topic"
    if any(mention in SOFTWARE_KEYWORDS for mention in mentions):
        return "software"
    if any(mention in PERSON_KEYWORDS for mention in mentions):
        return "person"
    return None


def infer_answer_kind(query_lower: str) -> str:
    """Infer the answer object kind from a normalized query string."""
    query_lower = query_lower.lower()
    answer_object_kind = _answer_kind_from_mentions(extract_answer_object_mentions(query_lower))
    if answer_object_kind is not None:
        return answer_object_kind
    if any(pattern.search(query_lower) for pattern in _TOPIC_PRIMARY_PATTERNS):
        return "topic"
    if any(pattern.search(query_lower) for pattern in _CREATOR_PRIMARY_PATTERNS):
        return "creator"
    if any(pattern.search(query_lower) for pattern in _PLACE_PRIMARY_PATTERNS):
        return "place"
    if any(pattern.search(query_lower) for pattern in _SOFTWARE_PRIMARY_PATTERNS):
        return "software"
    if contains_any(query_lower, CREATOR_KEYWORDS):
        return "creator"
    if contains_any(query_lower, PLACE_KEYWORDS):
        return "place"
    if contains_any(query_lower, TOPIC_KEYWORDS):
        return "topic"
    if contains_any(query_lower, SOFTWARE_KEYWORDS):
        return "software"
    if contains_any(query_lower, PERSON_KEYWORDS):
        return "person"
    return "unknown"


def infer_answer_shape(query_lower: str) -> str:
    """Infer whether the query expects a list, single answer, or boolean."""
    query_lower = query_lower.lower()
    if "是否" in query_lower or "是不是" in query_lower:
        return "boolean"
    if _BOOLEAN_TRAILING_PATTERN.search(query_lower):
        return "boolean"
    if contains_any(query_lower, LIST_QUERY_KEYWORDS):
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


def extract_entities(query: str) -> list[str]:
    """Extract high-confidence entity surface forms for common software/platform names."""
    query_lower = query.lower()
    entities: list[str] = []
    for aliases, entity_surface in ENTITY_SURFACE_SPECS:
        if any(alias in query_lower or alias in query for alias in aliases):
            entities.append(entity_surface)
    return entities


def infer_source_domain_filters(query: str) -> tuple[list[str] | None, list[str] | None]:
    """Infer source and domain filters from query text."""
    query_lower = query.lower()
    for keywords, sources, domains in SOURCE_DOMAIN_SIGNAL_SPECS:
        if contains_any(query_lower, keywords):
            return sources, domains
    return None, None


def extract_platform_constraint(query: str, *, answer_kind: str) -> SemanticConstraint | None:
    """Extract a platform constraint when the query contains platform hints."""
    query_lower = query.lower()
    if answer_kind == "software":
        return None
    if _BILIBILI_USAGE_PATTERN.search(query) or _BILIBILI_TIME_PATTERN.search(query):
        return SemanticConstraint(scope="interaction", facet="platform", raw_value="b站")
    if _YOUTUBE_USAGE_PATTERN.search(query) or _YOUTUBE_TIME_PATTERN.search(query):
        return SemanticConstraint(scope="interaction", facet="platform", raw_value="youtube")
    if "b站" in query_lower or "bilibili" in query_lower:
        return SemanticConstraint(scope="target", facet="platform", raw_value="b站")
    if "youtube" in query_lower or "油管" in query_lower:
        return SemanticConstraint(scope="target", facet="platform", raw_value="youtube")
    return None


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


def extract_category_constraint(query: str) -> SemanticConstraint | None:
    """Extract a category facet constraint from the query."""
    for label, facet_value in CATEGORY_FACET_MAP.items():
        if label in query:
            return SemanticConstraint(
                scope="target",
                facet="category",
                raw_value=label,
                resolved_facet_value=facet_value,
            )
    return None


def infer_semantic_constraints(query: str, *, answer_kind: str) -> list[SemanticConstraint]:
    """Infer structured semantic constraints from query text."""
    constraints: list[SemanticConstraint] = []
    platform_constraint = extract_platform_constraint(query, answer_kind=answer_kind)
    if platform_constraint is not None:
        constraints.append(platform_constraint)

    location_constraint = extract_location_constraint(query)
    if location_constraint is not None:
        constraints.append(location_constraint)

    category_constraint = extract_category_constraint(query)
    if category_constraint is not None:
        constraints.append(category_constraint)

    return constraints
