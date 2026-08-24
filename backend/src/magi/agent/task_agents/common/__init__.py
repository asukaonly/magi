"""Common execution building blocks shared by task agents."""

from .contracts import (
    AssistantResponsePlan,
    AssistantResponseSegment,
    BaseAdmissionDecision,
    BaseRuntimeContext,
    CapabilitySelection,
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    AgentRunExecutionResult,
    PreparedAgentRunRequest,
    GenericFactPayload,
    IncomingFactKind,
    RhythmPersonaSignal,
    TaskFactPayload,
    UserMessagePayload,
)
from .handlers import (
    BaseExecutionHandler,
    CommonHandlerDependencies,
    ExecutionHandler,
    ExecutionHandlerRegistry,
    FactOnlyHandler,
)
from .llm_service import TaskAgentLLMService

__all__ = [
    "AssistantResponsePlan",
    "AssistantResponseSegment",
    "BaseExecutionHandler",
    "BaseAdmissionDecision",
    "BaseRuntimeContext",
    "CapabilitySelection",
    "CommonHandlerDependencies",
    "ExecutionHandler",
    "ExecutionHandlerRegistry",
    "ExecutionMode",
    "ExecutionRequest",
    "ExecutionResult",
    "FactOnlyHandler",
    "AgentRunExecutionResult",
    "PreparedAgentRunRequest",
    "GenericFactPayload",
    "IncomingFactKind",
    "RhythmPersonaSignal",
    "TaskFactPayload",
    "TaskAgentLLMService",
    "UserMessagePayload",
]
