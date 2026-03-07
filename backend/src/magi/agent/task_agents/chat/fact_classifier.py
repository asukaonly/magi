"""Fact normalization for chat task-agent routing."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ....core.runtime.contracts import FactRecord
from ....events.events import EventTypes
from ..explore_task_agent import EXPLORE_TASK_COMPLETED
from .contracts import IncomingFactKind

WORKER_AGENT_EVENT_TYPES = {
    "WORKER_AGENT_PROGRESS",
    "WORKER_AGENT_COMPLETED",
    "WORKER_AGENT_FAILED",
}


@dataclass(slots=True)
class ClassifiedFact:
    """Normalized fact payload used to build typed chat context."""

    kind: IncomingFactKind
    latest_fact: Optional[FactRecord]
    batch_facts: list[FactRecord]
    payload: dict[str, Any]
    user_id: str
    session_id: str
    user_message: str


class ChatFactClassifier:
    """Classify task-agent fact batches into typed chat facts."""

    def classify(
        self,
        *,
        agent_id: str,
        latest_fact: Optional[FactRecord],
        batch_facts: list[FactRecord],
    ) -> ClassifiedFact:
        payload = latest_fact.payload if isinstance(latest_fact, FactRecord) and isinstance(latest_fact.payload, dict) else {}
        if not payload and batch_facts:
            last_batch = batch_facts[-1]
            if isinstance(last_batch, FactRecord) and isinstance(last_batch.payload, dict):
                payload = last_batch.payload

        kind = self._detect_kind(latest_fact=latest_fact, batch_facts=batch_facts)
        user_id = str(payload.get("user_id") or agent_id)
        session_id = str(payload.get("session_id") or "")
        user_message = str(payload.get("message") or payload.get("root_user_message") or "").strip()
        return ClassifiedFact(
            kind=kind,
            latest_fact=latest_fact,
            batch_facts=batch_facts,
            payload=dict(payload),
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
        )

    def _detect_kind(
        self,
        *,
        latest_fact: Optional[FactRecord],
        batch_facts: list[FactRecord],
    ) -> IncomingFactKind:
        if any(
            isinstance(fact, FactRecord) and fact.event_type in WORKER_AGENT_EVENT_TYPES
            for fact in batch_facts
        ):
            return IncomingFactKind.WORKER_UPDATE
        if any(
            isinstance(fact, FactRecord) and fact.event_type == EXPLORE_TASK_COMPLETED
            for fact in batch_facts
        ):
            return IncomingFactKind.EXPLORE_TASK_COMPLETED
        if isinstance(latest_fact, FactRecord) and latest_fact.event_type == EventTypes.USER_MESSAGE:
            return IncomingFactKind.USER_MESSAGE
        return IncomingFactKind.OTHER_FACT
