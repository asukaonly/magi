"""Chat task-agent support package — generic ring-2 handler framework.

The chat-specific module cluster (coordinator, prompt/fact/interruption
services, rhythm/streaming, run-store + session-run machinery) descended into
the chat layer (``magi.chat.task_agent.*``) in P2 Task 6. What remains here is
the generic, domain-agnostic ring-2 handler framework shared across task-agent
drivers.
"""

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
