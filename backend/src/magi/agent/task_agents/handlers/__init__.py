"""Generic, domain-agnostic handlers shared by task-agent drivers."""

from .contracts import (
    ChatParseOutcome,
    ChatReplyContext,
    ChatRuntimeContext,
    TurnAdmissionDecision,
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
    CapabilitySelection,
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
    "TurnAdmissionDecision",
    "CapabilitySelection",
    "UserMessagePayload",
]
