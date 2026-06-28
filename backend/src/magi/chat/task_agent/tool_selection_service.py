"""Tool selection helpers for chat task-agent turns."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from magi.agent.task_agents.common import ExecutionMode, ToolSelection
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext, IntentDecision
from magi.core.logger import get_logger
from magi.tools.capabilities import build_tool_capabilities
from magi.tools.recommender import ToolRecommender
from magi.tools.schema import ToolExecutionContext
from magi.tools.tool_advisory_reranker import ToolAdvisoryReranker
from magi.tools.tool_hint_resolver import ToolHintResolver

ToolAdvisoryProvider = Callable[
    [str | None, list[str] | None, int], Awaitable[list[dict[str, Any]]]
]

logger = get_logger(__name__)


class ChatToolSelectionService:
    """Resolve runtime task hints and provider tool ordering for chat turns."""

    def __init__(
        self,
        *,
        tool_registry: Any | None,
        tool_advisory_provider: ToolAdvisoryProvider | None = None,
    ) -> None:
        self._tool_advisory_provider = tool_advisory_provider
        self._tool_hint_resolver = (
            ToolHintResolver(tool_registry)
            if tool_registry is not None and callable(getattr(tool_registry, "get_tool", None))
            else None
        )
        self._tool_recommender = (
            ToolRecommender(tool_registry)
            if tool_registry is not None and callable(getattr(tool_registry, "get_tool", None))
            else None
        )
        self._tool_advisory_reranker = ToolAdvisoryReranker()

    async def select_tools(
        self,
        *,
        context: ChatRuntimeContext,
        intent: IntentDecision,
    ) -> ToolSelection:
        """Return the final ordered tool selection for a routed chat turn."""
        if intent.execution_mode in {
            ExecutionMode.ORCHESTRATION_LAUNCH,
            ExecutionMode.ORCHESTRATION_UPDATE,
            ExecutionMode.FACT_ONLY,
            ExecutionMode.EXPLORE_TASK_RENDER,
        }:
            return ToolSelection(
                tools=[],
                reasoning=intent.reasoning,
                task_hint=dict(intent.task_hint or {}),
            )

        recommendations = self._recommend_runtime_tools(context=context, intent=intent)
        if recommendations:
            recommendations = await self._rerank_runtime_recommendations(
                task_context=context.latest_user_message,
                recommendations=recommendations,
            )
        recommended_names = [
            str(item.get("tool") or "").strip()
            for item in recommendations
            if str(item.get("tool") or "").strip()
        ]
        ordered_tools = recommended_names + [
            tool for tool in intent.tools if tool not in recommended_names
        ]
        return ToolSelection(
            tools=ordered_tools,
            reasoning=intent.reasoning,
            task_hint=dict(intent.task_hint or {}),
            recommended_tools=recommendations,
        )

    async def build_prompt_tool_advisory(
        self,
        *,
        user_message: str,
        fetch_limit: int = 6,
        prompt_limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Return compact procedural-memory advisory for the route decider prompt."""
        if self._tool_advisory_provider is None:
            return []
        try:
            advisories = await self._tool_advisory_provider(
                user_message,
                None,
                fetch_limit,
            )
        except Exception as exc:
            logger.debug("Failed to fetch tool advisory: %s", exc)
            return []
        return self._tool_advisory_reranker.compress_for_prompt(
            advisories=advisories,
            limit=prompt_limit,
        )

    def resolve_runtime_task_hint(
        self,
        *,
        user_message: str,
        selected_tools: list[str],
        execution_mode: ExecutionMode,
    ) -> dict[str, Any]:
        """Return task-local hints used by the runtime tool recommender."""
        if self._tool_hint_resolver is None or not selected_tools:
            return {}
        request_profile = (
            "research"
            if any(tool in {"web-search", "web-fetch"} for tool in selected_tools)
            else None
        )
        scope_hints: list[str] = []
        if any(
            marker in user_message
            for marker in ["~/", "/", "\\", "src/", "backend/", "frontend/", "docs/"]
        ):
            scope_hints.append("The request references an explicit path or subdirectory.")
        if execution_mode == ExecutionMode.ORCHESTRATION_LAUNCH:
            scope_hints.append("The request will be decomposed into orchestration work.")
        return self._tool_hint_resolver.resolve(
            user_message=user_message,
            available_tools=list(selected_tools),
            request_profile=request_profile,
            scope_hints=scope_hints,
        )

    async def rerank_selected_tools(
        self,
        *,
        task_context: str,
        tool_names: list[str],
    ) -> list[str]:
        """Apply procedural-memory advisory to a selected tool name list."""
        if self._tool_advisory_provider is None or not tool_names:
            return tool_names
        try:
            advisories = await self._tool_advisory_provider(
                task_context,
                list(tool_names),
                len(tool_names),
            )
        except Exception as exc:
            logger.debug("Failed to fetch targeted tool advisory: %s", exc)
            return tool_names
        return self._tool_advisory_reranker.rerank_tool_names(
            tool_names=tool_names,
            advisories=advisories,
        )

    def _recommend_runtime_tools(
        self,
        *,
        context: ChatRuntimeContext,
        intent: IntentDecision,
    ) -> list[dict[str, Any]]:
        if self._tool_recommender is None or not intent.tools:
            return []
        try:
            execution_context = ToolExecutionContext(
                agent_id=context.agent_id,
                workspace=str(getattr(context.latest_payload, "workspace_path", "") or "."),
                permissions=["authenticated", "dangerous_tools"],
                env_vars={"session_id": context.session_id, "user_id": context.user_id},
                capabilities=build_tool_capabilities(),
            )
            return self._tool_recommender.recommend_tools(
                intent=context.latest_user_message,
                context=execution_context,
                top_k=len(intent.tools),
                task_hint=intent.task_hint,
                candidate_tools=list(intent.tools),
            )
        except Exception as exc:
            logger.debug(
                "Runtime tool recommendation failed, falling back to router order: %s", exc
            )
            return []

    async def _rerank_runtime_recommendations(
        self,
        *,
        task_context: str,
        recommendations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self._tool_advisory_provider is None or not recommendations:
            return recommendations
        tool_names = [
            str(item.get("tool") or item.get("name") or "").strip()
            for item in recommendations
            if str(item.get("tool") or item.get("name") or "").strip()
        ]
        if not tool_names:
            return recommendations
        try:
            advisories = await self._tool_advisory_provider(
                task_context,
                tool_names,
                len(tool_names),
            )
        except Exception as exc:
            logger.debug("Failed to fetch runtime recommendation advisory: %s", exc)
            return recommendations
        return self._tool_advisory_reranker.rerank_recommendations(
            recommendations=recommendations,
            advisories=advisories,
        )


__all__ = ["ChatToolSelectionService", "ToolAdvisoryProvider"]
