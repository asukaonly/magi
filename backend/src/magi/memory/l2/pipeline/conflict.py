"""Conflict arbitration methods for L2Pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from ....core.logger import get_logger
from ...event_contracts import MemoryEvent
from ..models import (
    ContradictionHint,
    L2CandidateSet,
    L2ConflictArbitrationResult,
    L2EventWindow,
    L2EventWindowSummary,
    L2ExistingRecord,
    L2SourceEvent,
)

if TYPE_CHECKING:
    from ..store import L2CognitionStore
    from ..llm_service import L2LLMService
    from ...l1.event_store import L1EventStore

logger = get_logger(__name__)

SEVERE_CONTRADICTION_KINDS = {
    "direct_negation",
    "state_reversal",
    "exclusive_role_conflict",
    "preference_reversal",
}


class L2ConflictArbitrationMixin:
    """Mixin providing conflict arbitration methods for L2Pipeline."""

    # These attributes are provided by L2Pipeline at runtime.
    _cognition_store: Optional[L2CognitionStore]
    _l1_store: Optional[L1EventStore]
    _llm_service: Optional[L2LLMService]
    _enable_conflict_arbitration: bool
    _conflict_arbitration_min_confidence: float
    _stats: Any

    def _severe_contradiction_hints(self, hints: list[ContradictionHint]) -> list[ContradictionHint]:
        severe: list[ContradictionHint] = []
        for hint in hints:
            if hint.contradiction_kind not in SEVERE_CONTRADICTION_KINDS:
                continue
            if float(hint.confidence) < self._conflict_arbitration_min_confidence:
                continue
            severe.append(hint)
        return severe

    async def _arbitrate_conflicting_candidates(
        self,
        *,
        anchor_event: MemoryEvent,
        batch_events: list[MemoryEvent],
        graph_candidates: list[dict[str, Any]],
        assertion_candidates: list[dict[str, Any]],
        contradiction_hints: list[ContradictionHint],
    ) -> L2ConflictArbitrationResult | None:
        if not self._enable_conflict_arbitration or self._llm_service is None or self._cognition_store is None:
            return None

        severe_hints = self._severe_contradiction_hints(contradiction_hints)
        if not severe_hints:
            return None

        existing_records = await self._load_target_records_for_hints(severe_hints)
        if not existing_records:
            return None

        source_events = await self._load_source_events_for_records(
            batch_events=batch_events,
            existing_records=existing_records,
        )
        result = await self._llm_service.arbitrate_conflict(
            new_event_window=L2EventWindow(
                event_ids=[event.event_id for event in batch_events],
                events=[self._serialize_event_for_batch(event) for event in batch_events],  # type: ignore[attr-defined]
                summary=L2EventWindowSummary(
                    event_count=len(batch_events),
                    session_id=anchor_event.session_id,
                    user_id=anchor_event.user_id,
                ),
            ),
            new_candidates=L2CandidateSet(
                graph_candidates=graph_candidates,
                assertion_candidates=assertion_candidates,
            ),
            contradiction_hints=severe_hints,
            existing_records=existing_records,
            source_events=source_events,
        )
        if not result:
            return None
        self._stats.conflict_arbitration_triggered += 1
        self._stats.severe_contradiction_hint_count += len(severe_hints)
        self._increment_bucket(self._stats.conflict_arbitration_by_decision, result.decision)  # type: ignore[attr-defined]
        logger.info(
            "L2 conflict arbitration completed",
            event_id=anchor_event.event_id,
            decision=result.decision,
            severe_hint_count=len(severe_hints),
            existing_record_count=len(existing_records),
            source_event_count=len(source_events),
        )
        return result

    def _rewrite_hints_for_evolution(
        self,
        *,
        contradiction_hints: list[ContradictionHint],
        conflict_arbitration: L2ConflictArbitrationResult,
    ) -> list[ContradictionHint]:
        superseded_record_ids = {
            record_id
            for record_id in (
                self._non_empty_text(item)  # type: ignore[attr-defined]
                for item in conflict_arbitration.superseded_record_ids
            )
            if record_id
        }
        evolved_target_ids = superseded_record_ids or {
            hint.target_record_id for hint in self._severe_contradiction_hints(contradiction_hints) if hint.target_record_id
        }
        rewritten_hints: list[ContradictionHint] = []
        for hint in contradiction_hints:
            next_hint = ContradictionHint(**hint.to_dict())
            if next_hint.target_record_id in evolved_target_ids:
                if next_hint.target_record_type == "knowledge_graph":
                    next_hint.recommended_action = "mark_deprecated"
                elif next_hint.target_record_type == "tom_trait_assertion":
                    next_hint.recommended_action = "mark_conflicted"
            rewritten_hints.append(next_hint)
        return rewritten_hints

    def _rewrite_hints_for_keep_existing(
        self,
        *,
        contradiction_hints: list[ContradictionHint],
        conflict_arbitration: L2ConflictArbitrationResult,
    ) -> list[ContradictionHint]:
        winning_record_ids = {
            record_id
            for record_id in (
                self._non_empty_text(item)  # type: ignore[attr-defined]
                for item in conflict_arbitration.winning_record_ids
            )
            if record_id
        }
        rewritten_hints: list[ContradictionHint] = []
        for hint in contradiction_hints:
            next_hint = ContradictionHint(**hint.to_dict())
            if not winning_record_ids or next_hint.target_record_id in winning_record_ids:
                next_hint.recommended_action = "revalidate_only"
            rewritten_hints.append(next_hint)
        return rewritten_hints

    async def _load_target_records_for_hints(self, hints: list[ContradictionHint]) -> list[L2ExistingRecord]:
        if self._cognition_store is None:
            return []
        records: list[L2ExistingRecord] = []
        seen: set[str] = set()
        for hint in hints:
            target_record_id = self._non_empty_text(hint.target_record_id)  # type: ignore[attr-defined]
            target_record_type = self._non_empty_text(hint.target_record_type)  # type: ignore[attr-defined]
            if not target_record_id or not target_record_type or target_record_id in seen:
                continue
            seen.add(target_record_id)
            if target_record_type == "tom_trait_assertion":
                assertion = await self._cognition_store.get_tom_assertion(assertion_id=target_record_id)
                if assertion is None:
                    continue
                records.append(
                    L2ExistingRecord(
                        record_id=target_record_id,
                        record_type=target_record_type,
                        entity_id=assertion["entity_id"],
                        entity_type=assertion["entity_type"],
                        trait_name=assertion["trait_name"],
                        trait_value=assertion["trait_value"],
                        validation_state=assertion["validation_state"],
                        confidence=assertion["confidence_score"],
                        evidence_event_ids=list(assertion.get("evidence_events", [])),
                    )
                )
                continue
            if target_record_type == "knowledge_graph":
                relation = await self._cognition_store.get_relationship(triple_id=target_record_id)
                if relation is None:
                    continue
                records.append(
                    L2ExistingRecord(
                        record_id=target_record_id,
                        record_type=target_record_type,
                        subject_id=relation["subject_id"],
                        predicate=relation["predicate"],
                        object_id=relation["object_id"],
                        status=relation["status"],
                        confidence=relation["confidence"],
                        evidence_event_ids=list(relation.get("evidence_event_ids", [])),
                    )
                )
        return records

    async def _load_source_events_for_records(
        self,
        *,
        batch_events: list[MemoryEvent],
        existing_records: list[L2ExistingRecord],
    ) -> list[L2SourceEvent]:
        source_events: list[L2SourceEvent] = []
        seen_event_ids: set[str] = set()
        for event in batch_events:
            if event.event_id in seen_event_ids:
                continue
            seen_event_ids.add(event.event_id)
            source_events.append(
                L2SourceEvent(
                    event_id=event.event_id,
                    timestamp=event.timestamp,
                    session_id=event.session_id,
                    user_id=event.user_id,
                    source=event.source,
                    event_type=event.event_type,
                    content=event.content,
                    author_type=event.author_type,
                )
            )
        if self._l1_store is None:
            return source_events
        evidence_event_ids = {
            str(event_id)
            for record in existing_records
            for event_id in record.evidence_event_ids
            if str(event_id).strip()
        }
        for event_id in sorted(evidence_event_ids):
            if event_id in seen_event_ids:
                continue
            row = await self._l1_store.get_event(event_id)
            if row is None:
                continue
            seen_event_ids.add(event_id)
            source_events.append(
                L2SourceEvent(
                    event_id=str(row.get("event_id") or event_id),
                    timestamp=float(row.get("timestamp", 0.0) or 0.0),
                    session_id=self._non_empty_text(row.get("session_id")),  # type: ignore[attr-defined]
                    user_id=self._non_empty_text(row.get("user_id")),  # type: ignore[attr-defined]
                    source=str(row.get("source") or "unknown"),
                    event_type=str(row.get("event_type") or ""),
                    content=str(row.get("content") or ""),
                    author_type=str(row.get("author_type") or "user"),
                )
            )
        return source_events

    async def _load_evidence_timestamps(self, entity_id: str) -> dict[str, float]:
        if self._l1_store is None or self._cognition_store is None:
            return {}
        entity_type = self._entity_type_from_id(entity_id)  # type: ignore[attr-defined]
        assertions = await self._cognition_store.list_tom_assertions(entity_id=entity_id, entity_type=entity_type, limit=500)
        event_ids = sorted({event_id for item in assertions for event_id in item.get("evidence_events", [])})
        timestamps: dict[str, float] = {}
        for event_id in event_ids:
            event = await self._l1_store.get_event(event_id)
            if event is None:
                continue
            timestamps[event_id] = float(event["timestamp"])
        return timestamps
