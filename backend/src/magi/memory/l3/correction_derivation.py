"""Targeted re-evaluation for L3 insights invalidated by memory corrections."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ..l2.corrections.repository import MemoryCorrectionRepository
from ..l2.models import ReconciledTraitOutcome
from .contradiction_service import ContradictionInsightService
from .models import ContradictionPacket, StateChangePacket, TrendShiftPacket
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

    async def rebuild_subject(self, subject_key: str) -> None:
        """Rebuild or retire stale insights that depend on one subject."""
        for insight in await self._stale_insights(subject_key):
            await self._rebuild_insight(insight)

    async def _rebuild_insight(self, insight: Mapping[str, Any]) -> None:
        summary_id = str(insight["summary_id"])
        claim_slots = await self._claim_slots(summary_id)
        outcomes: list[ReconciledTraitOutcome] = []
        for subject_key, trait_names in claim_slots.items():
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
            await self._retire(summary_id)
            return

        dependencies: list[tuple[str, str, str, int]] = []
        revisions: dict[str, int] = {}
        for outcome in outcomes:
            subject_key = str(outcome.entity_id)
            if subject_key not in revisions:
                revisions[subject_key] = await self._repository.current_subject_revision(
                    subject_key
                )
            dependencies.append(
                (
                    "assertion",
                    str(outcome.source_assertion_id),
                    subject_key,
                    revisions[subject_key],
                )
            )
        source_revision = max(revisions.values(), default=0)
        stored = await self._l3_store.upsert_candidate(
            candidate=candidate,
            summary_overrides={
                "source_revision": source_revision,
                "derivation_state": "current",
            },
        )
        await self._repository.replace_artifact_dependencies(
            artifact_kind="l3_insight",
            artifact_id=str(stored["summary_id"]),
            dependencies=dependencies,
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

    async def _claim_slots(self, summary_id: str) -> dict[str, set[str]]:
        async with sqlite_connection_async(self._db_path) as db:
            async with db.execute(
                """
                SELECT dependencies.subject_key, assertions.trait_name
                FROM memory_derivation_dependencies AS dependencies
                JOIN tom_trait_assertions AS assertions
                  ON dependencies.source_kind = 'assertion'
                 AND assertions.assertion_id = dependencies.source_id
                WHERE dependencies.artifact_kind = 'l3_insight'
                  AND dependencies.artifact_id = ?
                """,
                (summary_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        result: dict[str, set[str]] = {}
        for subject_key, trait_name in rows:
            result.setdefault(str(subject_key), set()).add(str(trait_name))
        return result

    async def _retire(self, summary_id: str) -> None:
        async with sqlite_connection_async(self._db_path) as db:
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
