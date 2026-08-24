"""Decision records produced by the chat session run coordinator."""

from __future__ import annotations

from dataclasses import dataclass

from magi.agent.runtime.contracts import FactRecord
from magi.agent.task_agents.common import IncomingFactKind, TaskFactPayload
from magi.agent.task_agents.handlers.run_contracts import AgentRun


@dataclass(slots=True)
class SessionFactDecision:
    """Normalized session-run decision for one incoming chat fact batch."""

    active_run: AgentRun | None
    planner_fact: FactRecord | None
    planner_fact_kind: IncomingFactKind
    planner_user_message: str
    latest_payload: TaskFactPayload
    user_id: str
    session_id: str
    run_disposition: str | None = None


@dataclass(slots=True)
class TurnSupersession:
    """A turn that was superseded by a newer visible turn."""

    turn_id: str
    anchor_turn_id: str
    reason: str


def supersession_terminal_status(reason: str) -> str:
    """Map safe-boundary input injection separately from replacement."""

    normalized_reason = str(reason or "").strip().lower()
    if normalized_reason == "message":
        return "merged"
    return "interrupted"
