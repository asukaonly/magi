"""Fact normalization for chat task-agent routing."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ....agent.runtime.contracts import FactRecord
from ....events.events import EventTypes
from ..common import (
    ExploreTaskCompletedPayload,
    GenericFactPayload,
    IncomingFactKind,
    TaskFactPayload,
    UserMessagePayload,
    WorkerUpdatePayload,
)
from ..explore.constants import EXPLORE_TASK_COMPLETED

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
    payload: TaskFactPayload
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
        payload_dict = latest_fact.payload if isinstance(latest_fact, FactRecord) and isinstance(latest_fact.payload, dict) else {}
        if not payload_dict and batch_facts:
            last_batch = batch_facts[-1]
            if isinstance(last_batch, FactRecord) and isinstance(last_batch.payload, dict):
                payload_dict = last_batch.payload

        kind = self._detect_kind(latest_fact=latest_fact, batch_facts=batch_facts)
        payload = self._normalize_payload(kind=kind, payload=payload_dict, fallback_user_id=agent_id)
        user_id = self._payload_user_id(payload, fallback_user_id=agent_id)
        session_id = self._payload_session_id(payload)
        user_message = self._payload_user_message(payload)
        return ClassifiedFact(
            kind=kind,
            latest_fact=latest_fact,
            batch_facts=batch_facts,
            payload=payload,
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

    def _normalize_payload(
        self,
        *,
        kind: IncomingFactKind,
        payload: dict[str, object],
        fallback_user_id: str,
    ) -> TaskFactPayload:
        if kind == IncomingFactKind.USER_MESSAGE:
            return UserMessagePayload.from_dict(payload, fallback_user_id=fallback_user_id)
        if kind == IncomingFactKind.WORKER_UPDATE:
            return WorkerUpdatePayload.from_dict(payload, fallback_user_id=fallback_user_id)
        if kind == IncomingFactKind.EXPLORE_TASK_COMPLETED:
            return ExploreTaskCompletedPayload.from_dict(payload, fallback_user_id=fallback_user_id)
        return GenericFactPayload(raw=dict(payload))

    def _payload_user_id(self, payload: TaskFactPayload, *, fallback_user_id: str) -> str:
        if isinstance(payload, GenericFactPayload):
            return str(payload.raw.get("user_id") or fallback_user_id)
        return str(getattr(payload, "user_id", fallback_user_id) or fallback_user_id)

    def _payload_session_id(self, payload: TaskFactPayload) -> str:
        if isinstance(payload, GenericFactPayload):
            return str(payload.raw.get("session_id") or "")
        return str(getattr(payload, "session_id", "") or "")

    def _payload_user_message(self, payload: TaskFactPayload) -> str:
        if isinstance(payload, UserMessagePayload):
            return payload.content
        if isinstance(payload, ExploreTaskCompletedPayload):
            return payload.root_user_message
        if isinstance(payload, GenericFactPayload):
            return str(payload.raw.get("content") or payload.raw.get("root_user_message") or "").strip()
        return str(getattr(payload, "content", "") or "").strip()
