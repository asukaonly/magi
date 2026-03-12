"""Intent router for determining which memory layer to query."""
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class RoutingPlan:
    """Routing plan for memory query execution."""
    primary_layer: str              # Main layer to query (L1-L5)
    secondary_layers: List[str]     # Fallback layers for parallel query
    confidence: float               # Prediction confidence (0-1)
    reasoning: str                  # Why this routing was chosen


# Layer routing keywords
LAYER_KEYWORDS = {
    "L1": ["几点", "哪天", "具体数值", "确切时间", "原始记录", "审计",
           "what time", "exactly", "when did", "specific"],
    "L2": ["关系", "关联", "谁和谁", "归属", "网络", "连接",
           "relation", "connected", "who is", "belongs to"],
    "L3": ["相关", "类似", "关于", "模糊", "零散", "继续之前",
           "related", "similar", "about", "scattered", "continue"],
    "L4": ["总结", "趋势", "变化", "过去", "回顾", "长期",
           "summarize", "trend", "change", "past", "review", "overview"],
    "L5": ["怎么处理", "之前成功", "异常", "失败原因", "方案",
           "how to handle", "worked before", "error", "failed", "approach"],
}


class IntentRouter:
    """Lightweight intent analyzer for memory layer routing."""

    def analyze(self, query: str, time_range: Dict[str, Any]) -> RoutingPlan:
        """
        Analyze query intent and determine routing plan.

        Args:
            query: User's query string
            time_range: Time range for the query

        Returns:
            RoutingPlan with primary/secondary layers and confidence.
        """
        query_lower = query.lower()
        scores: Dict[str, float] = {}

        # Score each layer based on keyword matches
        for layer, keywords in LAYER_KEYWORDS.items():
            score = sum(1.0 for kw in keywords if kw in query_lower)
            scores[layer] = score

        # Find primary layer (highest score)
        if max(scores.values()) == 0:
            # No keyword match, default to L3 (concept retrieval)
            primary = "L3"
            confidence = 0.3
        else:
            primary = max(scores, key=scores.get)
            total_matches = sum(scores.values())
            confidence = min(0.9, scores[primary] / max(total_matches, 1) + 0.4)

        # Determine secondary layers
        secondary: List[str] = []
        sorted_layers = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        for layer, score in sorted_layers[1:3]:  # Take next 2 candidates
            if score > 0:
                secondary.append(layer)

        # Add time-based adjustment
        relative = time_range.get("relative", "")
        if relative and any(x in relative for x in ["30d", "90d", "180d", "1M", "6M"]):
            # Long time range suggests L4 (trends)
            if primary != "L4":
                secondary.append("L4")

        reasoning = f"Primary: {primary} (score: {scores[primary]}), " \
                    f"secondary: {secondary}, confidence: {confidence:.2f}"

        return RoutingPlan(
            primary_layer=primary,
            secondary_layers=secondary,
            confidence=confidence,
            reasoning=reasoning
        )

    async def execute(
        self,
        plan: RoutingPlan,
        request: "MemoryQueryRequest",
        layer_handlers: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Execute parallel queries across layers based on routing plan.

        Args:
            plan: Routing plan with layer selection
            request: Original query request
            layer_handlers: Dict mapping layer names to query handlers

        Returns:
            Merged and deduplicated results from all layers.
        """
        layers_to_query = [plan.primary_layer]
        if plan.confidence < 0.8:
            layers_to_query.extend(plan.secondary_layers)

        # Remove duplicates while preserving order
        layers_to_query = list(dict.fromkeys(layers_to_query))

        # Execute queries in parallel
        tasks = []
        for layer in layers_to_query:
            handler = layer_handlers.get(layer)
            if handler:
                tasks.append(self._query_layer(layer, request, handler))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge and flatten results
        merged: List[Dict[str, Any]] = []
        seen_ids: set = set()

        for result in results:
            if isinstance(result, Exception):
                continue
            if isinstance(result, list):
                for item in result:
                    item_id = item.get("id")
                    if item_id and item_id not in seen_ids:
                        seen_ids.add(item_id)
                        merged.append(item)

        return merged

    async def _query_layer(
        self,
        layer: str,
        request: "MemoryQueryRequest",
        handler: Any
    ) -> List[Dict[str, Any]]:
        """Query a single layer using its handler."""
        try:
            # Handler interface: async def query(request) -> List[Dict]
            if hasattr(handler, 'query'):
                return await handler.query(request)
            return []
        except Exception:
            return []
