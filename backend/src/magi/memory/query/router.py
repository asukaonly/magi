"""Intent router for building event-centric memory retrieval plans."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List


DETAIL_KEYWORDS = [
    "what did i do",
    "what was i doing",
    "哪些事",
    "做了什么",
    "明细",
    "列出来",
]
SUMMARY_KEYWORDS = [
    "summarize",
    "summary",
    "review",
    "trend",
    "overview",
    "总结",
    "回顾",
    "梳理",
    "趋势",
]
EXPERIENCE_KEYWORDS = [
    "how did i solve",
    "worked before",
    "previously handled",
    "之前怎么解决",
    "之前成功",
]

EXPLICIT_SOURCE_RULES = {
    "chrome_history": ["browse", "browsing", "website", "web", "search", "docs", "浏览", "网页", "搜索"],
    "git": ["git", "commit", "branch", "repo", "pull request", "pr", "提交", "代码变更"],
    "terminal": ["terminal", "command", "shell", "bash", "script", "终端", "命令"],
    "chat": ["chat", "talked", "discussed", "said", "conversation", "聊天", "对话", "说过", "聊过"],
}

TOPIC_SOURCE_DEFAULTS = {
    "programming": ["git", "terminal", "chrome_history", "chat"],
    "research": ["chrome_history", "chat", "terminal"],
}

TOPIC_KEYWORDS = {
    "programming": [
        "programming",
        "coding",
        "development",
        "bug",
        "repo",
        "implementation",
        "编程",
        "开发",
        "代码",
        "实现",
    ],
    "research": [
        "research",
        "study",
        "learning",
        "docs",
        "调研",
        "学习",
        "资料",
        "文档",
    ],
}


@dataclass
class RoutingPlan:
    """Execution-ready memory retrieval plan."""

    layers: List[str]
    query_mode: str
    source_filters: List[str]
    time_range: Dict[str, Any]
    topic_query: str
    confidence: float
    reasoning: str

    @property
    def primary_layer(self) -> str:
        return self.layers[0] if self.layers else "L1"

    @property
    def secondary_layers(self) -> List[str]:
        return self.layers[1:]


class IntentRouter:
    """Lightweight rule-based intent analyzer for event-centric retrieval."""

    def analyze(self, query: str, time_range: Dict[str, Any]) -> RoutingPlan:
        query_lower = query.lower().strip()
        query_mode = self._infer_query_mode(query_lower)
        topic_query = self._infer_topic_query(query_lower)
        source_filters = self._infer_source_filters(query_lower, topic_query)
        layers = self._infer_layers(query_lower=query_lower, query_mode=query_mode, time_range=time_range)
        confidence = self._estimate_confidence(query_mode=query_mode, source_filters=source_filters, time_range=time_range)
        reasoning = self._build_reasoning(
            layers=layers,
            query_mode=query_mode,
            source_filters=source_filters,
            time_range=time_range,
            topic_query=topic_query,
            confidence=confidence,
        )
        return RoutingPlan(
            layers=layers,
            query_mode=query_mode,
            source_filters=source_filters,
            time_range=dict(time_range),
            topic_query=topic_query,
            confidence=confidence,
            reasoning=reasoning,
        )

    async def execute(
        self,
        plan: RoutingPlan,
        request: "MemoryQueryRequest",
        layer_handlers: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        layers_to_query = list(dict.fromkeys(plan.layers))
        tasks = []
        for layer in layers_to_query:
            handler = layer_handlers.get(layer)
            if handler:
                tasks.append(self._query_layer(layer, request, plan, handler))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        merged: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        for result in results:
            if isinstance(result, Exception):
                continue
            if isinstance(result, list):
                for item in result:
                    item_id = str(item.get("id") or item.get("event_id") or "")
                    if item_id and item_id in seen_ids:
                        continue
                    if item_id:
                        seen_ids.add(item_id)
                    merged.append(item)

        return merged

    async def _query_layer(
        self,
        layer: str,
        request: "MemoryQueryRequest",
        plan: RoutingPlan,
        handler: Any,
    ) -> List[Dict[str, Any]]:
        try:
            if hasattr(handler, "query"):
                try:
                    return await handler.query(request, plan)
                except TypeError:
                    return await handler.query(request)
            return []
        except Exception:
            return []

    def _infer_query_mode(self, query_lower: str) -> str:
        if any(keyword in query_lower for keyword in EXPERIENCE_KEYWORDS):
            return "experience"
        if any(keyword in query_lower for keyword in SUMMARY_KEYWORDS):
            return "summary"
        if any(keyword in query_lower for keyword in DETAIL_KEYWORDS):
            return "detail"
        if any(keyword in query_lower for keyword in ["yesterday", "昨天", "today", "今天"]):
            return "detail"
        return "detail"

    def _infer_topic_query(self, query_lower: str) -> str:
        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(keyword in query_lower for keyword in keywords):
                return topic
        return query_lower

    def _infer_source_filters(self, query_lower: str, topic_query: str) -> List[str]:
        sources: List[str] = []
        for source, keywords in EXPLICIT_SOURCE_RULES.items():
            if any(keyword in query_lower for keyword in keywords):
                sources.append(source)

        topic_defaults = TOPIC_SOURCE_DEFAULTS.get(topic_query, [])
        for source in topic_defaults:
            if source not in sources:
                sources.append(source)
        return sources

    def _infer_layers(self, *, query_lower: str, query_mode: str, time_range: Dict[str, Any]) -> List[str]:
        relative = str(time_range.get("relative", "")).strip()
        if any(keyword in query_lower for keyword in ["scattered", "related", "similar", "thoughts", "模糊", "相关", "零散"]):
            layers = ["L3", "L1"]
        elif query_mode == "summary":
            layers = ["L4", "L1"]
        elif query_mode == "experience":
            layers = ["L5", "L1"]
        else:
            layers = ["L1"]
        if relative and any(token in relative for token in ["30d", "90d", "180d", "1m", "6m"]):
            if "L4" not in layers:
                layers.insert(0, "L4")
        return layers

    def _estimate_confidence(
        self,
        *,
        query_mode: str,
        source_filters: List[str],
        time_range: Dict[str, Any],
    ) -> float:
        score = 0.45
        if source_filters:
            score += 0.2
        if query_mode in {"summary", "experience"}:
            score += 0.1
        if time_range:
            score += 0.1
        return min(0.95, score)

    def _build_reasoning(
        self,
        *,
        layers: List[str],
        query_mode: str,
        source_filters: List[str],
        time_range: Dict[str, Any],
        topic_query: str,
        confidence: float,
    ) -> str:
        return (
            f"layers={layers}; query_mode={query_mode}; source_filters={source_filters}; "
            f"time_range={time_range}; topic_query={topic_query}; confidence={confidence:.2f}"
        )
