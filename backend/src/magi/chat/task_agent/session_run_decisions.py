"""Decision records produced by the chat session run coordinator."""

from __future__ import annotations

from dataclasses import dataclass, field

from magi.agent.runtime.contracts import FactRecord
from magi.agent.task_agents.common import IncomingFactKind, TaskFactPayload
from .interruption_classifier import InterruptionDisposition
from magi.agent.task_agents.handlers.run_contracts import ActiveRun, PendingTurn


@dataclass(slots=True)
class SessionFactDecision:
    """Normalized session-run decision for one incoming chat fact batch."""

    active_run: ActiveRun | None
    planner_fact: FactRecord | None
    planner_fact_kind: IncomingFactKind
    planner_user_message: str
    latest_payload: TaskFactPayload
    user_id: str
    session_id: str
    run_disposition: str | None = None
    interruption_disposition: InterruptionDisposition | None = None
    checkpoint_pending_turns: list[PendingTurn] = field(default_factory=list)
    superseded_turns: list["TurnSupersession"] = field(default_factory=list)


@dataclass(slots=True)
class TurnSupersession:
    """A turn that was superseded by a newer visible turn."""

    turn_id: str
    anchor_turn_id: str
    reason: str


def supersession_terminal_status(reason: str) -> str:
    """Map merge-like interjections separately from true interruption."""

    normalized_reason = str(reason or "").strip().lower()
    if normalized_reason in {
        InterruptionDisposition.AUGMENT.value,
        InterruptionDisposition.STEER.value,
    }:
        return "merged"
    return "interrupted"


@dataclass(slots=True)
class CheckpointDecision:
    """Visible pending-turn merge for one session checkpoint."""

    session_id: str
    run_id: str
    revision: int
    pending_turns: list[PendingTurn] = field(default_factory=list)
    visible_user_message: str = ""
