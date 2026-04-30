"""Resolve structured task intent and tool hints for planning and tool selection."""

from __future__ import annotations

from typing import Any, Optional

from .registry import ToolRegistry
from .tool_hint_metadata import ToolHintMetadataMixin
from .tool_hint_profile import ToolHintProfileMixin
from .tool_hint_ranking import ToolHintRankingMixin
from .tool_hint_rendering import ToolHintRenderingMixin


class ToolHintResolver(
    ToolHintRenderingMixin,
    ToolHintProfileMixin,
    ToolHintRankingMixin,
    ToolHintMetadataMixin,
):
    """Infer task intent and rank tools with lightweight structured hints."""

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._tool_registry = tool_registry

    def resolve(
        self,
        *,
        user_message: str,
        available_tools: list[str],
        request_profile: str | None = None,
        scope_hints: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        normalized_tools = [tool for tool in available_tools if self._get_tool_info(tool)]
        if not normalized_tools:
            return {}

        task_profile = self._infer_task_profile(
            user_message=user_message,
            request_profile=request_profile,
            scope_hints=scope_hints or [],
        )
        scope_policy = self._infer_scope_policy(
            user_message=user_message,
            request_profile=request_profile,
            scope_hints=scope_hints or [],
            available_tools=normalized_tools,
            task_profile=task_profile,
        )
        ranked_tools = self._rank_tools(task_profile=task_profile, available_tools=normalized_tools)
        return {
            "task_intent": task_profile["task_intent"],
            "domain": task_profile["domain"],
            "operation": task_profile["operation"],
            **scope_policy,
            "tool_hints": ranked_tools,
        }


__all__ = ["ToolHintResolver"]
