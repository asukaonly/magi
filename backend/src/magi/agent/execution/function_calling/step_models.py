"""Shared models for one function-calling execution step."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..evidence import ToolExecutionEvidence
from ..journal import AgentRunJournal
from ..reasoning import ReasoningPolicy, ReasoningState
from ..run_plan_port import RunPlanReader


@dataclass(slots=True)
class FunctionCallingStepState:
    """Mutable loop state shared across bounded function-calling steps."""

    messages: list[dict[str, Any]]
    effective_system_prompt: str
    tools: list[dict[str, Any]]
    selected_tool_names: list[str] = field(default_factory=list)
    iteration: int = 0
    tool_failures: list[dict[str, Any]] = field(default_factory=list)
    chat_attachments: list[dict[str, Any]] = field(default_factory=list)
    message_payload: dict[str, Any] = field(default_factory=dict)
    allow_attachment_grounding: bool = False
    tool_expansion_count: int = 0
    consecutive_failed_tool_iterations: int = 0
    all_tools_failed: bool = False
    failed_tool_call_fingerprints: set[str] = field(default_factory=set)
    failure_signature_counts: dict[str, int] = field(default_factory=dict)
    repeated_blocker_tool_names: set[str] = field(default_factory=set)
    suppressed_tool_names: set[str] = field(default_factory=set)
    ephemeral_context_message_index: int | None = None
    ephemeral_context_original_content: Any | None = None
    latest_context_usage: dict[str, Any] | None = None
    tool_evidence: list[ToolExecutionEvidence] = field(default_factory=list)
    repair_iterations: int = 0
    journal: AgentRunJournal | None = None
    run_id: str = ""
    reasoning_policy: ReasoningPolicy | None = None
    reasoning_state: ReasoningState | None = None
    persona_task_clamp_applied: bool = False
    run_plan_reader: RunPlanReader | None = None


@dataclass(slots=True)
class FunctionCallingStepOutcome:
    """Result of executing one bounded function-calling step."""

    status: str
    iteration: int
    content: str = ""
    failure_reason: str | None = None
    error_text: str | None = None


@dataclass(slots=True)
class StepExecutionContext:
    """Stable context for one function-calling loop step."""

    user_message: str
    user_id: str
    session_id: str | None
    run_id: str
    run_revision: int
    turn_id: str | None
    execution_preset: str
    execution_agent_id: str
    execution_workspace: str | None
