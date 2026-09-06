"""Tool registry import/export helpers."""

from __future__ import annotations

import logging
from typing import Any, Callable

from .schema import Tool

logger = logging.getLogger(__name__)


class ToolRegistryFormatMixin:
    """Import/export registered tools in provider-specific formats."""

    _tools: dict[str, type[Tool]]

    def get_tool(self, tool_name: str) -> Tool | None: ...

    def list_tools(self) -> list[str]: ...

    def exported_tool_name(self, name: str) -> str: ...

    def register(self, tool_class: type[Tool]) -> None: ...

    def export_to_claude_format(self) -> list[dict[str, Any]]:
        """
        Export all tools in Claude Tool Use API format.

        Only exports tools that are ready (have required configuration).

        Returns:
            List of tools in Claude API format.
        """
        tools = []
        for tool_name in self.list_tools():
            tool = self.get_tool(tool_name)
            if tool and tool.is_ready():
                definition = tool.to_claude_format()
                definition["name"] = self.exported_tool_name(tool_name)
                tools.append(definition)
            elif tool and not tool.is_ready():
                logger.debug(f"Tool {tool_name} not ready (missing configuration), skipping")
        return tools

    def import_from_claude_format(
        self, tool_defs: list[dict[str, Any]], executor: Callable[..., Any]
    ) -> None:
        """
        Import tools from Claude Tool Use API format.

        Args:
            tool_defs: List of tool definitions in Claude format.
            executor: Execute function with signature async def execute(name, params) -> Any.
        """
        from .builtin import DynamicTool

        for tool_def in tool_defs:
            schema = Tool.Schema.from_claude_format(tool_def)

            dynamic_tool = type(
                f"ClaudeTool_{tool_def['name']}",
                (DynamicTool,),
                {
                    "schema": schema,
                    "_executor": staticmethod(executor),
                },
            )

            try:
                self.register(dynamic_tool)
            except Exception as e:
                logger.error(f"Failed to import tool {tool_def.get('name')}: {e}")


__all__ = ["ToolRegistryFormatMixin"]
