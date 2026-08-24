"""Fact normalization for chat task-agent routing."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from magi.agent.runtime.contracts import FactRecord
from magi.events.events import EventTypes
from magi.agent.task_agents.common import (
    GenericFactPayload,
    IncomingFactKind,
    TaskFactPayload,
    UserMessagePayload,
)

CHAT_TOOL_LOOP_STEP_EVENT_TYPE = "CHAT_TOOL_LOOP_STEP"
SESSION_RUN_RESULT_EVENT_TYPES = {CHAT_TOOL_LOOP_STEP_EVENT_TYPE}


@dataclass(slots=True)
class ClassifiedFact:
    """Normalized fact payload used to build typed chat context."""

    kind: IncomingFactKind
    source_fact: Optional[FactRecord]
    latest_fact: Optional[FactRecord]
    batch_facts: list[FactRecord]
    source_payload: TaskFactPayload
    latest_payload: TaskFactPayload
    user_id: str
    session_id: str
    user_message: str
    latest_user_fact: Optional[FactRecord] = None
    latest_user_payload: UserMessagePayload | None = None
    latest_result_fact: Optional[FactRecord] = None


class ChatFactClassifier:
    """Classify task-agent fact batches into typed chat facts."""

    def classify(
        self,
        *,
        agent_id: str,
        latest_fact: Optional[FactRecord],
        batch_facts: list[FactRecord],
    ) -> ClassifiedFact:
        kind = self._detect_kind(latest_fact=latest_fact, batch_facts=batch_facts)
        source_fact = self._select_source_fact(
            kind=kind,
            latest_fact=latest_fact,
            batch_facts=batch_facts,
        )
        source_payload = self._normalize_fact_payload(
            fact=source_fact,
            kind=kind,
            fallback_user_id=agent_id,
        )
        latest_payload = self._normalize_fact_payload(
            fact=latest_fact,
            kind=self._kind_for_fact(latest_fact),
            fallback_user_id=agent_id,
        )
        latest_user_fact = self._find_last_matching_fact(
            batch_facts=batch_facts,
            predicate=lambda fact: fact.event_type == EventTypes.USER_MESSAGE,
            fallback=latest_fact if isinstance(latest_fact, FactRecord) and latest_fact.event_type == EventTypes.USER_MESSAGE else None,
        )
        latest_user_payload = (
            UserMessagePayload.from_dict(
                dict(latest_user_fact.payload) if isinstance(latest_user_fact.payload, dict) else {},
                fallback_user_id=agent_id,
            )
            if isinstance(latest_user_fact, FactRecord)
            else None
        )
        latest_result_fact = self._find_last_matching_fact(
            batch_facts=batch_facts,
            predicate=lambda fact: fact.event_type in SESSION_RUN_RESULT_EVENT_TYPES,
            fallback=latest_fact if isinstance(latest_fact, FactRecord) and latest_fact.event_type in SESSION_RUN_RESULT_EVENT_TYPES else None,
        )
        user_id = self._payload_user_id(source_payload, fallback_user_id=agent_id)
        session_id = self._payload_session_id(source_payload)
        user_message = self._payload_user_message(source_payload)
        return ClassifiedFact(
            kind=kind,
            source_fact=source_fact,
            latest_fact=latest_fact,
            batch_facts=batch_facts,
            source_payload=source_payload,
            latest_payload=latest_payload,
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
            latest_user_fact=latest_user_fact,
            latest_user_payload=latest_user_payload,
            latest_result_fact=latest_result_fact,
        )

    def _detect_kind(
        self,
        *,
        latest_fact: Optional[FactRecord],
        batch_facts: list[FactRecord],
    ) -> IncomingFactKind:
        if any(
            isinstance(fact, FactRecord) and fact.event_type == EventTypes.USER_MESSAGE
            for fact in batch_facts
        ):
            return IncomingFactKind.USER_MESSAGE
        if isinstance(latest_fact, FactRecord) and latest_fact.event_type == EventTypes.USER_MESSAGE:
            return IncomingFactKind.USER_MESSAGE
        return IncomingFactKind.OTHER_FACT

    def _kind_for_fact(self, fact: Optional[FactRecord]) -> IncomingFactKind:
        if not isinstance(fact, FactRecord):
            return IncomingFactKind.OTHER_FACT
        if fact.event_type == EventTypes.USER_MESSAGE:
            return IncomingFactKind.USER_MESSAGE
        return IncomingFactKind.OTHER_FACT

    def _select_source_fact(
        self,
        *,
        kind: IncomingFactKind,
        latest_fact: Optional[FactRecord],
        batch_facts: list[FactRecord],
    ) -> Optional[FactRecord]:
        if kind == IncomingFactKind.USER_MESSAGE:
            return self._find_last_matching_fact(
                batch_facts=batch_facts,
                predicate=lambda fact: fact.event_type == EventTypes.USER_MESSAGE,
                fallback=latest_fact,
            )
        if batch_facts:
            batch_fact = batch_facts[-1]
            if isinstance(batch_fact, FactRecord):
                return batch_fact
        return latest_fact if isinstance(latest_fact, FactRecord) else None

    def _find_last_matching_fact(
        self,
        *,
        batch_facts: list[FactRecord],
        predicate,
        fallback: Optional[FactRecord],
    ) -> Optional[FactRecord]:
        for fact in reversed(batch_facts):
            if isinstance(fact, FactRecord) and predicate(fact):
                return fact
        return fallback if isinstance(fallback, FactRecord) else None

    def _normalize_fact_payload(
        self,
        *,
        fact: Optional[FactRecord],
        kind: IncomingFactKind,
        fallback_user_id: str,
    ) -> TaskFactPayload:
        payload_dict = fact.payload if isinstance(fact, FactRecord) and isinstance(fact.payload, dict) else {}
        return self._normalize_payload(
            kind=kind,
            payload=payload_dict,
            fallback_user_id=fallback_user_id,
        )

    def _normalize_payload(
        self,
        *,
        kind: IncomingFactKind,
        payload: dict[str, object],
        fallback_user_id: str,
    ) -> TaskFactPayload:
        if kind == IncomingFactKind.USER_MESSAGE:
            return UserMessagePayload.from_dict(payload, fallback_user_id=fallback_user_id)
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
        if isinstance(payload, GenericFactPayload):
            return str(payload.raw.get("content") or "").strip()
        return str(getattr(payload, "content", "") or "").strip()
