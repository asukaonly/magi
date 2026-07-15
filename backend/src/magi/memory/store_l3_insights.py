"""Mixin: L3 insight candidate building and L2-callback wiring."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from .derivation_revision import (
    DerivationRevisionChangedError,
    MemoryClearGenerationChangedError,
)
from .l2.corrections.repository import MemoryCorrectionRepository
from .l2.models import L2FocalEntityRef, ReconciledTraitOutcome
from .l3.derivation_fence import L3DerivationFence
from .l3.dependency_validation import (
    StaleL3CandidateError,
    ensure_l3_dependencies_current,
)
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


@dataclass(frozen=True, slots=True)
class _L3CandidateDependencyContext:
    dependencies: list[tuple[str, str, str, int]]
    fence: L3DerivationFence


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
        async with self.memory_operation_guard():
            try:
                return await self._persist_l3_candidate_guarded(
                    candidate=candidate,
                    task_outcome=task_outcome,
                    source_task_ids=source_task_ids,
                )
            except (
                DerivationRevisionChangedError,
                MemoryClearGenerationChangedError,
                StaleL3CandidateError,
            ) as exc:
                logger.info("Discarded stale L3 candidate: %s", exc)
                return None

    async def _persist_l3_candidate_guarded(
        self,
        *,
        candidate: L3Candidate,
        task_outcome: TaskOutcomePacket | None,
        source_task_ids: list[str] | None,
    ) -> Optional[Dict[str, Any]]:
        if self.l1 is None or self.l3 is None:  # type: ignore[attr-defined]
            return None

        evidence_events: list[dict[str, Any]] = []
        for event_id in candidate.source_event_ids:
            event = await self.l1.get_memory_event(event_id)  # type: ignore[attr-defined]
            if event is not None:
                evidence_events.append(
                    event.to_dict() if hasattr(event, "to_dict") else dict(event)
                )

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
        dependency_context = await self._l3_candidate_dependencies(candidate)
        l3_store = self.l3  # type: ignore[attr-defined]
        await l3_store.initialize()
        repository = MemoryCorrectionRepository(l3_store.db_path)
        detached_chunk_ids: list[str] = []
        async with l3_store.embedding_mutation_guard():
            async with sqlite_connection_async(l3_store.db_path) as db:
                db.row_factory = aiosqlite.Row
                await db.execute("BEGIN IMMEDIATE")
                try:
                    await dependency_context.fence.ensure_current_on_connection(db)
                    await ensure_l3_dependencies_current(
                        db,
                        dependency_context.dependencies,
                        effective_at=time.time(),
                    )
                    insight_key = (candidate.insight_key or "").strip() or None
                    existing_summary = (
                        await l3_store._find_summary_by_insight_key_on_connection(
                            db,
                            insight_key,
                        )
                        if insight_key is not None
                        else None
                    )
                    if existing_summary is not None:
                        detached_chunk_ids = (
                            await l3_store._detach_summary_embedding_on_connection(
                                db,
                                summary_id=str(existing_summary["summary_id"]),
                            )
                        )
                    summary = await l3_store.upsert_candidate_on_connection(
                        db,
                        candidate=candidate,
                        source_task_ids=task_ids,
                        summary_overrides={
                            "source_revision": dependency_context.fence.source_revision,
                            "derivation_state": "current",
                        },
                        resolved_existing_summary=existing_summary,
                    )
                    await repository.replace_artifact_dependencies_on_connection(
                        db,
                        artifact_kind="l3_insight",
                        artifact_id=str(summary["summary_id"]),
                        dependencies=dependency_context.dependencies,
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
            await l3_store._delete_summary_vectors_unlocked(detached_chunk_ids)
        await l3_store._schedule_summary_embedding(summary)
        return summary

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
        await self._attach_source_assertion_ids(entity_id, outcomes)
        await self.persist_state_change_insight(
            StateChangePacket(
                entity_id=entity_id,
                entity_type=entity_type,
                outcomes=outcomes,
            )
        )
        contradicted_outcomes = [o for o in outcomes if str(o.status or "") == "contradicted"]
        contradiction_source_ids: list[str] = []
        for outcome in contradicted_outcomes:
            for event_id in outcome.evidence_event_ids:
                event_id_str = str(event_id).strip()
                if event_id_str and event_id_str not in contradiction_source_ids:
                    contradiction_source_ids.append(event_id_str)
        if contradicted_outcomes and contradiction_source_ids:
            await self.persist_contradiction_insight(
                ContradictionPacket(
                    source_event_ids=contradiction_source_ids,
                    outcomes=contradicted_outcomes,
                )
            )
        await self.persist_trend_shift_insight(
            TrendShiftPacket(
                entity_id=entity_id,
                entity_type=entity_type,
                outcomes=outcomes,
            )
        )

    async def _attach_source_assertion_ids(
        self,
        entity_id: str,
        outcomes: list[ReconciledTraitOutcome],
    ) -> None:
        l2 = self.l2  # type: ignore[attr-defined]
        if l2 is None:
            return
        assertions = await l2.list_current_assertions(
            entity_id=entity_id,
            context_scope=None,
            limit=500,
        )
        by_trait: dict[str, list[dict[str, Any]]] = {}
        for assertion in assertions:
            by_trait.setdefault(str(assertion.get("trait_name") or ""), []).append(assertion)
        for outcome in outcomes:
            if outcome.source_assertion_id:
                continue
            candidates = by_trait.get(str(outcome.trait_name), [])
            matching = [
                assertion
                for assertion in candidates
                if str(assertion.get("trait_value") or "") == str(outcome.winning_value or "")
            ]
            selected = (matching or candidates)[:1]
            if selected:
                outcome.source_assertion_id = str(selected[0]["assertion_id"])

    async def _l3_candidate_dependencies(
        self,
        candidate: L3Candidate,
    ) -> _L3CandidateDependencyContext:
        l2 = self.l2  # type: ignore[attr-defined]
        l3 = self.l3  # type: ignore[attr-defined]
        dependency_refs: list[tuple[str, str, str]] = []
        if l2 is not None and candidate.summary_type == "insight":
            metadata = candidate.insight_metadata or {}
            default_subject = str(metadata.get("entity_id") or "").strip()
            raw_outcomes = metadata.get("outcomes")
            if not isinstance(raw_outcomes, list):
                raw_outcomes = []
            for raw_dependency in candidate.claim_dependencies:
                source_kind = str(raw_dependency.get("source_kind") or "").strip()
                source_id = str(raw_dependency.get("source_id") or "").strip()
                subject_key = str(raw_dependency.get("subject_key") or "").strip()
                if (
                    source_kind in {"assertion", "edge"}
                    and source_id
                    and subject_key
                ):
                    dependency_refs.append((source_kind, source_id, subject_key))
            for raw_outcome in raw_outcomes:
                if not isinstance(raw_outcome, dict):
                    continue
                subject_key = str(raw_outcome.get("entity_id") or default_subject).strip()
                assertion_id = str(raw_outcome.get("source_assertion_id") or "").strip()
                if subject_key and assertion_id:
                    dependency_refs.append(("assertion", assertion_id, subject_key))

        dependency_refs = list(dict.fromkeys(dependency_refs))
        db_path = l2.db_path if l2 is not None else l3.db_path
        if str(db_path) != str(l3.db_path):
            raise RuntimeError("L2 and L3 must share one database for atomic insight writes")
        async with sqlite_connection_async(db_path) as db:
            await db.execute("BEGIN")
            fence = await L3DerivationFence.capture_on_connection(
                db,
                (subject_key for _, _, subject_key in dependency_refs),
            )
            await db.commit()
        dependencies = [
            (source_kind, source_id, subject_key, fence.revisions[subject_key])
            for source_kind, source_id, subject_key in dependency_refs
        ]
        return _L3CandidateDependencyContext(
            dependencies=dependencies,
            fence=fence,
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
