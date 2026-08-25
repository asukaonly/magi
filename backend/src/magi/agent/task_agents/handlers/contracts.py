"""Typed contracts for the chat task-agent pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ....agent.runtime.contracts import FactRecord
from magi.control.run_control import RunControl, null_run_control
from ..common import (
    BaseAdmissionDecision,
    BaseRuntimeContext,
    GenericFactPayload,
    IncomingFactKind,
    TaskFactPayload,
)
from .run_contracts import AgentRun
from ...execution.capability_resolver import CapabilityResolution
from ...execution.reasoning import ReasoningPreference


class AssistantSurfaceMode(str, Enum):
    """How the assistant should surface this turn in chat UI."""

    NONE = "none"
    REACTION_ONLY = "reaction_only"
    FINAL_ONLY = "final_only"
    INTERIM_THEN_FINAL = "interim_then_final"


class ThinkingIndicatorMode(str, Enum):
    """How prominently chat should show an in-progress indicator."""

    HIDDEN = "hidden"
    SUBTLE = "subtle"
    VISIBLE = "visible"


class TraceDisplayMode(str, Enum):
    """How tool-chain and execution trace should appear in chat."""

    NONE = "none"
    COLLAPSIBLE = "collapsible"
    PROMINENT = "prominent"


@dataclass(slots=True)
class TurnUXPlan:
    """Presentation-facing policy for one admitted turn."""

    assistant_surface_mode: AssistantSurfaceMode = AssistantSurfaceMode.FINAL_ONLY
    thinking_indicator: ThinkingIndicatorMode = ThinkingIndicatorMode.HIDDEN
    trace_display_mode: TraceDisplayMode = TraceDisplayMode.NONE
    allow_trace_collapse: bool = False
    interim_text: str | None = None
    reaction_style: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the UX plan for notifications and transport payloads."""
        payload: dict[str, Any] = {
            "assistant_surface_mode": self.assistant_surface_mode.value,
            "thinking_indicator": self.thinking_indicator.value,
            "trace_display_mode": self.trace_display_mode.value,
            "allow_trace_collapse": self.allow_trace_collapse,
        }
        if self.interim_text is not None:
            payload["interim_text"] = self.interim_text
        if self.reaction_style is not None:
            payload["reaction_style"] = self.reaction_style
        return payload


@dataclass(slots=True, kw_only=True)
class ChatRuntimeContext(BaseRuntimeContext):
    """Fully built runtime context for a chat task-agent turn."""

    conversation_history: list[dict[str, Any]]
    recent_tool_errors: list[dict[str, Any]] = field(default_factory=list)
    recent_tool_state: list[dict[str, Any]] = field(default_factory=list)
    active_run: AgentRun | None = None
    session_run_id: str | None = None
    session_run_revision: int = 0
    session_run_disposition: str | None = None
    planner_fact: FactRecord | None = None
    planner_fact_kind: IncomingFactKind = IncomingFactKind.OTHER_FACT
    planner_payload: TaskFactPayload = field(default_factory=GenericFactPayload)
    reply_context: "ChatReplyContext | None" = None
    recall_feedback: "RecallFeedbackContext | None" = None
    session_summary: str | None = None
    model_context_revision: int = 0
    active_persona_id: str | None = None
    streaming_chat_enabled: bool = False
    allow_media_grounding_for_conversation: bool = False
    core_model_supports_vision: bool = False
    core_model_supports_tool_calls: bool = True
    control: RunControl = field(default_factory=null_run_control)


@dataclass(slots=True)
class ChatReplyContext:
    """Compact runtime context for one replied-to message."""

    message_id: str
    role: str
    content_excerpt: str
    is_explicit_reply: bool
    references_prior_turn: bool
    structured_payload: dict[str, Any] | None = None


@dataclass(slots=True)
class RecallFeedbackContext:
    """Resolved evidence and target for one turn-local recall correction."""

    kind: str
    target_message_id: str
    original_question: str
    previous_answer_excerpt: str
    recalled_memories: list[dict[str, Any]] = field(default_factory=list)
    recalled_memory_summary: dict[str, Any] | None = None
    finding_ref: str | None = None
    valid: bool = True
    error_code: str | None = None


@dataclass(slots=True, kw_only=True)
class TurnAdmissionDecision(BaseAdmissionDecision):
    """Domain admission plus unified-run policy for one chat fact."""

    ux_plan: TurnUXPlan = field(default_factory=TurnUXPlan)
    tools: list[str] = field(default_factory=list)
    task_hint: dict[str, Any] = field(default_factory=dict)
    reasoning_preference: ReasoningPreference = ReasoningPreference.AUTO
    capability_resolution: CapabilityResolution | None = None


@dataclass(slots=True)
class ChatParseOutcome:
    """Post-processing outcome for emitted chat results."""

    emitted: bool
    stored_history: bool
    memory_updated: bool
    tool_loop_recorded: bool
