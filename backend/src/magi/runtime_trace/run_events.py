"""Provider-neutral durable agent-run event contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentRunEventType(str, Enum):
    """Stable event names persisted by the agent runtime."""

    RUN_STARTED = "run_started"
    RUN_RESUMED = "run_resumed"
    CONTEXT_PREPARED = "context_prepared"
    STEP_STARTED = "step_started"
    REASONING_POLICY_RESOLVED = "reasoning_policy_resolved"
    REASONING_DEPTH_CHANGED = "reasoning_depth_changed"
    MODEL_OUTPUT = "model_output"
    TOOL_CALL_REQUESTED = "tool_call_requested"
    TOOL_EFFECT_ADMITTED = "tool_effect_admitted"
    TOOL_RESULT = "tool_result"
    CHILD_STARTED = "child_started"
    CHILD_COMPLETED = "child_completed"
    CHILD_CANCELLED = "child_cancelled"
    CAPABILITIES_RESOLVED = "capabilities_resolved"
    CAPABILITIES_EXPANDED = "capabilities_expanded"
    ATTACHMENT_OBSERVED = "attachment_observed"
    CONTROL_RECEIVED = "control_received"
    PLAN_UPDATED = "plan_updated"
    VALIDATION_COMPLETED = "validation_completed"
    COMPLETION_REQUESTED = "completion_requested"
    COMPLETION_REJECTED = "completion_rejected"
    REPAIR_STARTED = "repair_started"
    REPAIR_STEP_STARTED = "repair_step_started"
    REPAIR_EXHAUSTED = "repair_exhausted"
    RUN_SUSPENDED = "run_suspended"
    RUN_BLOCKED = "run_blocked"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"


@dataclass(frozen=True, slots=True)
class AgentRunEvent:
    """One append-only event in the canonical run journal."""

    event_id: str
    run_id: str
    sequence: int
    event_type: AgentRunEventType
    created_at_ms: int
    turn_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    step_index: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "created_at_ms": self.created_at_ms,
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "step_index": self.step_index,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentRunEvent":
        return cls(
            event_id=str(value["event_id"]),
            run_id=str(value["run_id"]),
            sequence=int(value["sequence"]),
            event_type=AgentRunEventType(str(value["event_type"])),
            created_at_ms=int(value["created_at_ms"]),
            turn_id=_optional_text(value.get("turn_id")),
            session_id=_optional_text(value.get("session_id")),
            user_id=_optional_text(value.get("user_id")),
            step_index=(
                int(value["step_index"])
                if value.get("step_index") is not None
                else None
            ),
            payload=dict(value.get("payload") or {}),
        )


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


__all__ = ["AgentRunEvent", "AgentRunEventType"]
