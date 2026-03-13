"""Official built-in tools plugin."""
from __future__ import annotations

from magi.plugins import Plugin
from magi.tools.core_tools import CORE_TOOL_CLASSES


class CoreToolsPlugin(Plugin):
    """Registers all built-in tools through the plugin runtime."""

    def get_tools(self) -> list[type]:
        return list(CORE_TOOL_CLASSES)
