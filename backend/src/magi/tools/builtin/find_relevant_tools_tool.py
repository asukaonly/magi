"""Bounded tool-discovery helper for execution-time tool expansion."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

from ..recommender import ToolRecommender
from ..tool_advisory_reranker import ToolAdvisoryReranker
from ..schema import Tool, ToolExecutionContext, ToolParameter, ToolResult, ToolSchema, ParameterType
from ..registry import tool_registry


logger = logging.getLogger(__name__)


_DISCOVERY_SYNONYMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("日程", ("calendar", "schedule")),
    ("日历", ("calendar", "schedule")),
    ("会议", ("meeting", "calendar")),
    ("空档", ("availability", "free", "busy", "slot")),
    ("空闲", ("availability", "free", "busy", "slot")),
    ("档期", ("availability", "schedule", "slot")),
    ("可用时间", ("availability", "free", "busy", "slot")),
    ("安排", ("schedule", "planning")),
    ("照片", ("photo", "image", "picture")),
    ("图片", ("image", "photo", "picture")),
    ("天气", ("weather", "forecast")),
    ("网页", ("web", "fetch", "browser")),
    ("搜索", ("search", "web")),
    ("代码", ("code", "file", "grep")),
    ("文件", ("file", "read", "write")),
)
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)


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
        skill_recommendations = self._recommend_skills(
            registry=registry,
            query=query,
            current_tools=current_tools,
            limit=max(limit * self._TOOL_CANDIDATE_MULTIPLIER, self._MIN_TOOL_CANDIDATES),
            existing_names={str(item.get("name") or "") for item in tool_recommendations},
        )

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
        query_tokens = set(self._tokenize_discovery_text(query))
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
            )
            haystack_lower = self._expand_discovery_text(haystack).lower()
            haystack_tokens = set(self._tokenize_discovery_text(haystack))
            score = 0.0
            if skill_name.lower() in query_lower:
                score += 0.6
            skill_name_tokens = set(self._tokenize_discovery_text(skill_name))
            if skill_name_tokens and skill_name_tokens.issubset(query_tokens):
                score += 0.45
            overlap = query_tokens & haystack_tokens
            score += min(len(overlap), 6) * 0.12
            category = str(metadata.category or "").strip().lower()
            if category and category in query_tokens:
                score += 0.2
            for tag in metadata.tags or []:
                tag_tokens = set(self._tokenize_discovery_text(str(tag)))
                if tag_tokens and tag_tokens & query_tokens:
                    score += 0.08
            for token in query_tokens:
                if len(token) > 2 and token in haystack_lower:
                    score += 0.03
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
    def _rank_recommendations(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        indexed: list[tuple[float, int, dict[str, Any]]] = []
        for index, item in enumerate(recommendations):
            indexed.append((float(item.get("score") or 0.0), index, item))
        indexed.sort(key=lambda row: (-row[0], row[1]))
        return [item for _, _, item in indexed]

    @staticmethod
    def _expand_discovery_text(text: str) -> str:
        lowered = str(text or "").lower()
        aliases: list[str] = []
        for marker, expansions in _DISCOVERY_SYNONYMS:
            if marker in lowered:
                aliases.extend(expansions)
        if not aliases:
            return lowered
        return " ".join([lowered, *aliases])

    @classmethod
    def _tokenize_discovery_text(cls, text: str) -> list[str]:
        expanded = cls._expand_discovery_text(text)
        tokens: list[str] = []
        for match in _TOKEN_RE.findall(expanded):
            token = match.lower().strip()
            if len(token) > 1:
                tokens.append(token)
        return tokens

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
