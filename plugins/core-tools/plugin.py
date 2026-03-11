"""Official built-in tools plugin."""
from __future__ import annotations

from magi.plugins import Plugin
from magi.tools.builtin import (
    AgentTool,
    BashTool,
    CapabilitiesTool,
    FileEditTool,
    FileReadTool,
    FileWriteTool,
    GlobTool,
    GrepTool,
    SystemSettingsTool,
    WeatherTool,
    WebFetchTool,
    WebSearchTool,
)


class CoreToolsPlugin(Plugin):
    """Registers all built-in tools through the plugin runtime."""

    def get_tools(self) -> list[type]:
        return [
            BashTool,
            FileReadTool,
            FileWriteTool,
            FileEditTool,
            GrepTool,
            GlobTool,
            CapabilitiesTool,
            WebSearchTool,
            WebFetchTool,
            WeatherTool,
            SystemSettingsTool,
            AgentTool,
        ]
