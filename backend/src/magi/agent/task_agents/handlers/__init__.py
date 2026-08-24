"""Generic, domain-agnostic handlers shared by task-agent drivers."""

from .contracts import (
    ChatParseOutcome,
    ChatReplyContext,
    ChatRuntimeContext,
    IntentDecision,
)
from ..common import (
    AssistantResponsePlan,
    AssistantResponseSegment,
    ExecutionHandlerRegistry,
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    GenericFactPayload,
    IncomingFactKind,
    ToolSelection,
    UserMessagePayload,
)

__all__ = [
    "AssistantResponsePlan",
    "AssistantResponseSegment",
    "ChatParseOutcome",
    "ChatReplyContext",
    "ChatRuntimeContext",
    "ExecutionHandlerRegistry",
    "ExecutionMode",
    "ExecutionRequest",
    "ExecutionResult",
    "GenericFactPayload",
    "IncomingFactKind",
    "IntentDecision",
    "ToolSelection",
    "UserMessagePayload",
]
