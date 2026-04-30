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
    _category_index: dict[str, list[str]]
    _tag_index: dict[str, list[str]]
    _stats: dict[str, ToolExecutionStats]
    _skills: dict[str, "SkillMetadata"]

    def get_tool(self, tool_name: str) -> Optional[Tool]:
        """
        Get tool instance.

        Args:
            tool_name: Tool name.

        Returns:
            Tool instance or None.
        """
        return self._tool_instances.get(tool_name)

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
        tools = list(self._tools.keys())

        if category:
            tools = list(set(tools) & set(self._category_index.get(category, [])))

        if tags:
            tag_sets = [set(self._tag_index.get(tag, [])) for tag in tags]
            if tag_sets:
                tools = list(set(tools) & set.intersection(*tag_sets))

        if enabled_features is not None:
            enabled_set = set(enabled_features)
            tools = [
                name for name in tools
                if self._tool_passes_feature_gate(name, enabled_set)
            ]

        return tools

    def get_tool_info(self, tool_name: str) -> Optional[dict[str, Any]]:
        """
        Get tool info.

        Args:
            tool_name: Tool name.

        Returns:
            Tool info dict or None.
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return None

        info = tool.get_info()
        info["stats"] = self._stats[tool_name].get_stats()

        return info

    def get_all_tools_info(self, enabled_features: Optional[list[str]] = None) -> list[dict[str, Any]]:
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
            if enabled_set is not None and not self._tool_passes_feature_gate(tool_name, enabled_set):
                continue
            tools_info.append(self.get_tool_info(tool_name))

        for skill_name, skill_metadata in self._skills.items():
            tools_info.append({
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
            })

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
            if tool_name in self._stats:
                return {
                    tool_name: self._stats[tool_name].get_stats()
                }
            return {}
        else:
            return {
                name: stats.get_stats()
                for name, stats in self._stats.items()
            }


__all__ = ["ToolRegistryLookupMixin"]
