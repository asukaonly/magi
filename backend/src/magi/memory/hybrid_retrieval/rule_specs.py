"""Centralized rule specs for hybrid retrieval query heuristics."""

from __future__ import annotations

import re
from typing import Sequence

from .models import SemanticConstraint

L2_SIGNAL_KEYWORDS = [
    "关系", "认识", "谁是", "谁", "人物", "联系人",
    "偏好", "喜好", "喜欢", "讨厌", "不喜欢", "画像", "倾向",
    "relationship", "who is", "who", "person", "contact",
    "preference", "preferences", "profile", "tendency",
    "like", "likes", "dislike", "dislikes",
]
L3_SIGNAL_KEYWORDS = [
    "总结", "回顾", "小结", "概要", "复盘",
    "summary", "review", "recap", "overview",
]
L4_SIGNAL_KEYWORDS = [
    "怎么做", "上次怎么", "经验", "技巧", "最佳实践", "方法", "策略",
    "how to", "best practice", "experience", "strategy", "technique",
]
L1_SIGNAL_KEYWORDS = [
    "浏览", "看了", "聊了", "发了", "搜了", "打开了", "访问了",
    "browsed", "viewed", "chatted", "searched", "opened", "visited",
]

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

_BOOLEAN_TRAILING_PATTERN = re.compile(r"(吗|么)\s*[?？]?\s*$")
_BILIBILI_USAGE_PATTERN = re.compile(r"用\s*(B站|b站|bilibili)\s*(?:的时候)?", re.IGNORECASE)
_BILIBILI_TIME_PATTERN = re.compile(r"在\s*(B站|b站|bilibili)\s*的时候", re.IGNORECASE)
_YOUTUBE_USAGE_PATTERN = re.compile(r"用\s*(youtube|油管)\s*(?:的时候)?", re.IGNORECASE)
_YOUTUBE_TIME_PATTERN = re.compile(r"(?:在|用)\s*(youtube|油管)\s*的时候", re.IGNORECASE)
_INTERACTION_LOCATION_PATTERN = re.compile(r"在([\u4e00-\u9fffA-Za-z]{2,12})的时候喜欢去")
_TARGET_LOCATION_PATTERN = re.compile(r"在([\u4e00-\u9fffA-Za-z]{2,12})喜欢去")


def contains_any(text: str, tokens: Sequence[str]) -> bool:
    """Return whether the text contains any token."""
    return any(token in text for token in tokens)


def infer_answer_kind(query_lower: str) -> str:
    """Infer the answer object kind from a normalized query string."""
    query_lower = query_lower.lower()
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


def infer_semantic_constraints(query: str, *, answer_kind: str) -> list[SemanticConstraint]:
    """Infer structured semantic constraints from query text."""
    query_lower = query.lower()
    constraints: list[SemanticConstraint] = []
    interaction_platform_value: str | None = None
    if answer_kind != "software":
        if _BILIBILI_USAGE_PATTERN.search(query) or _BILIBILI_TIME_PATTERN.search(query):
            interaction_platform_value = "b站"
        elif _YOUTUBE_USAGE_PATTERN.search(query) or _YOUTUBE_TIME_PATTERN.search(query):
            interaction_platform_value = "youtube"

    if interaction_platform_value is not None:
        constraints.append(
            SemanticConstraint(
                scope="interaction",
                facet="platform",
                raw_value=interaction_platform_value,
            )
        )
    elif answer_kind != "software" and ("b站" in query_lower or "bilibili" in query_lower):
        constraints.append(SemanticConstraint(scope="target", facet="platform", raw_value="b站"))
    elif answer_kind != "software" and ("youtube" in query_lower or "油管" in query_lower):
        constraints.append(SemanticConstraint(scope="target", facet="platform", raw_value="youtube"))

    interaction_location_match = _INTERACTION_LOCATION_PATTERN.search(query)
    if interaction_location_match:
        constraints.append(
            SemanticConstraint(
                scope="interaction",
                facet="located_in",
                raw_value=interaction_location_match.group(1),
            )
        )
    else:
        location_match = _TARGET_LOCATION_PATTERN.search(query)
        if location_match:
            constraints.append(
                SemanticConstraint(
                    scope="target",
                    facet="located_in",
                    raw_value=location_match.group(1),
                )
            )

    for label, facet_value in CATEGORY_FACET_MAP.items():
        if label in query:
            constraints.append(
                SemanticConstraint(
                    scope="target",
                    facet="category",
                    raw_value=label,
                    resolved_facet_value=facet_value,
                )
            )
            break
    return constraints
