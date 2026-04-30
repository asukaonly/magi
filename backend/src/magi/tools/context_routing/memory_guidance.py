"""Memory-query routing guidance for context decisions."""

from __future__ import annotations

from typing import Any, Optional

from .models import ContextDecision, MemoryGuidance


MEMORY_RETRIEVAL_TRIGGERS = [
    "what did i", "what was i", "what have i",
    "do you remember", "remember when", "i remember",
    "i like", "i prefer", "my preference", "my favorite",
    "yesterday", "last week", "last month", "recently",
    "browsing", "browse", "visited", "watched", "read",
    "my history", "my activity", "my notes", "my chat",
    "my default", "my settings",
    "we agreed", "we promised", "you promised",
    "photo", "picture", "image of",
    "最近", "刚才", "刚刚", "昨天", "上周", "上个月",
    "浏览", "拍",
    "我喜欢", "我爱", "我讨厌", "偏好", "默认",
    "记得", "约定", "答应",
    "照片", "图片",
]


def evaluate_memory_need(user_message: str, context: dict[str, Any]) -> Optional[MemoryGuidance]:
    """Return memory guidance when a request looks like recall or preference lookup."""
    del context
    message_lower = user_message.lower()
    if not any(trigger in message_lower for trigger in MEMORY_RETRIEVAL_TRIGGERS):
        return None
    return MemoryGuidance(recommended=True, route="explicit_query")


def apply_memory_guidance(
    *,
    user_message: str,
    context: Optional[dict[str, Any]],
    decision: ContextDecision,
    available_tools: list[dict[str, Any]],
    max_tools: int,
) -> ContextDecision:
    guidance = evaluate_memory_need(user_message, context or {})
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
        deep_thinking=decision.deep_thinking,
        reasoning=decision.reasoning,
        orchestration_strategy=decision.orchestration_strategy,
        memory_layer=decision.memory_layer,
        memory_route=guidance.route,
    )


__all__ = [
    "MEMORY_RETRIEVAL_TRIGGERS",
    "apply_memory_guidance",
    "evaluate_memory_need",
]