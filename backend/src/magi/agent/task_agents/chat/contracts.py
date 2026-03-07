"""Typed contracts for the chat task-agent pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ....core.runtime.contracts import FactRecord
from ..common import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    IncomingFactKind,
    OrchestrationPlan,
    ToolSelection,
)


@dataclass(slots=True)
class ChatRuntimeContext:
    """Fully built runtime context for a chat task-agent turn."""

    latest_fact: Optional[FactRecord]
    recent_facts: list[FactRecord]
    batch_facts: list[FactRecord]
    agent_id: str
    agent_type: str
    runtime_key: str
    user_id: str
    session_id: str
    history_key: str
    history: list[dict[str, Any]]
    conversation_history: list[dict[str, Any]]
    active_orchestrations: list[dict[str, Any]]
    latest_user_message: str
    incoming_fact_kind: IncomingFactKind
    latest_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class IntentDecision:
    """Typed result from intent and complexity routing."""

    intent: str
    difficulty: str
    execution_mode: ExecutionMode
    tools: list[str] = field(default_factory=list)
    deep_thinking: bool = False
    reasoning: str = ""
    orchestration_plan: Optional[OrchestrationPlan] = None


@dataclass(slots=True)
class ChatParseOutcome:
    """Post-processing outcome for emitted chat results."""

    emitted: bool
    stored_history: bool
    memory_updated: bool
    tool_loop_recorded: bool
