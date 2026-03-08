"""Common contracts shared by task-agent execution pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, TypeAlias

from ....core.runtime.contracts import FactRecord
from ...orchestration import WorkerResult


class IncomingFactKind(str, Enum):
    """Normalized fact categories consumed by task-agent coordinators."""

    USER_MESSAGE = "user_message"
    WORKER_UPDATE = "worker_update"
    EXPLORE_TASK_COMPLETED = "explore_task_completed"
    EXPLORE_TASK_REQUEST = "explore_task_request"
    OTHER_FACT = "other_fact"


class ExecutionMode(str, Enum):
    """Execution paths supported by task agents."""

    FACT_ONLY = "fact_only"
    DIRECT_LLM = "direct_llm"
    FUNCTION_CALLING = "function_calling"
    ORCHESTRATION_LAUNCH = "orchestration_launch"
    ORCHESTRATION_UPDATE = "orchestration_update"
    EXPLORE_TASK_RENDER = "explore_task_render"


@dataclass(slots=True)
class OrchestrationPlan:
    """Structured orchestration plan chosen by intent routing."""

    mode: str = "direct"
    planner: str = "task_agent"
    default_leaf_type: str = "Explore"
    allow_parallel: bool = True
    route_to_explore_task_agent: bool = False

    def to_strategy_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "planner": self.planner,
            "default_leaf_type": self.default_leaf_type,
            "allow_parallel": self.allow_parallel,
        }


@dataclass(slots=True)
class ToolSelection:
    """Typed tool selection result."""

    tools: list[str] = field(default_factory=list)
    reasoning: str = ""


@dataclass(slots=True)
class GenericFactPayload:
    """Fallback payload wrapper for facts without a specialized contract."""

    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UserMessagePayload:
    """Typed payload for direct user-message facts."""

    user_id: str
    session_id: str
    message: str
    turn_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "message": self.message,
        }
        if self.turn_id is not None:
            payload["turn_id"] = self.turn_id
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, fallback_user_id: str) -> "UserMessagePayload":
        return cls(
            user_id=str(payload.get("user_id") or fallback_user_id),
            session_id=str(payload.get("session_id") or ""),
            message=str(payload.get("message") or "").strip(),
            turn_id=_optional_string(payload.get("turn_id")),
        )


@dataclass(slots=True)
class WorkerUpdatePayload:
    """Typed payload for worker progress/completion/failure facts."""

    user_id: str
    session_id: str
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

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "worker_id": self.worker_id,
            "stage": self.stage,
            "result_preview": self.result_preview,
        }
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
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, fallback_user_id: str) -> "WorkerUpdatePayload":
        worker_result = payload.get("worker_result")
        return cls(
            user_id=str(payload.get("user_id") or fallback_user_id),
            session_id=str(payload.get("session_id") or ""),
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
            worker_result=WorkerResult.from_dict(worker_result) if isinstance(worker_result, dict) else None,
            error=_optional_string(payload.get("error")),
            failure_reason=_optional_string(payload.get("failure_reason")),
        )


@dataclass(slots=True)
class ExploreTaskRequestPayload:
    """Typed payload for chat -> ExploreTaskAgent handoff."""

    user_id: str
    session_id: str
    message: str
    history_snapshot: list[dict[str, Any]] = field(default_factory=list)
    upstream_task_agent_type: str = "chat"
    upstream_task_agent_id: str = ""
    turn_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "message": self.message,
            "history_snapshot": list(self.history_snapshot),
            "upstream_task_agent_type": self.upstream_task_agent_type,
            "upstream_task_agent_id": self.upstream_task_agent_id,
        }
        if self.turn_id is not None:
            payload["turn_id"] = self.turn_id
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, fallback_user_id: str) -> "ExploreTaskRequestPayload":
        history_snapshot = payload.get("history_snapshot")
        return cls(
            user_id=str(payload.get("user_id") or fallback_user_id),
            session_id=str(payload.get("session_id") or ""),
            message=str(payload.get("message") or "").strip(),
            history_snapshot=history_snapshot if isinstance(history_snapshot, list) else [],
            upstream_task_agent_type=str(payload.get("upstream_task_agent_type") or "chat"),
            upstream_task_agent_id=str(payload.get("upstream_task_agent_id") or fallback_user_id),
            turn_id=_optional_string(payload.get("turn_id")),
        )


@dataclass(slots=True)
class ExploreTaskCompletedPayload:
    """Typed payload for ExploreTaskAgent -> chat dossier delivery."""

    user_id: str
    session_id: str
    root_user_message: str
    markdown_dossier: str
    orchestration_id: Optional[str] = None
    message_started_at: Optional[float] = None
    turn_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "root_user_message": self.root_user_message,
            "markdown_dossier": self.markdown_dossier,
        }
        if self.orchestration_id is not None:
            payload["orchestration_id"] = self.orchestration_id
        if self.message_started_at is not None:
            payload["message_started_at"] = self.message_started_at
        if self.turn_id is not None:
            payload["turn_id"] = self.turn_id
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, fallback_user_id: str) -> "ExploreTaskCompletedPayload":
        return cls(
            user_id=str(payload.get("user_id") or fallback_user_id),
            session_id=str(payload.get("session_id") or ""),
            root_user_message=str(payload.get("root_user_message") or payload.get("message") or "").strip(),
            markdown_dossier=str(payload.get("markdown_dossier") or "").strip(),
            orchestration_id=_optional_string(payload.get("orchestration_id")),
            message_started_at=_optional_float(payload.get("message_started_at")),
            turn_id=_optional_string(payload.get("turn_id")),
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


@dataclass(slots=True)
class BaseIntentDecision:
    """Common intent-routing result shared across task-agent pipelines."""

    intent: str
    execution_mode: ExecutionMode
    reasoning: str = ""
    orchestration_plan: Optional[OrchestrationPlan] = None


@dataclass(slots=True)
class ExecutionRequest:
    """Normalized request passed into an execution handler."""

    mode: ExecutionMode
    context: BaseRuntimeContext
    intent: BaseIntentDecision
    tool_selection: ToolSelection


@dataclass(slots=True)
class DirectLLMRequest(ExecutionRequest):
    """Typed request for direct LLM rendering."""

    prompt_context: Optional[dict[str, Any]] = None
    system_prompt: str = ""
    messages: list[dict[str, str]] = field(default_factory=list)
    disable_thinking: bool = True


@dataclass(slots=True)
class FunctionCallingRequest(ExecutionRequest):
    """Typed request for function-calling execution."""

    prompt_context: Optional[dict[str, Any]] = None
    system_prompt: str = ""
    selected_tools: list[str] = field(default_factory=list)
    disable_thinking: bool = True


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
class ExecutionResult:
    """Normalized execution result returned from a handler."""

    mode: ExecutionMode
    response_text: str = ""
    skip_emit: bool = False
    root_user_message: str = ""
    correlation_id: Optional[str] = None
    orchestration_id: Optional[str] = None
    message_started_at: Optional[float] = None
    turn_id: Optional[str] = None


@dataclass(slots=True)
class FunctionCallingExecutionResult(ExecutionResult):
    """Execution result carrying structured function-calling outcome details."""

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
