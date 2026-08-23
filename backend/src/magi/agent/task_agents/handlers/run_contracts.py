"""Typed contracts for session-scoped chat runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from time import time

from magi_plugin_sdk.run_trigger import RunTrigger  # noqa: F401 — re-export for callers


class RunResultDisposition(str, Enum):
    """How a run result should be treated by the session store."""

    ACCEPTED = "accepted"
    STALE = "stale"


@dataclass(slots=True)
class PendingTurn:
    """A pending user turn attached to an active session run."""

    turn_id: str
    content: str
    revision: int
    disposition: str = "augment"
    created_at: float = field(default_factory=time)


@dataclass(slots=True)
class RunResult:
    """A result emitted for a run revision."""

    result_id: str
    run_id: str
    revision: int
    payload: dict[str, Any]
    disposition: RunResultDisposition
    created_at: float = field(default_factory=time)


@dataclass(slots=True)
class AgentRun:
    """The active execution state for one chat session.

    Phase E adds graph + node_states + consumed_events + trigger + deliveries.
    Phase E keeps the legacy name ``ActiveRun`` as an alias so callers
    that imported the old name continue working without churn.
    Phase H upgrades ``trigger`` from ``str | None`` to a typed
    ``RunTrigger | None``. Live user-turn coordination remains canonical in
    ``pending_turns``; generic ``IncomingEvent`` values are trigger inputs,
    not a second process-local run queue.
    """

    session_id: str
    run_id: str
    status: str = "running"
    root_turn_id: str | None = None
    root_user_message: str = ""
    revision: int = 0
    cancel_requested_at: float | None = None
    cancel_reason: str | None = None
    cancel_requested_by: str | None = None
    cancel_anchor_turn_id: str | None = None
    pending_turns: list[PendingTurn] = field(default_factory=list)
    accepted_results: list[RunResult] = field(default_factory=list)
    stale_results: list[RunResult] = field(default_factory=list)
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    # === Phase E ===
    graph: tuple[str, ...] = ()
    node_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    consumed_events: tuple[str, ...] = ()
    # === Phase H: trigger upgraded from str to RunTrigger ===
    trigger: RunTrigger | None = None
    deliveries: tuple[str, ...] = ()


# Backward-compat alias — many call sites still import ActiveRun.
ActiveRun = AgentRun
