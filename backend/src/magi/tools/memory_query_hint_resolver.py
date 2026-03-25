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

EVENT_RECALL_PATTERNS = (
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
    "聊到哪",
    "说到哪",
    "回忆",
    "总结一下我最近",
)

PREFERENCE_RECALL_PATTERNS = (
    "我喜欢什么",
    "我偏好什么",
    "我讨厌什么",
    "我的喜好",
    "我的偏好",
    "你记得我喜欢",
    "你记得我讨厌",
    "what do i like",
    "what do i dislike",
    "what is my preference",
    "what are my preferences",
    "do you remember what i like",
)

PROFILE_FACT_PATTERNS = (
    "我的默认",
    "我的设置",
    "我的工作目录",
    "我的默认工作目录",
    "我的常用",
    "我的语言设置",
    "what is my default",
    "what is my setting",
    "what are my settings",
    "what workspace do i",
    "what is my workspace",
)

RELATIONSHIP_RECALL_PATTERNS = (
    "你记得我们",
    "我们之前约定",
    "我们约定了什么",
    "我们之前说过",
    "我们之前聊过",
    "what did we agree",
    "do you remember we",
    "what did we discuss about",
)


class MemoryQueryHintResolver:
    """Resolve explicit memory-query hints without extra LLM work."""

    def should_route_explicitly(self, user_message: str) -> bool:
        text = str(user_message or "").strip()
        if not text:
            return False
        lowered = text.lower()
        return self._infer_recall_intent(lowered) not in {None, "workflow_reuse"}

    def resolve(self, user_message: str) -> dict[str, Any]:
        text = str(user_message or "").strip()
        lowered = text.lower()
        hint: dict[str, Any] = {"query": text}
        recall_intent = self._infer_recall_intent(lowered)
        if recall_intent:
            hint["recall_intent"] = recall_intent
        sources = self._infer_sources(lowered, recall_intent)
        if sources:
            hint["sources"] = sources
        query_mode = self._infer_query_mode(lowered)
        if query_mode:
            hint["query_mode"] = query_mode
        time_range = self._infer_time_range(lowered)
        if time_range is not None:
            hint["time_range"] = time_range
        return hint

    def _infer_recall_intent(self, lowered: str) -> Optional[str]:
        if any(hint in lowered for hint in WORKFLOW_REUSE_HINTS) and any(noun in lowered for noun in WORKFLOW_NOUNS):
            return "workflow_reuse"
        if any(pattern in lowered for pattern in PREFERENCE_RECALL_PATTERNS):
            return "preference_recall"
        if any(pattern in lowered for pattern in PROFILE_FACT_PATTERNS):
            return "profile_fact_recall"
        if any(pattern in lowered for pattern in RELATIONSHIP_RECALL_PATTERNS):
            return "relationship_recall"
        if any(pattern in lowered for pattern in EVENT_RECALL_PATTERNS):
            return "event_recall"
        return None

    def _infer_sources(self, lowered: str, recall_intent: Optional[str]) -> list[str]:
        if recall_intent == "preference_recall":
            return ["profile", "chat"]
        if recall_intent == "profile_fact_recall":
            return ["profile", "settings"]
        if recall_intent == "relationship_recall":
            return ["chat", "relationship"]
        if recall_intent == "event_recall":
            if any(term in lowered for term in ["chat", "conversation", "discuss", "聊", "聊天", "对话"]):
                return ["chat"]
            if any(term in lowered for term in ["browse", "browsing", "visited", "watched", "read", "浏览", "看了", "看过", "读过"]):
                return ["timeline"]
            if any(term in lowered for term in ["how did i", "经验", "怎么做", "上次怎么", "之前怎么"]):
                return ["worker"]
        return []

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
