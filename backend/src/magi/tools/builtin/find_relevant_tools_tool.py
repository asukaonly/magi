"""Bounded tool-discovery helper for execution-time tool expansion."""

from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict

from ..discovery_index import ToolDiscoveryIndex
from ..recommender import ToolRecommender
from ..tool_advisory_reranker import ToolAdvisoryReranker
from ..schema import (
    ParameterType,
    Tool,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)
from ..registry import tool_registry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _DiscoveryRequest:
    query: str
    current_tools: list[str]
    limit: int


@dataclass(frozen=True)
class _DiscoveryResult:
    indexed_recommendations: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    filtered_tool_count: int


class FindRelevantToolsTool(Tool):
    """Suggest a small number of additional tools for the current turn."""

    _EXCLUDED_TOOL_NAMES = {"find-relevant-tools", "get-capabilities", "todo_write"}
    _TOOL_CANDIDATE_MULTIPLIER = 3
    _MIN_TOOL_CANDIDATES = 4
    _DISCOVERY_CACHE_TTL_SECONDS = 300.0
    _DISCOVERY_CACHE_MAX_ENTRIES = 64

    def __init__(self) -> None:
        self._advisory_reranker = ToolAdvisoryReranker()
        self._discovery_cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
        super().__init__()

    async def clear_user_content(self) -> None:
        """Discard cached discovery queries and recommendation payloads."""
        self._discovery_cache.clear()

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="find-relevant-tools",
            description=(
                "Find up to two additional tools or skills that are relevant to the current unmet subtask. "
                "Use this when the current tool set cannot complete the next grounded step, not for broad capability browsing."
            ),
            category="system",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="query",
                    type=ParameterType.STRING,
                    description=(
                        "Describe one focused missing capability, including the domain/action/object and concrete facts "
                        "discovered so far. Do not pass the whole user request."
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
                        "query": "Need historical weather for Hangzhou on 2025-05-01 after recovering the trip date from memory.",
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
        request = self._build_request(parameters)
        registry = self._get_registry()
        cache_key = self._build_cache_key(
            registry=registry,
            query=request.query,
            current_tools=request.current_tools,
            limit=request.limit,
            context=context,
        )
        cached_payload = self._get_cached_payload(cache_key)
        if cached_payload is not None:
            return ToolResult(success=True, data=cached_payload)

        discovery = await self._discover(
            registry=registry,
            request=request,
            context=context,
        )
        payload = self._build_payload(request, discovery)
        self._store_cached_payload(cache_key, payload)

        return ToolResult(success=True, data=payload)

    def _build_request(self, parameters: Dict[str, Any]) -> _DiscoveryRequest:
        query = str(parameters.get("query") or "").strip()
        limit = int(parameters.get("limit") or 2)
        return _DiscoveryRequest(
            query=query,
            current_tools=self._normalize_current_tools(parameters.get("current_tools")),
            limit=1 if limit < 1 else 2 if limit > 2 else limit,
        )

    async def _discover(
        self,
        *,
        registry: Any,
        request: _DiscoveryRequest,
        context: ToolExecutionContext,
    ) -> _DiscoveryResult:
        discovery_index = ToolDiscoveryIndex.from_registry(
            registry,
            enabled_features=context.enabled_features,
        )
        candidate_limit = max(
            request.limit * self._TOOL_CANDIDATE_MULTIPLIER,
            self._MIN_TOOL_CANDIDATES,
        )
        indexed_recommendations = discovery_index.search(
            query=request.query,
            limit=candidate_limit,
            current_tools=request.current_tools,
            excluded_names=self._EXCLUDED_TOOL_NAMES,
        )
        tool_recommendations = self._recommendations_by_type(
            indexed_recommendations,
            item_type="tool",
        )
        raw_tool_count = len(tool_recommendations)
        tool_recommendations = self._filter_allowed_tool_recommendations(
            recommendations=tool_recommendations,
            registry=registry,
            context=context,
        )
        tool_recommendations = await self._rerank_tool_recommendations(
            recommendations=tool_recommendations,
            query=request.query,
            context=context,
        )
        skill_recommendations = self._recommendations_by_type(
            indexed_recommendations,
            item_type="skill",
        )

        recommendations = self._rank_recommendations(
            [*tool_recommendations, *skill_recommendations]
        )[: request.limit]
        return _DiscoveryResult(
            indexed_recommendations=indexed_recommendations,
            recommendations=recommendations,
            filtered_tool_count=raw_tool_count - len(tool_recommendations),
        )

    @staticmethod
    def _recommendations_by_type(
        recommendations: list[dict[str, Any]],
        *,
        item_type: str,
    ) -> list[dict[str, Any]]:
        return [item for item in recommendations if item.get("type") == item_type]

    def _build_payload(
        self,
        request: _DiscoveryRequest,
        discovery: _DiscoveryResult,
    ) -> dict[str, Any]:
        recommended_names = self._recommended_names(discovery.recommendations)
        discovery_metrics = self._build_discovery_metrics(
            cache_hit=False,
            indexed_recommendations=discovery.indexed_recommendations,
            recommendations=discovery.recommendations,
            filtered_tool_count=discovery.filtered_tool_count,
        )
        return {
            "query": request.query,
            "recommendations": discovery.recommendations,
            "recommended_tools": recommended_names,
            "tool_expansion": self._expansion_payload(recommended_names),
            "discovery_metrics": discovery_metrics,
        }

    @staticmethod
    def _recommended_names(recommendations: list[dict[str, Any]]) -> list[str]:
        return [
            name
            for name in (str(item.get("name") or "").strip() for item in recommendations)
            if name
        ]

    @staticmethod
    def _expansion_payload(recommended_names: list[str]) -> dict[str, Any]:
        return {
            "append_tools": recommended_names,
            "reason": (
                "Recommended additional tools for the missing next-step capability. "
                "Append them only if they are not already available in this turn."
                if recommended_names
                else "No additional tools were confidently recommended."
            ),
        }

    def _filter_allowed_tool_recommendations(
        self,
        *,
        recommendations: list[dict[str, Any]],
        registry: Any,
        context: ToolExecutionContext,
    ) -> list[dict[str, Any]]:
        if not recommendations:
            return []

        recommender = ToolRecommender(registry)
        allowed: list[dict[str, Any]] = []
        for item in recommendations:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            is_suitable, reason = recommender.evaluate_tool(name, context)
            if is_suitable:
                allowed.append(item)
            else:
                logger.debug("Filtered discovered tool %s: %s", name, reason)
        return allowed

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
            advisory_rows = await l4_store.get_tool_advisory(
                tool_names=tool_names, task_context=query
            )
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

    def _build_cache_key(
        self,
        *,
        registry: Any,
        query: str,
        current_tools: list[str],
        limit: int,
        context: ToolExecutionContext,
    ) -> tuple[Any, ...]:
        return (
            self._discovery_scope(context),
            " ".join(str(query or "").lower().split()),
            tuple(sorted(current_tools)),
            int(limit),
            tuple(sorted(str(item) for item in (context.permissions or []))),
            tuple(sorted(str(item) for item in (context.enabled_features or []))),
            self._registry_signature(registry, context=context),
        )

    def _get_cached_payload(self, cache_key: tuple[Any, ...]) -> dict[str, Any] | None:
        cached = self._discovery_cache.get(cache_key)
        if cached is None:
            return None
        cached_at, payload = cached
        now = time.monotonic()
        age_seconds = now - cached_at
        if age_seconds > self._DISCOVERY_CACHE_TTL_SECONDS:
            self._discovery_cache.pop(cache_key, None)
            return None
        data = copy.deepcopy(payload)
        metrics = data.get("discovery_metrics")
        if isinstance(metrics, dict):
            metrics["cache_hit"] = True
            metrics["cache_age_ms"] = int(age_seconds * 1000)
        return data

    def _store_cached_payload(self, cache_key: tuple[Any, ...], payload: dict[str, Any]) -> None:
        if len(self._discovery_cache) >= self._DISCOVERY_CACHE_MAX_ENTRIES:
            oldest_key = min(
                self._discovery_cache,
                key=lambda key: self._discovery_cache[key][0],
            )
            self._discovery_cache.pop(oldest_key, None)
        self._discovery_cache[cache_key] = (time.monotonic(), copy.deepcopy(payload))

    @staticmethod
    def _discovery_scope(context: ToolExecutionContext) -> str:
        env_vars = context.env_vars or {}
        for key in ("session_id", "task_id", "turn_id"):
            value = str(env_vars.get(key) or "").strip()
            if value:
                return f"{key}:{value}"
        if context.task_id:
            return f"task_id:{context.task_id}"
        return f"agent_id:{context.agent_id}"

    @staticmethod
    def _registry_signature(
        registry: Any, *, context: ToolExecutionContext
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        try:
            tool_names = tuple(
                sorted(
                    str(name)
                    for name in registry.list_tools(enabled_features=context.enabled_features)
                )
            )
        except TypeError:
            tool_names = tuple(sorted(str(name) for name in registry.list_tools()))
        skill_names = tuple(sorted(str(name) for name in registry.get_skill_names()))
        return tool_names, skill_names

    @staticmethod
    def _build_discovery_metrics(
        *,
        cache_hit: bool,
        indexed_recommendations: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
        filtered_tool_count: int,
    ) -> dict[str, Any]:
        return {
            "cache_hit": cache_hit,
            "cache_age_ms": 0,
            "candidate_count": len(indexed_recommendations),
            "candidate_source_counts": _count_by_field(indexed_recommendations, "source"),
            "candidate_type_counts": _count_by_field(indexed_recommendations, "type"),
            "recommended_count": len(recommendations),
            "recommended_source_counts": _count_by_field(recommendations, "source"),
            "recommended_type_counts": _count_by_field(recommendations, "type"),
            "filtered_tool_count": max(0, int(filtered_tool_count)),
        }

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


def _count_by_field(items: list[dict[str, Any]], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(field_name) or "unknown").strip() or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return counts


__all__ = ["FindRelevantToolsTool"]
