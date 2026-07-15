"""Snapshot evolution and reconciliation helpers for the L2 cognition store."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Protocol, cast

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ..models import ReconciledTraitOutcome
from .reconcile_state import L2ReconcileStateMixin, _MOMENTARY_TRAITS
from .snapshot_evolution import L2SnapshotEvolutionMixin, _SNAPSHOT_HISTORY_LIMIT

logger = get_logger(__name__)


@dataclass(slots=True)
class _ReconciledAssertionWrite:
    assertion_id: str
    status: str
    confidence: float
    last_seen: float
    outcome: ReconciledTraitOutcome


class _L2StoreReconcileHostProtocol(Protocol):
    db_path: str

    async def list_tom_assertions(
        self,
        *,
        entity_id: str | None = None,
        entity_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...


class L2StoreReconcileMixin(
    L2SnapshotEvolutionMixin,
    L2ReconcileStateMixin,
):
    """Compose L2 snapshot evolution and assertion reconcile helpers."""

    async def reconcile_entity(
        self,
        *,
        entity_id: str,
        entity_type: str | None = None,
        evidence_timestamps: dict[str, float] | None = None,
    ) -> list[ReconciledTraitOutcome]:
        """Re-evaluate assertion confidence and stability for one entity."""
        assertions = await self._active_reconcile_assertions(
            entity_id=entity_id,
            entity_type=entity_type,
        )
        if not assertions:
            return []

        normalized_entity_type = entity_type or assertions[0]["entity_type"]
        writes = [
            self._reconciled_assertion_write(
                assertion,
                entity_id=entity_id,
                entity_type=normalized_entity_type,
                evidence_timestamps=evidence_timestamps,
            )
            for assertion in assertions
        ]
        await self._write_reconciled_assertions(writes)
        outcomes = [write.outcome for write in writes]
        _log_reconcile_outcomes(
            entity_id=entity_id,
            entity_type=normalized_entity_type,
            outcomes=outcomes,
        )
        return outcomes

    async def _active_reconcile_assertions(
        self,
        *,
        entity_id: str,
        entity_type: str | None,
    ) -> list[dict[str, Any]]:
        host = cast(_L2StoreReconcileHostProtocol, self)
        assertions = await host.list_tom_assertions(
            entity_id=entity_id,
            entity_type=entity_type,
            limit=500,
        )
        inactive_statuses = {"superseded", "archived", "expired", "user_rejected"}
        return [
            item
            for item in assertions
            if item.get("status", item["validation_state"]) not in inactive_statuses
        ]

    def _reconciled_assertion_write(
        self,
        assertion: dict[str, Any],
        *,
        entity_id: str,
        entity_type: str,
        evidence_timestamps: dict[str, float] | None,
    ) -> _ReconciledAssertionWrite:
        evidence_events = [str(item) for item in assertion.get("evidence_events", [])]
        first_seen, last_seen = _assertion_seen_bounds(
            assertion,
            evidence_events=evidence_events,
            evidence_timestamps=evidence_timestamps,
        )
        time_span_hours = max(0.0, (last_seen - first_seen) / 3600.0)
        status, confidence, stability_kind = self._derive_reconcile_state(
            current_state=str(assertion["validation_state"]),
            current_confidence=float(assertion["confidence_score"]),
            evidence_count=len(set(evidence_events)),
            time_span_hours=time_span_hours,
            trait_name=str(assertion["trait_name"]),
            user_feedback=assertion.get("user_feedback"),
        )
        return _ReconciledAssertionWrite(
            assertion_id=str(assertion["assertion_id"]),
            status=status,
            confidence=confidence,
            last_seen=last_seen,
            outcome=self._reconciled_trait_outcome(
                assertion,
                entity_id=entity_id,
                entity_type=entity_type,
                evidence_events=evidence_events,
                status=status,
                confidence=confidence,
                time_span_hours=time_span_hours,
                stability_kind=stability_kind,
            ),
        )

    def _reconciled_trait_outcome(
        self,
        assertion: dict[str, Any],
        *,
        entity_id: str,
        entity_type: str,
        evidence_events: list[str],
        status: str,
        confidence: float,
        time_span_hours: float,
        stability_kind: str,
    ) -> ReconciledTraitOutcome:
        trait_name = str(assertion["trait_name"])
        return ReconciledTraitOutcome(
            entity_id=entity_id,
            entity_type=entity_type,
            trait_name=trait_name,
            winning_value=str(assertion["trait_value"]),
            status=status,
            confidence=confidence,
            evidence_event_ids=evidence_events,
            time_span_hours=round(time_span_hours, 2),
            stability_kind=stability_kind,
            recommended_snapshot_field=self._recommend_snapshot_field(
                trait_name=trait_name,
                status=status,
            ),
            natural_summary=str(assertion.get("natural_summary") or "").strip(),
            expires_at=(
                float(assertion["expires_at"]) if assertion.get("expires_at") is not None else None
            ),
            trait_family=str(assertion.get("trait_family") or "").strip(),
            source_assertion_id=str(assertion.get("assertion_id") or "").strip(),
        )

    async def _write_reconciled_assertions(
        self,
        writes: list[_ReconciledAssertionWrite],
    ) -> None:
        now = time.time()
        host = cast(_L2StoreReconcileHostProtocol, self)
        async with sqlite_connection_async(host.db_path) as db:
            for write in writes:
                await db.execute(
                    """
                    UPDATE tom_trait_assertions
                    SET confidence_score = ?, validation_state = ?, status = ?,
                        last_validated_at = ?, updated_at = ?
                    WHERE assertion_id = ?
                    """,
                    (
                        write.confidence,
                        write.status,
                        write.status,
                        write.last_seen,
                        now,
                        write.assertion_id,
                    ),
                )
            await db.commit()


def _assertion_seen_bounds(
    assertion: dict[str, Any],
    *,
    evidence_events: list[str],
    evidence_timestamps: dict[str, float] | None,
) -> tuple[float, float]:
    timestamps = sorted(
        float(evidence_timestamps[item])
        for item in evidence_events
        if evidence_timestamps and item in evidence_timestamps
    )
    if timestamps:
        return timestamps[0], timestamps[-1]
    return float(assertion["first_inferred_at"]), float(assertion["last_validated_at"])


def _log_reconcile_outcomes(
    *,
    entity_id: str,
    entity_type: str,
    outcomes: list[ReconciledTraitOutcome],
) -> None:
    status_counts: dict[str, int] = {}
    for item in outcomes:
        status = str(item.status or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    logger.info(
        "L2 reconcile entity completed",
        entity_id=entity_id,
        entity_type=entity_type,
        outcome_count=len(outcomes),
        status_counts=status_counts,
    )


__all__ = [
    "L2StoreReconcileMixin",
    "L2SnapshotEvolutionMixin",
    "L2ReconcileStateMixin",
    "_MOMENTARY_TRAITS",
    "_SNAPSHOT_HISTORY_LIMIT",
]
