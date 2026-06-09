"""Bounded tool-discovery helper for execution-time tool expansion."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..recommender import ToolRecommender
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
        recommender = ToolRecommender(registry)
        recommendations: List[Dict[str, Any]] = []
        tool_recommendations = self._recommend_tools(
            recommender=recommender,
            registry=registry,
            query=query,
            context=context,
            current_tools=current_tools,
            candidate_limit=max(limit * self._TOOL_CANDIDATE_MULTIPLIER, self._MIN_TOOL_CANDIDATES),
        )
        tool_recommendations = await self._rerank_tool_recommendations(
            recommendations=tool_recommendations,
            query=query,
            context=context,
        )
        recommendations.extend(tool_recommendations)
        recommendations.extend(
            self._recommend_skills(
                registry=registry,
                query=query,
                current_tools=current_tools,
                limit=limit,
                existing_names={str(item.get("name") or "") for item in recommendations},
            )
        )

        recommendations = recommendations[:limit]
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

    def _recommend_tools(
        self,
        *,
        recommender: ToolRecommender,
        registry: Any,
        query: str,
        context: ToolExecutionContext,
        current_tools: list[str],
        candidate_limit: int,
    ) -> list[dict[str, Any]]:
        candidate_tools = [
            name
            for name in registry.list_tools(enabled_features=context.enabled_features)
            if name not in current_tools and name not in self._EXCLUDED_TOOL_NAMES
        ]
        if not candidate_tools:
            return []
        raw = recommender.recommend_tools(
            intent=query,
            context=context,
            top_k=candidate_limit,
            candidate_tools=candidate_tools,
        )
        recommendations: list[dict[str, Any]] = []
        for item in raw:
            name = str(item.get("tool") or "").strip()
            if not name:
                continue
            recommendations.append(
                {
                    "name": name,
                    "type": "tool",
                    "reason": str(item.get("reason") or "").strip(),
                    "score": float(item.get("score") or 0.0),
                    "category": str(item.get("category") or ""),
                }
            )
        return recommendations

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

    def _recommend_skills(
        self,
        *,
        registry: Any,
        query: str,
        current_tools: list[str],
        limit: int,
        existing_names: set[str],
    ) -> list[dict[str, Any]]:
        query_lower = query.lower()
        tokens = {token for token in query_lower.replace("/", " ").replace("_", " ").split() if len(token) > 1}
        scored: list[tuple[float, dict[str, Any]]] = []
        for skill_name in registry.get_skill_names():
            if skill_name in current_tools or skill_name in existing_names:
                continue
            metadata = registry.get_skill_metadata(skill_name)
            if metadata is None:
                continue
            description = str(metadata.description or "")
            haystack = " ".join(
                [
                    skill_name,
                    description,
                    str(metadata.argument_hint or ""),
                    " ".join(str(tag) for tag in (metadata.tags or [])),
                ]
            ).lower()
            score = 0.0
            if skill_name.lower() in query_lower:
                score += 0.6
            for token in tokens:
                if token in haystack:
                    score += 0.1
            if score <= 0:
                continue
            scored.append(
                (
                    score,
                    {
                        "name": skill_name,
                        "type": "skill",
                        "reason": description or "Skill description matched the requested capability.",
                        "score": round(score, 3),
                        "category": str(metadata.category or "skill"),
                    },
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in scored[:limit]]

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