"""Shared DTOs for function-calling execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..checkpoint import AgentRunCheckpoint


@dataclass
class ToolMessageBlock:
    """One protocol-complete assistant tool-call block plus its tool messages."""

    start: int
    end: int
    assistant_message: dict[str, Any]
    tool_messages: list[dict[str, Any]]


@dataclass
class ToolCall:
    """Represents a single tool call from LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolCallResult:
    """Result of a tool call execution."""

    tool_call_id: str
    tool_name: str
    success: bool
    data: Any = None
    error: str | None = None
    error_code: str | None = None
    execution_time: float = 0.0


@dataclass
class ExecutionOutcome:
    """Structured result for function-calling execution."""

    status: str
    content: str
    failure_reason: str | None = None
    error_text: str | None = None
    tool_failures: list[dict[str, Any]] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    message_payload: dict[str, Any] = field(default_factory=dict)
    context_usage: dict[str, Any] | None = None
    iterations: int = 0
    snapshot: "AgentRunCheckpoint | None" = None

    @property
    def succeeded(self) -> bool:
        return self.status == "completed"

    @property
    def detached(self) -> bool:
        return self.status == "detached"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "content": self.content,
            "failure_reason": self.failure_reason,
            "error_text": self.error_text,
            "tool_failures": list(self.tool_failures),
            "attachments": list(self.attachments),
            "message_payload": dict(self.message_payload),
            "context_usage": (
                dict(self.context_usage)
                if isinstance(self.context_usage, dict)
                else None
            ),
            "iterations": self.iterations,
            "snapshot": self.snapshot.to_dict() if self.snapshot is not None else None,
        }
