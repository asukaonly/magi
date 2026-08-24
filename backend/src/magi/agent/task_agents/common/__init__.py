"""Common execution building blocks shared by task agents."""

from .contracts import (
    AssistantResponsePlan,
    AssistantResponseSegment,
    BaseIntentDecision,
    BaseRuntimeContext,
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    AgentRunExecutionResult,
    PreparedAgentRunRequest,
    GenericFactPayload,
    IncomingFactKind,
    RhythmPersonaSignal,
    TaskFactPayload,
    ToolSelection,
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
    "BaseIntentDecision",
    "BaseRuntimeContext",
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
    "ToolSelection",
    "UserMessagePayload",
]
