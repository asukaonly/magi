"""Typed contracts for session-scoped chat runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from time import time


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
class ActiveRun:
    """The active execution state for one chat session."""

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
