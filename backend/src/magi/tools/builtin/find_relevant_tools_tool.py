"""Bounded tool-discovery helper for execution-time tool expansion."""

from __future__ import annotations

import logging
from typing import Any, Dict

from ..discovery_index import ToolDiscoveryIndex
from ..tool_advisory_reranker import ToolAdvisoryReranker
from ..schema import Tool, ToolExecutionContext, ToolParameter, ToolResult, ToolSchema, ParameterType
from ..registry import tool_registry


logger = logging.getLogger(__name__)


class FindRelevantToolsTool(Tool):
    """Suggest a small number of additional tools for the current turn."""

    _EXCLUDED_TOOL_NAMES = {"find-relevant-tools", "get-capabilities", "todo_write"}
    _TOOL_CANDIDATE_MULTIPLIER = 3
    _MIN_TOOL_CANDIDATES = 4

    def __init__(self) -> None:
        self._advisory_reranker = ToolAdvisoryReranker()
        super().__init__()

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="find-relevant-tools",
            description=(
                "Find up to two additional tools or skills that are relevant to the current unmet subtask. "
                "Use this when the current tool set cannot complete the next step, not for broad capability browsing."
            ),
            category="system",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="query",
                    type=ParameterType.STRING,
                    description=(
                        "Describe the missing capability or next subtask. Include concrete facts discovered so far when relevant."
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="current_tools",
                    type=ParameterType.ARRAY,
                    array_item_type=ParameterType.STRING,
                    description="Tools already available in this turn. Recommended tools will exclude these.",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type=ParameterType.INTEGER,
                    description="Maximum number of additional tools or skills to recommend.",
                    required=False,
                    default=2,
                    min_value=1,
                    max_value=2,
                ),
            ],
            examples=[
                {
                    "input": {
                        "query": "I already recovered that the trip was in Hangzhou on 2025-05-01, and now I need the historical weather.",
                        "current_tools": ["memory_query"],
                        "limit": 1,
                    },
                    "output": "Returns the weather tool as the best next addition.",
                }
            ],
            timeout=10,
            retry_on_failure=False,
            dangerous=False,
            tags=["system", "discovery", "tooling"],
            metadata={
                "task_intents": ["expand_toolset", "recover_execution_path"],
                "domains": ["tooling"],
                "operations": ["discover", "narrow"],
                "cost": "cheap",
                "tool_hint": "Use only when the current tool set is missing a needed capability for the next step.",
            },
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        query = str(parameters.get("query") or "").strip()
        current_tools = self._normalize_current_tools(parameters.get("current_tools"))
        limit = int(parameters.get("limit") or 2)
        limit = 1 if limit < 1 else 2 if limit > 2 else limit

        registry = self._get_registry()
        candidate_limit = max(
            limit * self._TOOL_CANDIDATE_MULTIPLIER,
            self._MIN_TOOL_CANDIDATES,
        )
        discovery_index = ToolDiscoveryIndex.from_registry(
            registry,
            enabled_features=context.enabled_features,
        )
        indexed_recommendations = discovery_index.search(
            query=query,
            limit=candidate_limit,
            current_tools=current_tools,
            excluded_names=self._EXCLUDED_TOOL_NAMES,
        )
        tool_recommendations = [
            item for item in indexed_recommendations if item.get("type") == "tool"
        ]
        tool_recommendations = await self._rerank_tool_recommendations(
            recommendations=tool_recommendations,
            query=query,
            context=context,
        )
        skill_recommendations = [
            item for item in indexed_recommendations if item.get("type") == "skill"
        ]

        recommendations = self._rank_recommendations(
            [*tool_recommendations, *skill_recommendations]
        )[:limit]
        recommended_names = [str(item.get("name") or "").strip() for item in recommendations if str(item.get("name") or "").strip()]
        expansion_payload = {
            "append_tools": recommended_names,
            "reason": (
                "Recommended additional tools for the missing next-step capability. "
                "Append them only if they are not already available in this turn."
                if recommended_names
                else "No additional tools were confidently recommended."
            ),
        }

        return ToolResult(
            success=True,
            data={
                "query": query,
                "recommendations": recommendations,
                "recommended_tools": recommended_names,
                "tool_expansion": expansion_payload,
            },
        )

    async def _rerank_tool_recommendations(
        self,
        *,
        recommendations: list[dict[str, Any]],
        query: str,
        context: ToolExecutionContext | None = None,
    ) -> list[dict[str, Any]]:
        if not recommendations:
            return []

        l4_store = self._get_l4_store(context=context)
        if l4_store is None or not hasattr(l4_store, "get_tool_advisory"):
            return recommendations

        tool_names = [str(item.get("name") or "").strip() for item in recommendations]
        tool_names = [name for name in tool_names if name]
        if not tool_names:
            return recommendations

        try:
            advisory_rows = await l4_store.get_tool_advisory(tool_names=tool_names, task_context=query)
        except Exception as exc:
            logger.debug("Failed to fetch L4 tool advisory for discovery: %s", exc)
            return recommendations

        return self._advisory_reranker.rerank_recommendations(
            recommendations=recommendations,
            advisories=list(advisory_rows),
        )

    @staticmethod
    def _rank_recommendations(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        indexed: list[tuple[float, int, dict[str, Any]]] = []
        for index, item in enumerate(recommendations):
            indexed.append((float(item.get("score") or 0.0), index, item))
        indexed.sort(key=lambda row: (-row[0], row[1]))
        return [item for _, _, item in indexed]

    @staticmethod
    def _normalize_current_tools(raw_value: Any) -> list[str]:
        if not isinstance(raw_value, list):
            return []
        normalized: list[str] = []
        for item in raw_value:
            name = str(item or "").strip()
            if name:
                normalized.append(name)
        return normalized

    def _get_registry(self) -> Any:
        bound = getattr(self, "_tool_registry_ref", None)
        return bound if bound is not None else tool_registry

    def _get_l4_store(self, *, context: ToolExecutionContext | None = None) -> Any | None:
        if context is not None:
            caps = getattr(context, "capabilities", None)
            mq = getattr(caps, "memory_query", None) if caps is not None else None
            if mq is not None:
                return mq.get_l4_store()
        return None


__all__ = ["FindRelevantToolsTool"]
