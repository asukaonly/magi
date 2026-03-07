"""Fact normalization for ExploreTaskAgent routing."""
from __future__ import annotations

from dataclasses import dataclass

from ....core.runtime.contracts import FactRecord
from ..common import IncomingFactKind
from .constants import EXPLORE_TASK_REQUEST

WORKER_AGENT_EVENT_TYPES = {
    "WORKER_AGENT_PROGRESS",
    "WORKER_AGENT_COMPLETED",
    "WORKER_AGENT_FAILED",
}


@dataclass(slots=True)
class ClassifiedExploreFact:
    """Normalized fact payload used to build explore runtime context."""

    kind: IncomingFactKind
    payload: dict
    user_id: str
    session_id: str
    user_message: str


class ExploreFactClassifier:
    """Classify fact batches for ExploreTaskAgent."""

    def classify(self, *, agent_id: str, latest_fact: FactRecord | None, batch_facts: list[FactRecord]) -> ClassifiedExploreFact:
        payload = latest_fact.payload if isinstance(latest_fact, FactRecord) and isinstance(latest_fact.payload, dict) else {}
        kind = self._detect_kind(latest_fact, batch_facts)
        user_id = str(payload.get("user_id") or agent_id)
        session_id = str(payload.get("session_id") or "")
        user_message = str(payload.get("message") or payload.get("root_user_message") or "").strip()
        return ClassifiedExploreFact(
            kind=kind,
            payload=dict(payload),
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
        )

    def _detect_kind(self, latest_fact: FactRecord | None, batch_facts: list[FactRecord]) -> IncomingFactKind:
        if any(isinstance(fact, FactRecord) and fact.event_type in WORKER_AGENT_EVENT_TYPES for fact in batch_facts):
            return IncomingFactKind.WORKER_UPDATE
        if isinstance(latest_fact, FactRecord) and latest_fact.event_type == EXPLORE_TASK_REQUEST:
            return IncomingFactKind.EXPLORE_TASK_REQUEST
        return IncomingFactKind.OTHER_FACT
