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
from ...orchestration_plan import OrchestrationPlan
from ...execution.reasoning import ReasoningPolicy
from ...orchestration import WorkerResult


class IncomingFactKind(str, Enum):
    """Normalized fact categories consumed by task-agent coordinators."""

    USER_MESSAGE = "user_message"
    WORKER_UPDATE = "worker_update"
    EXPLORE_TASK_COMPLETED = "explore_task_completed"
    EXPLORE_TASK_FAILED = "explore_task_failed"
    EXPLORE_TASK_REQUEST = "explore_task_request"
    OTHER_FACT = "other_fact"


class ExecutionMode(str, Enum):
    """Deterministic domain-event handlers outside the ordinary agent run."""

    FACT_ONLY = "fact_only"
    ORCHESTRATION_LAUNCH = "orchestration_launch"
    ORCHESTRATION_UPDATE = "orchestration_update"
    EXPLORE_TASK_RENDER = "explore_task_render"


@dataclass(slots=True)
class ToolSelection:
    """Typed tool selection result."""

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

    Phase H+1: ``source`` carries the dispatcher channel name
    (``"api"`` for HTTP /chat, ``"telegram"`` / ``"weixin"`` for plugins,
    etc.) so :class:`SessionRunCoordinator` can tag the resulting
    :class:`RunTrigger` accordingly. Defaults to ``"api"`` for backward
    compatibility with legacy payloads that pre-date this field.
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
                payload.get("reasoning_preference")
                or metadata.get("reasoning_preference")
            ),
            source=str(raw_source) if raw_source else "api",
        )


@dataclass(slots=True)
class WorkerUpdatePayload:
    """Typed payload for worker progress/completion/failure facts."""

    user_id: str
    session_id: str
    run_id: Optional[str] = None
    run_revision: int = 0
    turn_id: Optional[str] = None
    worker_id: str = ""
    stage: str = ""
    orchestration_id: Optional[str] = None
    subtask_id: Optional[str] = None
    worker_subagent_type: Optional[str] = None
    worker_description: Optional[str] = None
    result_preview: str = ""
    worker_result: Optional[WorkerResult] = None
    error: Optional[str] = None
    failure_reason: Optional[str] = None
    error_text: Optional[str] = None
    tool_failures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "run_revision": self.run_revision,
            "worker_id": self.worker_id,
            "stage": self.stage,
            "result_preview": self.result_preview,
        }
        if self.run_id is not None:
            payload["run_id"] = self.run_id
        if self.turn_id is not None:
            payload["turn_id"] = self.turn_id
        if self.orchestration_id is not None:
            payload["orchestration_id"] = self.orchestration_id
        if self.subtask_id is not None:
            payload["subtask_id"] = self.subtask_id
        if self.worker_subagent_type is not None:
            payload["worker_subagent_type"] = self.worker_subagent_type
        if self.worker_description is not None:
            payload["worker_description"] = self.worker_description
        if self.worker_result is not None:
            payload["worker_result"] = self.worker_result.to_dict()
        if self.error is not None:
            payload["error"] = self.error
        if self.failure_reason is not None:
            payload["failure_reason"] = self.failure_reason
        if self.error_text is not None:
            payload["error_text"] = self.error_text
        if self.tool_failures:
            payload["tool_failures"] = list(self.tool_failures)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, fallback_user_id: str) -> "WorkerUpdatePayload":
        worker_result = payload.get("worker_result")
        raw_tool_failures = payload.get("tool_failures")
        return cls(
            user_id=str(payload.get("user_id") or fallback_user_id),
            session_id=str(payload.get("session_id") or ""),
            run_id=_optional_string(payload.get("run_id")),
            run_revision=_optional_int(payload.get("run_revision")) or 0,
            turn_id=_optional_string(payload.get("turn_id")),
            worker_id=str(payload.get("worker_id") or ""),
            stage=str(payload.get("stage") or ""),
            orchestration_id=_optional_string(payload.get("orchestration_id")),
            subtask_id=_optional_string(payload.get("subtask_id")),
            worker_subagent_type=_optional_string(
                payload.get("worker_subagent_type") or payload.get("subagent_type")
            ),
            worker_description=_optional_string(
                payload.get("worker_description") or payload.get("description")
            ),
            result_preview=str(payload.get("result_preview") or "").strip(),
            worker_result=WorkerResult.from_dict(worker_result)
            if isinstance(worker_result, dict)
            else None,
            error=_optional_string(payload.get("error")),
            failure_reason=_optional_string(payload.get("failure_reason")),
            error_text=_optional_string(payload.get("error_text")),
            tool_failures=[
                dict(item)
                for item in (raw_tool_failures if isinstance(raw_tool_failures, list) else [])
                if isinstance(item, dict)
            ],
        )


@dataclass(slots=True)
class ExploreTaskRequestPayload:
    """Typed payload for chat -> ExploreTaskAgent handoff."""

    user_id: str
    session_id: str
    content: str
    run_id: Optional[str] = None
    run_revision: int = 0
    history_snapshot: list[dict[str, Any]] = field(default_factory=list)
    upstream_task_agent_type: str = "chat"
    upstream_task_agent_id: str = ""
    turn_id: Optional[str] = None
    root_turn_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "content": self.content,
            "run_revision": self.run_revision,
            "history_snapshot": list(self.history_snapshot),
            "upstream_task_agent_type": self.upstream_task_agent_type,
            "upstream_task_agent_id": self.upstream_task_agent_id,
        }
        if self.run_id is not None:
            payload["run_id"] = self.run_id
        if self.turn_id is not None:
            payload["turn_id"] = self.turn_id
        if self.root_turn_id is not None:
            payload["root_turn_id"] = self.root_turn_id
        return payload

    @classmethod
    def from_dict(
        cls, payload: dict[str, Any], *, fallback_user_id: str
    ) -> "ExploreTaskRequestPayload":
        history_snapshot = payload.get("history_snapshot")
        return cls(
            user_id=str(payload.get("user_id") or fallback_user_id),
            session_id=str(payload.get("session_id") or ""),
            content=str(payload.get("content") or "").strip(),
            run_id=_optional_string(payload.get("run_id")),
            run_revision=_optional_int(payload.get("run_revision")) or 0,
            history_snapshot=history_snapshot if isinstance(history_snapshot, list) else [],
            upstream_task_agent_type=str(payload.get("upstream_task_agent_type") or "chat"),
            upstream_task_agent_id=str(payload.get("upstream_task_agent_id") or fallback_user_id),
            turn_id=_optional_string(payload.get("turn_id")),
            root_turn_id=_optional_string(payload.get("root_turn_id")),
        )


@dataclass(slots=True)
class ExploreTaskCompletedPayload:
    """Typed payload for ExploreTaskAgent -> chat dossier delivery."""

    user_id: str
    session_id: str
    root_user_message: str
    markdown_dossier: str
    run_id: Optional[str] = None
    run_revision: int = 0
    orchestration_id: Optional[str] = None
    message_started_at: Optional[float] = None
    turn_id: Optional[str] = None
    root_turn_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "root_user_message": self.root_user_message,
            "markdown_dossier": self.markdown_dossier,
            "run_revision": self.run_revision,
        }
        if self.run_id is not None:
            payload["run_id"] = self.run_id
        if self.orchestration_id is not None:
            payload["orchestration_id"] = self.orchestration_id
        if self.message_started_at is not None:
            payload["message_started_at"] = self.message_started_at
        if self.turn_id is not None:
            payload["turn_id"] = self.turn_id
        if self.root_turn_id is not None:
            payload["root_turn_id"] = self.root_turn_id
        return payload

    @classmethod
    def from_dict(
        cls, payload: dict[str, Any], *, fallback_user_id: str
    ) -> "ExploreTaskCompletedPayload":
        return cls(
            user_id=str(payload.get("user_id") or fallback_user_id),
            session_id=str(payload.get("session_id") or ""),
            root_user_message=str(payload.get("root_user_message") or "").strip(),
            markdown_dossier=str(payload.get("markdown_dossier") or "").strip(),
            run_id=_optional_string(payload.get("run_id")),
            run_revision=_optional_int(payload.get("run_revision")) or 0,
            orchestration_id=_optional_string(payload.get("orchestration_id")),
            message_started_at=_optional_float(payload.get("message_started_at")),
            turn_id=_optional_string(payload.get("turn_id")),
            root_turn_id=_optional_string(payload.get("root_turn_id")),
        )


TaskFactPayload: TypeAlias = (
    GenericFactPayload
    | UserMessagePayload
    | WorkerUpdatePayload
    | ExploreTaskRequestPayload
    | ExploreTaskCompletedPayload
)


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
class BaseIntentDecision:
    """Deterministic fact-admission result shared across task agents."""

    intent: str
    execution_mode: ExecutionMode | None
    reasoning: str = ""
    orchestration_plan: OrchestrationPlan | None = None


@dataclass(slots=True)
class ExecutionRequest:
    """Normalized request passed into an execution handler."""

    mode: ExecutionMode | None
    context: BaseRuntimeContext
    intent: BaseIntentDecision
    tool_selection: ToolSelection


@dataclass(slots=True)
class PreparedAgentRunRequest(ExecutionRequest):
    """Chat-prepared inputs used to build the engine-level AgentRunRequest."""

    prompt_context: Optional[dict[str, Any]] = None
    system_prompt: str = ""
    selected_tools: list[str] = field(default_factory=list)
    reasoning_policy: ReasoningPolicy = field(default_factory=ReasoningPolicy)
    context_sources: tuple[dict[str, Any], ...] = ()


@dataclass(slots=True)
class OrchestrationLaunchRequest(ExecutionRequest):
    """Execution request for orchestration launch handlers."""

    correlation_id: Optional[str] = None


@dataclass(slots=True)
class OrchestrationUpdateRequest(ExecutionRequest):
    """Execution request for orchestration update handlers."""


@dataclass(slots=True)
class ExploreRenderRequest(ExecutionRequest):
    """Typed request for chat-side Explore dossier rendering."""

    markdown_dossier: str = ""
    root_user_message: str = ""
    message_started_at: Optional[float] = None
    orchestration_id: Optional[str] = None


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
    orchestration_id: Optional[str] = None
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


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
