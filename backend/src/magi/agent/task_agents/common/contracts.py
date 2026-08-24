"""Common contracts shared by task-agent execution pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, TypeAlias

from ....agent.runtime.contracts import FactRecord
from ....events.first_context import (
    FIRST_CONTEXT_STORY_INTERACTION_KIND,
    first_context_from_metadata,
)
from ....events.recall_feedback import RecallFeedbackRequest
from ...execution.reasoning import ReasoningPolicy
from magi.skills.allowed_tools_rules import ToolRule


class IncomingFactKind(str, Enum):
    """Normalized fact categories consumed by task-agent coordinators."""

    USER_MESSAGE = "user_message"
    OTHER_FACT = "other_fact"


class ExecutionMode(str, Enum):
    """Deterministic domain-event handlers outside the ordinary agent run."""

    FACT_ONLY = "fact_only"


@dataclass(slots=True)
class CapabilitySelection:
    """Capabilities exposed to one admitted execution."""

    tools: list[str] = field(default_factory=list)
    reasoning: str = ""
    task_hint: dict[str, Any] = field(default_factory=dict)
    recommended_tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class GenericFactPayload:
    """Fallback payload wrapper for facts without a specialized contract."""

    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UserMessagePayload:
    """Typed payload for direct user-message facts.

    ``source`` carries the ingress channel name so the session coordinator can
    bind the resulting run trigger to its originating transport. Direct API
    ingress uses ``"api"``.
    """

    user_id: str
    session_id: str
    content: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    workspace_path: Optional[str] = None
    turn_id: Optional[str] = None
    reply_to_message_id: Optional[str] = None
    recall_feedback: RecallFeedbackRequest | None = None
    interaction_kind: str | None = None
    first_context: dict[str, str] | None = None
    reasoning_preference: str | None = None
    skill_invocation: dict[str, Any] | None = None
    run_disposition: str = "message"
    source: str = "api"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "content": self.content,
            "attachments": list(self.attachments),
            "source": self.source,
        }
        if self.workspace_path is not None:
            payload["workspace_path"] = self.workspace_path
        if self.turn_id is not None:
            payload["turn_id"] = self.turn_id
        if self.reply_to_message_id is not None:
            payload["reply_to_message_id"] = self.reply_to_message_id
        if self.recall_feedback is not None:
            payload["recall_feedback"] = self.recall_feedback.to_dict()
        if self.interaction_kind is not None and self.first_context is not None:
            payload["interaction_kind"] = self.interaction_kind
            payload["first_context"] = dict(self.first_context)
        if self.reasoning_preference is not None:
            payload["reasoning_preference"] = self.reasoning_preference
        if self.skill_invocation is not None:
            payload["skill_invocation"] = dict(self.skill_invocation)
        if self.run_disposition != "message":
            payload["run_disposition"] = self.run_disposition
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, fallback_user_id: str) -> "UserMessagePayload":
        raw_metadata = payload.get("metadata")
        metadata: dict[str, Any] = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        raw_attachments = payload.get("attachments")
        attachments = (
            [dict(item) for item in raw_attachments if isinstance(item, dict)]
            if isinstance(raw_attachments, list)
            else []
        )
        raw_source = payload.get("source")
        normalized_first_context = first_context_from_metadata(
            {
                "interaction_kind": payload.get("interaction_kind")
                or metadata.get("interaction_kind"),
                "first_context": payload.get("first_context") or metadata.get("first_context"),
            }
        )
        return cls(
            user_id=str(payload.get("user_id") or fallback_user_id),
            session_id=str(payload.get("session_id") or ""),
            content=str(payload.get("content") or "").strip(),
            attachments=attachments,
            workspace_path=_optional_string(payload.get("workspace_path")),
            turn_id=_optional_string(payload.get("turn_id")),
            reply_to_message_id=(
                _optional_string(payload.get("reply_to_message_id"))
                or _optional_string(metadata.get("reply_to_message_id"))
            ),
            recall_feedback=RecallFeedbackRequest.from_value(
                payload.get("recall_feedback") or metadata.get("recall_feedback")
            ),
            interaction_kind=(
                FIRST_CONTEXT_STORY_INTERACTION_KIND
                if normalized_first_context is not None
                else None
            ),
            first_context=normalized_first_context,
            reasoning_preference=_optional_string(
                payload.get("reasoning_preference") or metadata.get("reasoning_preference")
            ),
            skill_invocation=_optional_dict(
                payload.get("skill_invocation") or metadata.get("skill_invocation")
            ),
            run_disposition=str(
                payload.get("run_disposition")
                or metadata.get("run_disposition")
                or "message"
            ).strip().lower(),
            source=str(raw_source) if raw_source else "api",
        )


TaskFactPayload: TypeAlias = GenericFactPayload | UserMessagePayload


@dataclass(slots=True)
class BaseRuntimeContext:
    """Common runtime context fields shared across task-agent pipelines."""

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
    latest_user_message: str
    incoming_fact_kind: IncomingFactKind
    latest_payload: TaskFactPayload = field(default_factory=GenericFactPayload)
    user_message_generation: Optional[int] = None


@dataclass(slots=True)
class BaseAdmissionDecision:
    """Deterministic fact-admission result shared across task agents."""

    run_kind: str
    execution_mode: ExecutionMode | None
    reasoning: str = ""


@dataclass(slots=True)
class ExecutionRequest:
    """Normalized request passed into an execution handler."""

    mode: ExecutionMode | None
    context: BaseRuntimeContext
    admission: BaseAdmissionDecision
    capabilities: CapabilitySelection


@dataclass(slots=True)
class PreparedAgentRunRequest(ExecutionRequest):
    """Chat-prepared inputs used to build the engine-level AgentRunRequest."""

    prompt_context: Optional[dict[str, Any]] = None
    system_prompt: str = ""
    selected_tools: list[str] = field(default_factory=list)
    reasoning_policy: ReasoningPolicy = field(default_factory=ReasoningPolicy)
    context_sources: tuple[dict[str, Any], ...] = ()
    skill_preapproval_rules: tuple[ToolRule, ...] = ()


@dataclass(slots=True)
class AssistantResponseSegment:
    """One visible assistant message in a presentation plan."""

    content: str
    intent: str = "answer"
    delay_ms: int = 0
    segment_index: int = 0
    source_unit_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AssistantResponsePlan:
    """Presentation plan for rendering one canonical answer as messages."""

    mode: str = "single"
    aggregate_text: str = ""
    segments: list[AssistantResponseSegment] = field(default_factory=list)


@dataclass(slots=True)
class RhythmPersonaSignal:
    """Per-turn persona signals consumed by the conversation rhythm planner."""

    register: str = "casual"
    persona_intensity: int = 1
    sentence_style: str = ""
    chattiness: float = (
        0.5  # baseline conversational verbosity; drives rhythm pacing via _rhythm_level
    )


@dataclass(slots=True)
class ExecutionResult:
    """Normalized execution result returned from a handler."""

    mode: ExecutionMode | None
    response_text: str = ""
    response_plan: Optional[AssistantResponsePlan] = None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    message_payload: dict[str, Any] = field(default_factory=dict)
    skip_emit: bool = False
    root_user_message: str = ""
    correlation_id: Optional[str] = None
    message_started_at: Optional[float] = None
    turn_id: Optional[str] = None
    llm_trace: dict[str, Any] = field(default_factory=dict)
    context_usage: dict[str, Any] | None = None
    ux_plan: Optional[dict[str, Any]] = None
    streamed: bool = False
    persona_rhythm: Optional["RhythmPersonaSignal"] = None


@dataclass(slots=True)
class AgentRunExecutionResult(ExecutionResult):
    """Execution result carrying the structured unified-loop outcome."""

    execution_outcome: dict[str, Any] = field(default_factory=dict)


def _optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_dict(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None
