"""Producer-agnostic contracts for the proactive outreach layer."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from magi_plugin_sdk.channels import ChannelTarget


class OutreachKind(str, Enum):
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    # v2: HEARTBEAT, CLARIFICATION, INSIGHT


class Urgency(str, Enum):
    NORMAL = "normal"
    HIGH = "high"


class GovernorVerdict(str, Enum):
    PUSH_NOW = "push_now"
    DEFER = "defer"
    DROP = "drop"


@dataclass(frozen=True, slots=True)
class OutreachIntent:
    """Something magi wants to say to the user, unprompted.

    Surface-agnostic: where it lands is decided downstream by the
    TargetResolver. ``payload`` is an opaque, producer-owned dict carried
    verbatim to the desktop transcript row (preserves parity).
    """

    kind: OutreachKind
    user_id: str
    origin_session_id: str | None
    title: str
    facts: str
    correlation_id: str
    completed_at_ms: int
    pending_message_id: str | None = None
    urgency: Urgency = Urgency.NORMAL
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "user_id": self.user_id,
            "origin_session_id": self.origin_session_id,
            "title": self.title,
            "facts": self.facts,
            "correlation_id": self.correlation_id,
            "completed_at_ms": int(self.completed_at_ms),
            "pending_message_id": self.pending_message_id,
            "urgency": self.urgency.value,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OutreachIntent":
        return cls(
            kind=OutreachKind(data["kind"]),
            user_id=str(data["user_id"]),
            origin_session_id=data.get("origin_session_id"),
            title=str(data.get("title") or ""),
            facts=str(data.get("facts") or ""),
            correlation_id=str(data["correlation_id"]),
            completed_at_ms=int(data.get("completed_at_ms") or 0),
            pending_message_id=data.get("pending_message_id"),
            urgency=Urgency(data.get("urgency") or Urgency.NORMAL.value),
            payload=dict(data.get("payload") or {}),
        )


@dataclass(frozen=True, slots=True)
class ResolvedTargets:
    desktop_session_id: str | None = None
    external: ChannelTarget | None = None
