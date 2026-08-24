"""Phase H: typed RunTrigger + IncomingEvent."""
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
    def from_dict(cls, d: dict[str, Any]) -> "RunTrigger":
        return cls(
            trigger_type=d["trigger_type"],
            source_channel=d.get("source_channel"),
            requester=d["requester"],
            priority=d.get("priority", "foreground"),
            correlation=list(d.get("correlation") or []),
            payload=dict(d.get("payload") or {}),
        )


INCOMING_EVENT_TYPES = frozenset({
    "user_steer", "user_augment", "user_defer", "user_retract",
    "external_inbound", "scheduled_fire",
    "child_run_completed", "tool_advisory_arrival",
    "sensor_event",
})


@dataclass(frozen=True, slots=True)
class IncomingEvent:
    """A typed signal arriving during or before a run.

    Generalizes the chat-specific ``PendingTurn`` so external inbound
    (Telegram/Slack), scheduled fires, sensor events, and child-run
    completion all flow through the same queue + dispatcher.
    """
    event_id: str
    event_type: str
    target_run_id: str | None
    arrived_at_ms: int
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.event_type not in INCOMING_EVENT_TYPES:
            raise ValueError(
                f"IncomingEvent.event_type must be one of {sorted(INCOMING_EVENT_TYPES)}, "
                f"got {self.event_type!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "target_run_id": self.target_run_id,
            "arrived_at_ms": int(self.arrived_at_ms),
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "IncomingEvent":
        return cls(
            event_id=d["event_id"],
            event_type=d["event_type"],
            target_run_id=d.get("target_run_id"),
            arrived_at_ms=int(d["arrived_at_ms"]),
            payload=dict(d.get("payload") or {}),
        )


@dataclass(frozen=True, slots=True)
class RunRequest:
    """A normalized "start a run" request — the seam between a trigger source
    and a driver (ADR-0004 P3).

    A trigger source (chat user-message, scheduler tick, batch item-queue,
    inbound channel event) produces a ``RunRequest``; a driver consumes it to
    start one bounded engine run. It carries the ``trigger`` (provenance: who /
    why / which channel), the raw ``input`` to run, an optional ``session_id``,
    and optional ``bounds`` (e.g. ``max_iterations``).

    Execution specifics the driver fills in later — instructions / tool set /
    assembled context — are deliberately NOT part of the request. The request
    says *what to run and on whose behalf*, not *how to run it*.
    """

    trigger: RunTrigger
    input: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    bounds: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger.to_dict(),
            "input": dict(self.input),
            "session_id": self.session_id,
            "bounds": dict(self.bounds),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunRequest":
        return cls(
            trigger=RunTrigger.from_dict(d["trigger"]),
            input=dict(d.get("input") or {}),
            session_id=d.get("session_id"),
            bounds=dict(d.get("bounds") or {}),
        )


__all__ = [
    "RunTrigger",
    "RUN_TRIGGER_TYPES",
    "RUN_TRIGGER_PRIORITIES",
    "IncomingEvent",
    "INCOMING_EVENT_TYPES",
    "RunRequest",
]
