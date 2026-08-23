"""
Tool registry.

Provides tool registration, lookup, execution, and monitoring.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from .registry_execution import ToolRegistryExecutionMixin
from .registry_formats import ToolRegistryFormatMixin
from .registry_lookup import ToolRegistryLookupMixin
from .registry_skills import ToolRegistrySkillMixin
from .registry_stats import ToolExecutionStats
from .schema import Tool

if TYPE_CHECKING:
    from ..skills.schema import SkillMetadata

logger = logging.getLogger(__name__)


class ToolRegistry(
    ToolRegistryLookupMixin,
    ToolRegistrySkillMixin,
    ToolRegistryExecutionMixin,
    ToolRegistryFormatMixin,
):
    """
    Tool registry.

    Manages tool registration, lookup, execution, and statistics.
    """

    def __init__(self, skill_indexer=None):
        self._tools: dict[str, type[Tool]] = {}
        self._tool_instances: dict[str, Tool] = {}
        self._tool_aliases: dict[str, str] = {
            "ask": "ask_user_question",
        }
        self._category_index: dict[str, list[str]] = defaultdict(list)
        self._tag_index: dict[str, list[str]] = defaultdict(list)
        self._stats: dict[str, ToolExecutionStats] = defaultdict(ToolExecutionStats)
        self._skills: dict[str, "SkillMetadata"] = {}
        self._skill_indexer = skill_indexer
        self._user_content_clear_condition = asyncio.Condition()
        self._user_content_clear_active = False
        self._active_tool_invocations = 0
        self._active_tool_invocation_lineages: dict[str, int] = {}
        self._tool_effect_ledger = None
        self._tool_effect_ledger_required = False

    def bind_tool_effect_ledger(self, ledger, *, required: bool = True) -> None:
        """Bind durable effect governance to canonical tool invocations."""
        self._tool_effect_ledger = ledger
        self._tool_effect_ledger_required = bool(required)

    def unbind_tool_effect_ledger(self) -> None:
        """Remove the runtime-owned effect ledger during shutdown."""
        self._tool_effect_ledger = None
        self._tool_effect_ledger_required = False

    def resolve_tool_effect_ledger(self):
        """Return the bound ledger and whether effect calls require it."""
        return self._tool_effect_ledger, self._tool_effect_ledger_required

    def register(self, tool_class: type[Tool]) -> None:
        """
        Register a tool.

        Args:
            tool_class: Tool class to register.
        """
        temp_instance = tool_class()
        schema = temp_instance.get_schema()

        if not schema:
            raise ValueError(f"Tool {tool_class.__name__} must define a schema")

        tool_name = schema.name

        if tool_name in self._tools:
            logger.warning(f"Tool {tool_name} already registered, overwriting")

        setattr(temp_instance, "_tool_registry_ref", self)
        self._tools[tool_name] = tool_class
        self._tool_instances[tool_name] = temp_instance
        self._category_index[schema.category].append(tool_name)

        for tag in schema.tags:
            self._tag_index[tag].append(tool_name)

        self._stats[tool_name] = ToolExecutionStats()

        logger.info(f"Registered tool: {tool_name} (category: {schema.category})")

    def unregister(self, tool_name: str) -> bool:
        """
        Unregister a tool.

        Args:
            tool_name: Tool name.

        Returns:
            True if successful.
        """
        if tool_name not in self._tools:
            logger.warning(f"Tool {tool_name} not registered")
            return False

        schema = self._tool_instances[tool_name].get_schema()

        if schema.category in self._category_index:
            self._category_index[schema.category].remove(tool_name)

        for tag in schema.tags:
            if tag in self._tag_index:
                self._tag_index[tag].remove(tool_name)

        del self._tools[tool_name]
        del self._tool_instances[tool_name]
        del self._stats[tool_name]

        logger.info(f"Unregistered tool: {tool_name}")
        return True


tool_registry = ToolRegistry()


__all__ = ["ToolExecutionStats", "ToolRegistry", "tool_registry"]
