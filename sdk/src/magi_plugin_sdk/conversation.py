"""Phase F: typed conversation content + events."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ContentBlock:
    """One typed fragment of a message.

    Phase F scope: ``kind="text"`` only. Phase I extends with
    ``image`` / ``code`` / ``tool_use`` / ``file`` variants.
    """
    kind: Literal["text"]
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text, "metadata": dict(self.metadata)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ContentBlock":
        return cls(
            kind=d.get("kind", "text"),
            text=str(d.get("text", "")),
            metadata=dict(d.get("metadata") or {}),
        )


EVENT_TYPES = frozenset({
    "user_message", "agent_reply", "tool_use_summary", "system_note",
    "message_redacted", "message_revised", "delivery_receipt",
})


@dataclass(frozen=True, slots=True)
class ConversationEvent:
    """One immutable event in a ConversationLog.

    Materialized history is a left-fold over these events with redaction
    + revision applied.
    """
    event_id: str
    event_type: str
    timestamp_ms: int
    actor: str
    content: list[ContentBlock] | None = None
    revises: str | None = None
    redacts: str | None = None
    triggered_run_id: str | None = None
    source_channel: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise ValueError(
                f"ConversationEvent.event_type must be one of {sorted(EVENT_TYPES)}, "
                f"got {self.event_type!r}"
            )
        if self.event_type == "message_redacted" and not self.redacts:
            raise ValueError("message_redacted requires `redacts` to reference the target event")
        if self.event_type == "message_revised":
            if not self.revises:
                raise ValueError("message_revised requires `revises`")
            if not self.content:
                raise ValueError("message_revised requires non-empty `content`")
        if self.event_type in {"user_message", "agent_reply", "tool_use_summary", "system_note"}:
            if not self.content:
                raise ValueError(f"{self.event_type} requires non-empty `content`")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp_ms": int(self.timestamp_ms),
            "actor": self.actor,
            "content": [b.to_dict() for b in self.content] if self.content else None,
            "revises": self.revises,
            "redacts": self.redacts,
            "triggered_run_id": self.triggered_run_id,
            "source_channel": self.source_channel,
            "metadata": dict(self.metadata),
        }


__all__ = ["ContentBlock", "ConversationEvent", "EVENT_TYPES"]
