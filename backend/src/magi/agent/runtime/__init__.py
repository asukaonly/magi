"""Agent runtime orchestration primitives."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .contracts import FactRecord
from .types import CHAT_AGENT_ID, TaskAgentType, build_task_agent_key

if TYPE_CHECKING:
    from .agent_runtime import AgentRuntime
    from .router_agent import RouterAgent
    from .task_agent import (
        TaskAgent,
        TaskAgentAdmissionDecision,
        TaskAgentCapabilitySelection,
        TaskAgentExecutionRequest,
        TaskAgentRuntimeContext,
    )
    from .task_agent_manager import TaskAgentManager

__all__ = [
    "FactRecord",
    "CHAT_AGENT_ID",
    "TaskAgentType",
    "build_task_agent_key",
    "AgentRuntime",
    "RouterAgent",
    "TaskAgent",
    "TaskAgentRuntimeContext",
    "TaskAgentAdmissionDecision",
    "TaskAgentCapabilitySelection",
    "TaskAgentExecutionRequest",
    "TaskAgentManager",
]


def __getattr__(name: str) -> Any:
    if name == "AgentRuntime":
        from .agent_runtime import AgentRuntime

        return AgentRuntime
    if name == "RouterAgent":
        from .router_agent import RouterAgent

        return RouterAgent
    if name == "TaskAgentManager":
        from .task_agent_manager import TaskAgentManager

        return TaskAgentManager
    if name in {
        "TaskAgent",
        "TaskAgentAdmissionDecision",
        "TaskAgentCapabilitySelection",
        "TaskAgentExecutionRequest",
        "TaskAgentRuntimeContext",
    }:
        from .task_agent import (
            TaskAgent,
            TaskAgentAdmissionDecision,
            TaskAgentCapabilitySelection,
            TaskAgentExecutionRequest,
            TaskAgentRuntimeContext,
        )

        mapping = {
            "TaskAgent": TaskAgent,
            "TaskAgentAdmissionDecision": TaskAgentAdmissionDecision,
            "TaskAgentCapabilitySelection": TaskAgentCapabilitySelection,
            "TaskAgentExecutionRequest": TaskAgentExecutionRequest,
            "TaskAgentRuntimeContext": TaskAgentRuntimeContext,
        }
        return mapping[name]
    raise AttributeError(name)
