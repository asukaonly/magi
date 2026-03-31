"""Mixin: L3 insight candidate building and L2-callback wiring."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .l2.models import L2FocalEntityRef, ReconciledTraitOutcome
from .l3.models import (
    ContradictionPacket,
    L3Candidate,
    StateChangePacket,
    TaskOutcomePacket,
    TrendShiftPacket,
)
from .l3.validator import validate_candidate

if __name__ != "__main__":  # always True – guard for TYPE_CHECKING-like lazy import
    from .event_contracts import MemoryEvent

logger = logging.getLogger(__name__)


class L3InsightsMixin:
    """Extracted methods for building / persisting L3 insight candidates."""

    # -- public persist helpers ------------------------------------------------

    async def persist_l3_candidate(
        self,
        *,
        candidate: L3Candidate,
        task_outcome: TaskOutcomePacket | None = None,
        source_task_ids: list[str] | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Validate and persist an explicit L3 candidate."""
        if self.l1 is None or self.l3 is None:  # type: ignore[attr-defined]
            return None

        evidence_events: list[dict[str, Any]] = []
        for event_id in candidate.source_event_ids:
            event = await self.l1.get_memory_event(event_id)  # type: ignore[attr-defined]
            if event is not None:
                evidence_events.append(event.to_dict() if hasattr(event, "to_dict") else dict(event))

        decision = validate_candidate(
            candidate,
            evidence_events=evidence_events,
            task_outcome=task_outcome,
        )
        if decision.action != "accept":
            return None

        task_ids = list(source_task_ids or [])
        if task_outcome is not None and task_outcome.task_id not in task_ids:
            task_ids.append(task_outcome.task_id)
        return await self.l3.upsert_candidate(candidate=candidate, source_task_ids=task_ids)  # type: ignore[attr-defined]

    async def persist_task_outcome_reflection(
        self,
        task_outcome: TaskOutcomePacket,
    ) -> Optional[Dict[str, Any]]:
        """Build and persist a task-driven L3 reflection when it has user value."""
        candidate = await self._task_reflection_service.build_candidate(task_outcome)  # type: ignore[attr-defined]
        if candidate is None:
            return None
        return await self.persist_l3_candidate(
            candidate=candidate,
            task_outcome=task_outcome,
            source_task_ids=[task_outcome.task_id],
        )

    async def persist_state_change_insight(
        self,
        packet: StateChangePacket,
    ) -> Optional[Dict[str, Any]]:
        """Build and persist an insight summary from L2 reconcile outcomes."""
        candidate = await self._state_change_service.build_candidate(packet)  # type: ignore[attr-defined]
        if candidate is None:
            return None
        return await self.persist_l3_candidate(candidate=candidate)

    async def persist_contradiction_insight(
        self,
        packet: ContradictionPacket,
    ) -> Optional[Dict[str, Any]]:
        """Build and persist a conflict-resolution insight from contradicted outcomes."""
        candidate = await self._contradiction_service.build_candidate(packet)  # type: ignore[attr-defined]
        if candidate is None:
            return None
        return await self.persist_l3_candidate(candidate=candidate)

    async def persist_trend_shift_insight(
        self,
        packet: TrendShiftPacket,
    ) -> Optional[Dict[str, Any]]:
        """Build and persist a trend-shift insight from long-span reconcile outcomes."""
        candidate = await self._trend_shift_service.build_candidate(packet)  # type: ignore[attr-defined]
        if candidate is None:
            return None
        return await self.persist_l3_candidate(candidate=candidate)

    # -- L2 pipeline callbacks -------------------------------------------------

    async def _handle_l2_state_change_outcomes(
        self,
        entity_id: str,
        entity_type: str,
        outcomes: list[ReconciledTraitOutcome],
    ) -> None:
        await self.persist_state_change_insight(
            StateChangePacket(
                entity_id=entity_id,
                entity_type=entity_type,
                outcomes=outcomes,
            )
        )
        contradiction_source_ids: list[str] = []
        contradictions: list[dict[str, Any]] = []
        for outcome in outcomes:
            if str(outcome.status or "") != "contradicted":
                continue
            contradictions.append(
                {
                    "trait_name": str(outcome.trait_name or ""),
                    "winning_value": str(outcome.winning_value or ""),
                }
            )
            for event_id in outcome.evidence_event_ids:
                event_id_str = str(event_id).strip()
                if event_id_str and event_id_str not in contradiction_source_ids:
                    contradiction_source_ids.append(event_id_str)
        if contradictions and contradiction_source_ids:
            await self.persist_contradiction_insight(
                ContradictionPacket(
                    source_event_ids=contradiction_source_ids,
                    contradictions=contradictions,
                )
            )
        await self.persist_trend_shift_insight(
            TrendShiftPacket(
                entity_id=entity_id,
                entity_type=entity_type,
                outcomes=outcomes,
            )
        )

    async def _handle_l2_active_entities(
        self,
        event: MemoryEvent,
        focal_entities: list[L2FocalEntityRef],
    ) -> None:
        if self.l0 is None or self.l2_entity_catalog is None or not event.session_id or not focal_entities:  # type: ignore[attr-defined]
            return

        entity_ids: list[str] = []
        for entity in focal_entities:
            entity_id = str(entity.entity_id).strip()
            if not entity_id or entity_id in entity_ids:
                continue
            entity_ids.append(entity_id)
        if not entity_ids:
            return

        catalog_rows = await self.l2_entity_catalog.list_entities(limit=len(entity_ids), entity_ids=entity_ids)  # type: ignore[attr-defined]
        catalog_by_id = {str(row["entity_id"]): row for row in catalog_rows}
        for entity in focal_entities:
            catalog_entity = catalog_by_id.get(str(entity.entity_id))
            if catalog_entity is None:
                continue
            canonical_name = str(catalog_entity.get("canonical_name") or "").strip()
            await self.l0.upsert_active_entity(  # type: ignore[attr-defined]
                session_id=event.session_id,
                entity_id=str(catalog_entity["entity_id"]),
                entity_type=str(catalog_entity["entity_type"]),
                snapshot={
                    "canonical_name": canonical_name,
                    "name": canonical_name,
                    "aliases": list(catalog_entity.get("aliases") or []),
                },
                relevance_score=1.0,
            )
