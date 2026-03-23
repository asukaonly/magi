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
    created_at: float = field(default_factory=time)


@dataclass(slots=True)
class RunResult:
    """A result emitted for a run revision."""

    result_id: str
    revision: int
    payload: dict[str, Any]
    disposition: RunResultDisposition
    created_at: float = field(default_factory=time)


@dataclass(slots=True)
class ActiveRun:
    """The active execution state for one chat session."""

    session_id: str
    run_id: str
    revision: int = 0
    pending_turns: list[PendingTurn] = field(default_factory=list)
    accepted_results: list[RunResult] = field(default_factory=list)
    stale_results: list[RunResult] = field(default_factory=list)
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
