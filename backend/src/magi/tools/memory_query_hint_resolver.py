"""Rule-based hint resolver for explicit memory_query usage."""

from __future__ import annotations

from typing import Any, Optional


WORKFLOW_REUSE_HINTS = (
    "按之前",
    "之前那套",
    "按惯例",
    "像之前一样",
    "same as before",
    "as usual",
    "usual workflow",
    "usual flow",
)

WORKFLOW_NOUNS = ("流程", "workflow", "flow", "惯例", "方式", "做法")


class MemoryQueryHintResolver:
    """Resolve explicit memory-query hints without extra LLM work."""

    def should_route_explicitly(self, user_message: str) -> bool:
        text = str(user_message or "").strip()
        if not text:
            return False
        lowered = text.lower()
        if any(hint in lowered for hint in WORKFLOW_REUSE_HINTS) and any(noun in lowered for noun in WORKFLOW_NOUNS):
            return False
        return self._looks_like_explicit_memory_query(lowered)

    def resolve(self, user_message: str) -> dict[str, Any]:
        text = str(user_message or "").strip()
        lowered = text.lower()
        hint: dict[str, Any] = {"query": text}
        source = self._infer_source(lowered)
        if source:
            hint["sources"] = [source]
        query_mode = self._infer_query_mode(lowered)
        if query_mode:
            hint["query_mode"] = query_mode
        time_range = self._infer_time_range(lowered)
        if time_range is not None:
            hint["time_range"] = time_range
        return hint

    def _looks_like_explicit_memory_query(self, lowered: str) -> bool:
        explicit_patterns = [
            "what did i",
            "what have i",
            "what was i",
            "did i",
            "have i",
            "what did we discuss",
            "where did we leave off",
            "summarize my",
            "analyze my",
            "yesterday",
            "last week",
            "last month",
            "recently",
            "我昨天",
            "我最近",
            "我之前",
            "我看了什么",
            "我看过什么",
            "我浏览了什么",
            "我浏览过什么",
            "我们上次",
            "我们之前",
            "聊到哪",
            "说到哪",
            "回忆",
            "总结一下我最近",
        ]
        return any(pattern in lowered for pattern in explicit_patterns)

    def _infer_source(self, lowered: str) -> Optional[str]:
        if any(term in lowered for term in ["chat", "conversation", "discuss", "聊", "聊天", "对话"]):
            return "chat"
        if any(term in lowered for term in ["browse", "browsing", "visited", "watched", "read", "浏览", "看了", "看过", "读过"]):
            return "timeline"
        if any(term in lowered for term in ["how did i", "经验", "怎么做", "上次怎么", "之前怎么"]):
            return "worker"
        return None

    def _infer_query_mode(self, lowered: str) -> Optional[str]:
        if any(term in lowered for term in ["pattern", "summary", "summarize", "总结", "概括", "聊到哪", "说到哪"]):
            return "summary"
        if any(term in lowered for term in ["experience", "经验", "怎么做", "上次怎么", "之前怎么"]):
            return "experience"
        return "detail"

    def _infer_time_range(self, lowered: str) -> Optional[dict[str, Any]]:
        if "yesterday" in lowered or "昨天" in lowered:
            return {"relative": "1d"}
        if "last week" in lowered or "上周" in lowered:
            return {"relative": "7d"}
        if "last month" in lowered or "上个月" in lowered:
            return {"relative": "30d"}
        if "recently" in lowered or "最近" in lowered:
            return {"relative": "7d"}
        return None
