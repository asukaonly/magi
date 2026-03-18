"""Normalized contracts for persisted chat trace nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TURN_TRACE_STARTED_EVENT_TYPE = "TURN_TRACE_STARTED"
TURN_TRACE_COMPLETED_EVENT_TYPE = "TURN_TRACE_COMPLETED"
TURN_TRACE_FAILED_EVENT_TYPE = "TURN_TRACE_FAILED"
TRACE_NODE_STARTED_EVENT_TYPE = "TRACE_NODE_STARTED"
TRACE_NODE_COMPLETED_EVENT_TYPE = "TRACE_NODE_COMPLETED"
TRACE_NODE_FAILED_EVENT_TYPE = "TRACE_NODE_FAILED"


@dataclass(slots=True)
class TraceNodePayload:
    """Canonical payload stored for one traceable runtime node."""

    trace_id: str
    turn_id: str
    span_id: str
    parent_span_id: str | None
    node_type: str
    name: str
    status: str
    attempt_index: int = 1
    retry_count: int = 0
    started_at_ms: int | None = None
    ended_at_ms: int | None = None
    duration_ms: int | None = None
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    tags: dict[str, Any] = field(default_factory=dict)

    def to_event_payload(self) -> dict[str, Any]:
        """Return a transport-safe dictionary for runtime event persistence."""
        return {
            "trace_id": self.trace_id,
            "turn_id": self.turn_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "node_type": self.node_type,
            "name": self.name,
            "status": self.status,
            "attempt_index": int(self.attempt_index),
            "retry_count": int(self.retry_count),
            "started_at_ms": self.started_at_ms,
            "ended_at_ms": self.ended_at_ms,
            "duration_ms": self.duration_ms,
            "input": dict(self.input),
            "output": dict(self.output),
            "metrics": dict(self.metrics),
            "error": dict(self.error) if isinstance(self.error, dict) else self.error,
            "tags": dict(self.tags),
        }
