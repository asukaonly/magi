"""Typed provenance shared by domain drivers and background runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RUN_TRIGGER_TYPES = frozenset({
    "user_message",          # user posted in chat
    "user_steer",            # user augmented an active run
    "user_retract",          # user retracted an earlier event (run is a recompute)
    "scheduled",             # scheduler fired
    "external_inbound",      # external channel (iMessage/Slack) delivered to us
    "sensor_event",          # filesystem/calendar/monitoring event
    "agent_self",            # agent's own callback / follow-up
    "child_run_completed",   # child run finished, parent should aggregate
    "background_resume",     # background executor resuming a detached run
    "batch",                 # batch driver launching a per-item run
})

RUN_TRIGGER_PRIORITIES = frozenset({"foreground", "background", "deferred"})


@dataclass(frozen=True, slots=True)
class RunTrigger:
    """Describes how / why a run was started.

    Carried on ``AgentRun.trigger`` so observability, delivery, and retract
    propagation can preserve provenance.
    """
    trigger_type: str
    source_channel: str | None
    requester: str
    priority: str
    correlation: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.trigger_type not in RUN_TRIGGER_TYPES:
            raise ValueError(
                f"RunTrigger.trigger_type must be one of {sorted(RUN_TRIGGER_TYPES)}, "
                f"got {self.trigger_type!r}"
            )
        if self.priority not in RUN_TRIGGER_PRIORITIES:
            raise ValueError(
                f"RunTrigger.priority must be one of {sorted(RUN_TRIGGER_PRIORITIES)}, "
                f"got {self.priority!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_type": self.trigger_type,
            "source_channel": self.source_channel,
            "requester": self.requester,
            "priority": self.priority,
            "correlation": list(self.correlation),
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunTrigger:
        return cls(
            trigger_type=d["trigger_type"],
            source_channel=d.get("source_channel"),
            requester=d["requester"],
            priority=d.get("priority", "foreground"),
            correlation=list(d.get("correlation") or []),
            payload=dict(d.get("payload") or {}),
        )


__all__ = ["RUN_TRIGGER_PRIORITIES", "RUN_TRIGGER_TYPES", "RunTrigger"]
