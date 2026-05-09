"""Memory-query routing guidance for context decisions."""

from __future__ import annotations

from typing import Any, Optional

from .models import ContextDecision, MemoryGuidance

MEMORY_RETRIEVAL_TRIGGERS_BY_CATEGORY: dict[str, list[str]] = {
    "personal_recall": [
        "what did i", "what was i", "what have i",
        "do you remember", "remember when", "i remember",
        "we agreed", "we promised", "you promised",
        "我记得", "记得", "约定", "答应",
    ],
    "preference": [
        "i like", "i prefer", "my preference", "my favorite",
        "my default", "my settings",
        "我喜欢", "我爱", "我讨厌", "偏好", "默认",
    ],
    "temporal_recall": [
        "yesterday", "last week", "last month", "recently",
        "last time i", "the other day",
        "最近", "刚才", "刚刚", "昨天", "上周", "上个月",
        "那时候", "三个月前", "之前",
    ],
    "activity_history": [
        "browsing", "browse", "visited", "watched", "read",
        "my history", "my activity", "my notes", "my chat",
        "浏览", "拍",
    ],
    "entity_recall": [
        "who is", "who was", "where does", "where did",
        "是谁", "住在", "认识",
    ],
    "media_asset": [
        "photo", "picture", "image of",
        "照片", "图片",
    ],
}

_ENTITY_RECALL_SUPPRESS_CATEGORIES: frozenset[str] = frozenset({
    "code_execution", "file_operation", "planning",
    "code_review", "debugging",
})

MEMORY_RETRIEVAL_TRIGGERS: list[str] = [
    trigger
    for triggers in MEMORY_RETRIEVAL_TRIGGERS_BY_CATEGORY.values()
    for trigger in triggers
]


def evaluate_memory_need(
    user_message: str,
    context: dict[str, Any],
    *,
    task_category: str | None = None,
) -> Optional[MemoryGuidance]:
    """Return memory guidance when a request looks like recall or preference lookup."""
    message_lower = user_message.lower()

    for category, triggers in MEMORY_RETRIEVAL_TRIGGERS_BY_CATEGORY.items():
        if category == "entity_recall" and task_category in _ENTITY_RECALL_SUPPRESS_CATEGORIES:
            continue
        if any(trigger in message_lower for trigger in triggers):
            return MemoryGuidance(recommended=True, route="explicit_query")

    return None


def apply_memory_guidance(
    *,
    user_message: str,
    context: Optional[dict[str, Any]],
    decision: ContextDecision,
    available_tools: list[dict[str, Any]],
    max_tools: int,
    task_category: str | None = None,
) -> ContextDecision:
    guidance = evaluate_memory_need(
        user_message, context or {}, task_category=task_category,
    )
    if guidance is None or not guidance.recommended:
        return decision
    available_names = {str(item.get("name", "")).strip() for item in available_tools}
    if "memory_query" not in available_names:
        return decision
    tools = list(decision.tools)
    tools = [tool for tool in tools if tool != "memory_query"]
    tools.insert(0, "memory_query")
    return ContextDecision(
        intent=decision.intent,
        tools=tools[:max_tools],
        thinking_depth=decision.thinking_depth,
        reasoning=decision.reasoning,
        orchestration_strategy=decision.orchestration_strategy,
        memory_layer=decision.memory_layer,
        memory_route=guidance.route,
    )


__all__ = [
    "MEMORY_RETRIEVAL_TRIGGERS",
    "MEMORY_RETRIEVAL_TRIGGERS_BY_CATEGORY",
    "apply_memory_guidance",
    "evaluate_memory_need",
]
