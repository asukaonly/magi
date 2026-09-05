"""Tool registry lookup, filtering, and stats helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .schema import Tool
from .registry_stats import ToolExecutionStats

if TYPE_CHECKING:
    from ..skills.schema import SkillMetadata


class ToolRegistryLookupMixin:
    """Lookup, filtering, and statistics methods for ToolRegistry."""

    _tools: dict[str, type[Tool]]
    _tool_instances: dict[str, Tool]
    _tool_aliases: dict[str, str]
    _category_index: dict[str, list[str]]
    _tag_index: dict[str, list[str]]
    _stats: dict[str, ToolExecutionStats]
    _skills: dict[str, "SkillMetadata"]

    def _is_tool_enabled(self, tool_name: str) -> bool:
        """Return False when a built-in tool is disabled in product config."""
        try:
            from ..config import get_config

            config = get_config()
        except Exception:
            return True

        enabled_by_tool = {
            "weather": getattr(config.tools.weather, "enabled", True),
            "web-search": getattr(config.tools.web_search, "enabled", True),
            "web-fetch": getattr(config.tools.web_fetch, "enabled", True),
        }
        return bool(enabled_by_tool.get(tool_name, True))

    def resolve_tool_name(self, tool_name: str) -> str:
        """Return the canonical tool name for direct names and supported aliases."""
        normalized_name = str(tool_name or "").strip()
        if not normalized_name:
            return ""
        if not self._model_name_is_current(normalized_name):
            return normalized_name
        return self._tool_aliases.get(normalized_name, normalized_name)

    def get_tool(self, tool_name: str) -> Optional[Tool]:
        """
        Get tool instance.

        Args:
            tool_name: Tool name.

        Returns:
            Tool instance or None.
        """
        return self._tool_instances.get(self.resolve_tool_name(tool_name))

    def _is_model_tool(self, tool_name: str) -> bool:
        """Keep host-only operation adapters out of model discovery."""
        tool = self._tool_instances.get(tool_name)
        if tool is None:
            return False
        triggers = tool.get_schema().metadata.get("invocation_triggers")
        return triggers is None or "model" in triggers

    def list_tools(
        self,
        category: Optional[str] = None,
        tags: Optional[list[str]] = None,
        enabled_features: Optional[list[str]] = None,
    ) -> list[str]:
        """
        List tools with optional filters.

        Args:
            category: Filter by category.
            tags: Filter by tags.
            enabled_features: If provided, exclude tools that require
                feature flags not present in this list.

        Returns:
            List of tool names.
        """
        tools = [
            tool_name
            for tool_name in self._tools.keys()
            if self._is_tool_enabled(tool_name) and self._is_model_tool(tool_name)
        ]

        if category:
            tools = list(set(tools) & set(self._category_index.get(category, [])))

        if tags:
            tag_sets = [set(self._tag_index.get(tag, [])) for tag in tags]
            if tag_sets:
                tools = list(set(tools) & set.intersection(*tag_sets))

        if enabled_features is not None:
            enabled_set = set(enabled_features)
            tools = [name for name in tools if self._tool_passes_feature_gate(name, enabled_set)]

        return tools

    def get_tool_info(self, tool_name: str) -> Optional[dict[str, Any]]:
        """
        Get tool info.

        Args:
            tool_name: Tool name.

        Returns:
            Tool info dict or None.
        """
        canonical_name = self.resolve_tool_name(tool_name)
        tool = self.get_tool(canonical_name)
        if not tool:
            return None

        info = tool.get_info()
        info["stats"] = self._stats[canonical_name].get_stats()

        return info

    def get_all_tools_info(
        self, enabled_features: Optional[list[str]] = None
    ) -> list[dict[str, Any]]:
        """
        Get all tool info (includes skills).

        Args:
            enabled_features: If provided, exclude tools requiring
                feature flags not present in this list.

        Returns:
            List of tool info dicts.
        """
        enabled_set = set(enabled_features) if enabled_features is not None else None
        tools_info = []
        for tool_name in self._tools.keys():
            if not self._is_tool_enabled(tool_name) or not self._is_model_tool(tool_name):
                continue
            if enabled_set is not None and not self._tool_passes_feature_gate(
                tool_name, enabled_set
            ):
                continue
            tools_info.append(self.get_tool_info(tool_name))

        for skill_name, skill_metadata in self._skills.items():
            tools_info.append(
                {
                    "name": skill_metadata.name,
                    "description": skill_metadata.description,
                    "category": skill_metadata.category or "skill",
                    "type": "skill",
                    "argument_hint": skill_metadata.argument_hint,
                    "user_invocable": skill_metadata.user_invocable,
                    "context": skill_metadata.context,
                    "agent": skill_metadata.agent,
                    "tags": skill_metadata.tags,
                    "parameters": [],
                    "examples": [],
                }
            )

        return tools_info

    def _tool_passes_feature_gate(self, tool_name: str, enabled_set: set[str]) -> bool:
        """Return True if the tool's feature_flags are all satisfied."""
        tool = self._tool_instances.get(tool_name)
        if not tool:
            return True
        required = tool.get_schema().feature_flags
        if not required:
            return True
        return all(f in enabled_set for f in required)

    def get_stats(self, tool_name: Optional[str] = None) -> dict[str, Any]:
        """
        Get execution statistics.

        Args:
            tool_name: Tool name (None to get all).

        Returns:
            Statistics dictionary.
        """
        if tool_name:
            canonical_name = self.resolve_tool_name(tool_name)
            if canonical_name in self._stats:
                return {canonical_name: self._stats[canonical_name].get_stats()}
            return {}
        else:
            return {name: stats.get_stats() for name, stats in self._stats.items()}


__all__ = ["ToolRegistryLookupMixin"]
