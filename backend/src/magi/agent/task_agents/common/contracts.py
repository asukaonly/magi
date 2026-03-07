"""Common contracts shared by task-agent execution pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


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
class ExecutionRequest:
    """Normalized request passed into an execution handler."""

    mode: ExecutionMode
    context: Any
    intent: Any
    tool_selection: ToolSelection
    prompt_payload: dict[str, Any] = field(default_factory=dict)
    tool_payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrchestrationLaunchRequest(ExecutionRequest):
    """Execution request for orchestration launch handlers."""


@dataclass(slots=True)
class OrchestrationUpdateRequest(ExecutionRequest):
    """Execution request for orchestration update handlers."""


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
    metadata: dict[str, Any] = field(default_factory=dict)
