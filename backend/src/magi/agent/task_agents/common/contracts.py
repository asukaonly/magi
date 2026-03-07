"""Common contracts shared by task-agent execution pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from ....core.runtime.contracts import FactRecord


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
    latest_payload: dict[str, Any] = field(default_factory=dict)


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


@dataclass(slots=True)
class FunctionCallingExecutionResult(ExecutionResult):
    """Execution result carrying structured function-calling outcome details."""

    execution_outcome: dict[str, Any] = field(default_factory=dict)
