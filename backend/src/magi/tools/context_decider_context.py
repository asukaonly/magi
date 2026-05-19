"""Typed routing context for ContextDecider prompt assembly."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, kw_only=True)
class ContextDeciderContext:
    """Normalized runtime context used by the routing prompt."""

    os_name: str = ""
    os_version: str = ""
    current_datetime: str = ""
    timezone: str = ""
    workspace_path: str = ""
    home_dir: str = ""
    current_user: str = ""
    recent_messages: list[dict[str, Any]] = field(default_factory=list)
    recent_tool_errors: list[dict[str, Any]] = field(default_factory=list)
    recent_tool_state: list[dict[str, Any]] = field(default_factory=list)
    tool_advisory: list[dict[str, Any]] = field(default_factory=list)
    # Pre-rendered menu of the active persona's signature triggers and
    # quiet-hour conditions, injected so the LLM can pick from a per-persona
    # set. Empty string disables the Persona Routing Menu prompt block.
    persona_routing_brief: str = ""

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

