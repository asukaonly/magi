"""Targeted re-evaluation for L3 insights invalidated by memory corrections."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ..derivation_revision import DerivationRevision
from ..l2.corrections.repository import MemoryCorrectionRepository
from ..l2.models import ReconciledTraitOutcome
from .contradiction_service import ContradictionInsightService
from .models import ContradictionPacket, L3Candidate, StateChangePacket, TrendShiftPacket
from .state_change_service import StateChangeService
from .summary_store import L3SummaryStore
from .trend_shift_service import TrendShiftService


class L3CorrectionDerivationService:
    """Re-evaluate only stale insights linked to one corrected subject."""

    def __init__(self, *, db_path: str, l2_store: Any) -> None:
        self._db_path = db_path
        self._l2_store = l2_store
        self._repository = MemoryCorrectionRepository(db_path)
        self._l3_store = L3SummaryStore(db_path=db_path, vector_enabled=False)

    async def rebuild_subject(
        self,
        subject_key: str,
        *,
        expected_revision: int | None = None,
    ) -> None:
        """Rebuild or retire stale insights that depend on one subject."""
        await self._l3_store.initialize()
        for insight in await self._stale_insights(subject_key):
            await self._rebuild_insight(
                insight,
                triggering_subject=subject_key,
                expected_revision=expected_revision,
            )

    async def _rebuild_insight(
        self,
        insight: Mapping[str, Any],
        *,
        triggering_subject: str,
        expected_revision: int | None,
    ) -> None:
        summary_id = str(insight["summary_id"])
        context = await self._rebuild_context(
            summary_id,
            triggering_subject=triggering_subject,
            expected_revision=expected_revision,
        )
        outcomes: list[ReconciledTraitOutcome] = []
        for subject_key, trait_names in context.claim_slots.items():
            assertions = await self._l2_store.list_current_assertions(
                entity_id=subject_key,
                context_scope=None,
                limit=500,
            )
            for assertion in assertions:
                if str(assertion.get("trait_name") or "") not in trait_names:
                    continue
                outcomes.append(_outcome_from_assertion(assertion))

        metadata = _json_dict(insight.get("insight_metadata"))
        candidate = await self._candidate_from_current_state(metadata, outcomes)
        if candidate is None:
            await self._retire(summary_id, revisions=context.revisions)
            return

        dependencies: list[tuple[str, str, str, int]] = []
        for outcome in outcomes:
            subject_key = str(outcome.entity_id)
            source_revision = context.revisions.get(subject_key)
            if source_revision is None:
                raise RuntimeError(f"Missing captured revision for {subject_key}")
            dependencies.append(
                (
                    "assertion",
                    str(outcome.source_assertion_id),
                    subject_key,
                    source_revision,
                )
            )
        await self._persist_candidate(
            candidate=candidate,
            dependencies=dependencies,
            revisions=context.revisions,
        )

    async def _candidate_from_current_state(
        self,
        metadata: Mapping[str, Any],
        outcomes: list[ReconciledTraitOutcome],
    ):
        if not outcomes:
            return None
        kind = str(metadata.get("kind") or "")
        trigger_reason = "memory_correction"
        if kind == "state_change":
            first = outcomes[0]
            return await StateChangeService().build_candidate(
                StateChangePacket(
                    entity_id=str(metadata.get("entity_id") or first.entity_id),
                    entity_type=str(metadata.get("entity_type") or first.entity_type),
                    outcomes=outcomes,
                    trigger_reason=trigger_reason,
                )
            )
        if kind == "trend_shift":
            first = outcomes[0]
            return await TrendShiftService().build_candidate(
                TrendShiftPacket(
                    entity_id=str(metadata.get("entity_id") or first.entity_id),
                    entity_type=str(metadata.get("entity_type") or first.entity_type),
                    outcomes=outcomes,
                    trigger_reason=trigger_reason,
                )
            )
        if kind == "conflict_resolution":
            source_event_ids = list(
                dict.fromkeys(
                    event_id for outcome in outcomes for event_id in outcome.evidence_event_ids
                )
            )
            return await ContradictionInsightService().build_candidate(
                ContradictionPacket(
                    source_event_ids=source_event_ids,
                    outcomes=outcomes,
                    trigger_reason=trigger_reason,
                )
            )
        return None

    async def _stale_insights(self, subject_key: str) -> list[dict[str, Any]]:
        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT DISTINCT summaries.*
                FROM summaries
                JOIN memory_derivation_dependencies AS dependencies
                  ON dependencies.artifact_id = summaries.summary_id
                 AND dependencies.artifact_kind = 'l3_insight'
                WHERE dependencies.subject_key = ?
                  AND summaries.summary_type = 'insight'
                  AND summaries.derivation_state = 'stale'
                ORDER BY summaries.updated_at ASC
                """,
                (subject_key,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def _rebuild_context(
        self,
        summary_id: str,
        *,
        triggering_subject: str,
        expected_revision: int | None,
    ) -> _RebuildContext:
        """Capture dependency slots and all related revisions from one snapshot."""
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN")
            async with db.execute(
                """
                SELECT dependencies.subject_key, assertions.trait_name
                FROM memory_derivation_dependencies AS dependencies
                LEFT JOIN tom_trait_assertions AS assertions
                  ON dependencies.source_kind = 'assertion'
                 AND assertions.assertion_id = dependencies.source_id
                WHERE dependencies.artifact_kind = 'l3_insight'
                  AND dependencies.artifact_id = ?
                """,
                (summary_id,),
            ) as cursor:
                rows = await cursor.fetchall()
            subjects = list(
                dict.fromkeys(
                    [
                        triggering_subject,
                        *(str(row[0]) for row in rows if str(row[0]).strip()),
                    ]
                )
            )
            placeholders = ", ".join("?" for _ in subjects)
            async with db.execute(
                f"""
                SELECT subject_key, revision
                FROM memory_subject_revisions
                WHERE subject_key IN ({placeholders})
                """,
                tuple(subjects),
            ) as cursor:
                revision_rows = await cursor.fetchall()
        revisions = {subject_key: 0 for subject_key in subjects}
        revisions.update({str(row[0]): int(row[1]) for row in revision_rows})
        if expected_revision is not None:
            DerivationRevision(
                subject_key=triggering_subject,
                source_revision=int(expected_revision),
            ).ensure_matches(revisions[triggering_subject])
        claim_slots: dict[str, set[str]] = {}
        for subject_key, trait_name in rows:
            if trait_name is None:
                continue
            claim_slots.setdefault(str(subject_key), set()).add(str(trait_name))
        return _RebuildContext(claim_slots=claim_slots, revisions=revisions)

    async def _persist_candidate(
        self,
        *,
        candidate: L3Candidate,
        dependencies: list[tuple[str, str, str, int]],
        revisions: Mapping[str, int],
    ) -> None:
        """Publish one rebuilt insight and its dependency ledger atomically."""
        stored: dict[str, Any]
        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                await _ensure_revisions_current(db, revisions)
                stored = await self._l3_store.upsert_candidate_on_connection(
                    db,
                    candidate=candidate,
                    source_task_ids=[],
                    summary_overrides={
                        "source_revision": max(revisions.values(), default=0),
                        "derivation_state": "current",
                    },
                )
                await self._repository.replace_artifact_dependencies_on_connection(
                    db,
                    artifact_kind="l3_insight",
                    artifact_id=str(stored["summary_id"]),
                    dependencies=dependencies,
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        await self._l3_store._schedule_summary_embedding(stored)

    async def _retire(
        self,
        summary_id: str,
        *,
        revisions: Mapping[str, int],
    ) -> None:
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await _ensure_revisions_current(db, revisions)
                await db.execute(
                    """
                    UPDATE summaries
                    SET derivation_state = 'retired', updated_at = ?
                    WHERE summary_id = ?
                    """,
                    (time.time(), summary_id),
                )
                await db.execute(
                    "DELETE FROM l3_summaries_fts WHERE summary_id = ?",
                    (summary_id,),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise


@dataclass(frozen=True, slots=True)
class _RebuildContext:
    claim_slots: dict[str, set[str]]
    revisions: dict[str, int]


async def _ensure_revisions_current(
    db: aiosqlite.Connection,
    revisions: Mapping[str, int],
) -> None:
    for subject_key, source_revision in revisions.items():
        await DerivationRevision(
            subject_key=subject_key,
            source_revision=source_revision,
        ).ensure_current_on_connection(db)


def _outcome_from_assertion(assertion: Mapping[str, Any]) -> ReconciledTraitOutcome:
    first_seen = float(assertion.get("first_inferred_at") or 0.0)
    last_seen = float(assertion.get("last_validated_at") or first_seen)
    return ReconciledTraitOutcome(
        entity_id=str(assertion.get("entity_id") or ""),
        entity_type=str(assertion.get("entity_type") or "entity"),
        trait_name=str(assertion.get("trait_name") or ""),
        winning_value=str(assertion.get("trait_value") or ""),
        status=str(assertion.get("validation_state") or assertion.get("status") or "stable"),
        confidence=float(assertion.get("confidence_score") or 0.0),
        evidence_event_ids=[str(item) for item in assertion.get("evidence_events") or []],
        time_span_hours=max(0.0, (last_seen - first_seen) / 3600.0),
        stability_kind="user_authoritative" if assertion.get("authority_ref") else "current",
        recommended_snapshot_field="",
        natural_summary=str(assertion.get("natural_summary") or ""),
        expires_at=(
            float(assertion["expires_at"]) if assertion.get("expires_at") is not None else None
        ),
        trait_family=str(assertion.get("trait_family") or ""),
        source_assertion_id=str(assertion.get("assertion_id") or ""),
    )


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


__all__ = ["L3CorrectionDerivationService"]
