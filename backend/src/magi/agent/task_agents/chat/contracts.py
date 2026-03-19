"""Typed contracts for the chat task-agent pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..common import BaseIntentDecision, BaseRuntimeContext


@dataclass(slots=True, kw_only=True)
class ChatRuntimeContext(BaseRuntimeContext):
    """Fully built runtime context for a chat task-agent turn."""

    conversation_history: list[dict[str, Any]]
    active_orchestrations: list[dict[str, Any]]
    recent_tool_errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True, kw_only=True)
class IntentDecision(BaseIntentDecision):
    """Typed result from intent and complexity routing."""

    difficulty: str
    tools: list[str] = field(default_factory=list)
    llm_trace: dict[str, Any] = field(default_factory=dict)
    deep_thinking: bool = False
    memory_route: str = "none"
    memory_query_hint: dict[str, Any] | None = None


@dataclass(slots=True)
class ChatParseOutcome:
    """Post-processing outcome for emitted chat results."""

    emitted: bool
    stored_history: bool
    memory_updated: bool
    tool_loop_recorded: bool
