"""Explicit model-tool exposure policy, independent of tool categories.

Categories organize capabilities. Exposure controls when schemas are offered;
invocation still crosses the runtime's permission, effect, and budget guards.
Unlisted tools are discovered or explicitly selected by the owning driver.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ToolExposure(str, Enum):
    """Default schema admission for the main chat loop."""

    RESIDENT = "resident"
    CONTEXTUAL = "contextual"
    DEFERRED = "deferred"


_RUNTIME_FACT_TOOLS = ("current_time", "environment_query")
_TOOL_EXPOSURE = {
    "enter_plan_mode": ToolExposure.RESIDENT,
    "todo_write": ToolExposure.RESIDENT,
    "ask_user_question": ToolExposure.RESIDENT,
    "detach_to_background": ToolExposure.RESIDENT,
    "agent": ToolExposure.RESIDENT,
    "find-relevant-tools": ToolExposure.RESIDENT,
    "memory_query": ToolExposure.RESIDENT,
    "current_time": ToolExposure.RESIDENT,
    "environment_query": ToolExposure.RESIDENT,
    "exit_plan_mode": ToolExposure.CONTEXTUAL,
    "request_reasoning_depth": ToolExposure.CONTEXTUAL,
    "task_query": ToolExposure.CONTEXTUAL,
    "trace_query": ToolExposure.DEFERRED,
    "batch_create": ToolExposure.DEFERRED,
}

# The host supplies these from live execution state, never semantic discovery.
STATE_MANAGED_TOOLS = frozenset({"exit_plan_mode", "request_reasoning_depth"})


def resolve_tool_exposure(tool_name: str) -> ToolExposure:
    """Return explicit exposure policy; new tools default to discovery."""
    return _TOOL_EXPOSURE.get(tool_name, ToolExposure.DEFERRED)


def resolve_resident_system_tools(tool_registry: Any) -> list[str]:
    """Return registered, enabled tools in the stable chat core."""
    registered = set(tool_registry.list_tools())
    return [
        name
        for name, exposure in _TOOL_EXPOSURE.items()
        if exposure is ToolExposure.RESIDENT and name in registered
    ]


def resolve_runtime_fact_tools(tool_registry: Any) -> list[str]:
    """Return universal read-only fact tools registered in this runtime."""
    try:
        registered = set(tool_registry.list_tools())
    except (AttributeError, TypeError):
        return []
    return [name for name in _RUNTIME_FACT_TOOLS if name in registered]


__all__ = [
    "STATE_MANAGED_TOOLS",
    "ToolExposure",
    "resolve_tool_exposure",
    "resolve_resident_system_tools",
    "resolve_runtime_fact_tools",
]
