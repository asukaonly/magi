"""Unbounded lightweight claim-to-evidence links for durable governance."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import aiosqlite

from .models import CorrectionTargetKind


@dataclass(frozen=True)
class ClaimEvidenceRecord:
    """One claim evidence identity with exact or bounded occurrence time."""

    event_id: str
    observed_at: float
    observed_from: float
    observed_to: float
    observed_at_is_approximate: bool

    def overlaps(self, start: float, end: float) -> bool:
        """Return whether this evidence can fall inside a closed interval."""
        return self.observed_from <= end and self.observed_to >= start


def normalize_evidence_timestamp(value: Any, *, fallback: float) -> float:
    """Return a finite evidence timestamp without rejecting a mixed batch."""
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        timestamp = float(fallback)
    if math.isfinite(timestamp):
        return timestamp
    fallback_timestamp = float(fallback)
    return fallback_timestamp if math.isfinite(fallback_timestamp) else 0.0


async def append_claim_evidence_event_ids(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    claim_fingerprint: str,
    event_ids: Iterable[str],
    observed_at: float,
    created_at: float,
    event_timestamps: Mapping[str, float] | None = None,
    observed_from: float | None = None,
    observed_to: float | None = None,
    mark_missing_timestamps_approximate: bool = False,
) -> None:
    """Record every event ever linked to a claim without bloating the claim row."""
    normalized = list(
        dict.fromkeys(str(event_id).strip() for event_id in event_ids if str(event_id).strip())
    )
    if not normalized:
        return
    fallback_observed_at = normalize_evidence_timestamp(observed_at, fallback=0.0)
    fallback_observed_from = normalize_evidence_timestamp(
        observed_from,
        fallback=fallback_observed_at,
    )
    fallback_observed_to = normalize_evidence_timestamp(
        observed_to,
        fallback=fallback_observed_at,
    )
    fallback_interval = (
        min(fallback_observed_from, fallback_observed_to),
        max(fallback_observed_from, fallback_observed_to),
    )
    rows: list[tuple[object, ...]] = []
    for event_id in normalized:
        exact_timestamp = _finite_timestamp_or_none((event_timestamps or {}).get(event_id))
        if exact_timestamp is None:
            event_observed_at = fallback_observed_at
            event_observed_from, event_observed_to = fallback_interval
            is_approximate = mark_missing_timestamps_approximate
        else:
            event_observed_at = exact_timestamp
            event_observed_from = exact_timestamp
            event_observed_to = exact_timestamp
            is_approximate = False
        rows.append(
            (
                target_kind.value,
                claim_fingerprint,
                event_id,
                event_observed_at,
                event_observed_from,
                event_observed_to,
                int(is_approximate),
                created_at,
            )
        )
    await db.executemany(
        """
        INSERT INTO memory_claim_evidence_events(
            target_kind, claim_fingerprint, event_id, observed_at,
            observed_from, observed_to, observed_at_is_approximate, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(target_kind, claim_fingerprint, event_id) DO UPDATE SET
            observed_at = CASE
                WHEN memory_claim_evidence_events.observed_at_is_approximate = 1
                     AND excluded.observed_at_is_approximate = 0
                THEN excluded.observed_at
                WHEN memory_claim_evidence_events.observed_at_is_approximate = 0
                     AND excluded.observed_at_is_approximate = 1
                THEN memory_claim_evidence_events.observed_at
                ELSE MIN(memory_claim_evidence_events.observed_at, excluded.observed_at)
            END,
            observed_from = CASE
                WHEN memory_claim_evidence_events.observed_at_is_approximate = 1
                     AND excluded.observed_at_is_approximate = 0
                THEN excluded.observed_from
                WHEN memory_claim_evidence_events.observed_at_is_approximate = 0
                     AND excluded.observed_at_is_approximate = 1
                THEN memory_claim_evidence_events.observed_from
                ELSE MIN(memory_claim_evidence_events.observed_from, excluded.observed_from)
            END,
            observed_to = CASE
                WHEN memory_claim_evidence_events.observed_at_is_approximate = 1
                     AND excluded.observed_at_is_approximate = 0
                THEN excluded.observed_to
                WHEN memory_claim_evidence_events.observed_at_is_approximate = 0
                     AND excluded.observed_at_is_approximate = 1
                THEN memory_claim_evidence_events.observed_to
                ELSE MAX(memory_claim_evidence_events.observed_to, excluded.observed_to)
            END,
            observed_at_is_approximate = MIN(
                memory_claim_evidence_events.observed_at_is_approximate,
                excluded.observed_at_is_approximate
            ),
            created_at = MIN(
                memory_claim_evidence_events.created_at,
                excluded.created_at
            )
        """,
        rows,
    )


async def claim_evidence_event_ids(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    claim_fingerprint: str,
    observed_from: float | None = None,
    observed_to: float | None = None,
) -> list[str]:
    """Return the complete evidence ledger for one claim and optional interval."""
    rows = await claim_evidence_records(
        db,
        target_kind=target_kind,
        claim_fingerprint=claim_fingerprint,
        observed_from=observed_from,
        observed_to=observed_to,
    )
    return [record.event_id for record in rows]


async def claim_evidence_records(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    claim_fingerprint: str,
    observed_from: float | None = None,
    observed_to: float | None = None,
) -> list[ClaimEvidenceRecord]:
    """Return complete evidence identities and observation times for one claim."""
    clauses = ["target_kind = ?", "claim_fingerprint = ?"]
    args: list[object] = [target_kind.value, claim_fingerprint]
    if observed_from is not None:
        clauses.append("observed_to >= ?")
        args.append(float(observed_from))
    if observed_to is not None:
        clauses.append("observed_from <= ?")
        args.append(float(observed_to))
    async with db.execute(
        f"""
        SELECT event_id, observed_at, observed_from, observed_to,
               observed_at_is_approximate
        FROM memory_claim_evidence_events
        WHERE {' AND '.join(clauses)}
        ORDER BY observed_at, event_id
        """,
        tuple(args),
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        ClaimEvidenceRecord(
            event_id=str(row[0]),
            observed_at=float(row[1]),
            observed_from=float(row[2]),
            observed_to=float(row[3]),
            observed_at_is_approximate=bool(row[4]),
        )
        for row in rows
    ]


async def claim_evidence_records_for_claims(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    claim_fingerprints: Iterable[str],
) -> dict[str, list[ClaimEvidenceRecord]]:
    """Return complete evidence ledgers for a bounded claim set in one query."""
    normalized = list(
        dict.fromkeys(
            str(fingerprint).strip()
            for fingerprint in claim_fingerprints
            if str(fingerprint).strip()
        )
    )
    if not normalized:
        return {}
    candidate_json = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    async with db.execute(
        """
        SELECT claim_fingerprint, event_id, observed_at, observed_from, observed_to,
               observed_at_is_approximate
        FROM memory_claim_evidence_events
        WHERE target_kind = ?
          AND claim_fingerprint IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        ORDER BY claim_fingerprint, observed_at, event_id
        """,
        (target_kind.value, candidate_json),
    ) as cursor:
        rows = await cursor.fetchall()
    grouped: dict[str, list[ClaimEvidenceRecord]] = {}
    for fingerprint, event_id, observed_at, observed_from, observed_to, approximate in rows:
        grouped.setdefault(str(fingerprint), []).append(
            ClaimEvidenceRecord(
                event_id=str(event_id),
                observed_at=float(observed_at),
                observed_from=float(observed_from),
                observed_to=float(observed_to),
                observed_at_is_approximate=bool(approximate),
            )
        )
    return grouped


async def refresh_claim_evidence_timestamps(
    db: aiosqlite.Connection,
    *,
    timestamps: Mapping[str, float],
) -> None:
    """Replace approximate ledger times with canonical L1 occurrence times."""
    normalized: list[tuple[float, str]] = []
    for event_id, observed_at in timestamps.items():
        normalized_event_id = str(event_id).strip()
        if not normalized_event_id:
            continue
        try:
            normalized_observed_at = float(observed_at)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(normalized_observed_at):
            continue
        normalized.append((normalized_observed_at, normalized_event_id))
    if not normalized:
        return
    await db.executemany(
        """
        UPDATE memory_claim_evidence_events
        SET observed_at = ?, observed_from = ?, observed_to = ?,
            observed_at_is_approximate = 0
        WHERE event_id = ? AND observed_at_is_approximate = 1
        """,
        [(observed_at, observed_at, observed_at, event_id) for observed_at, event_id in normalized],
    )


def _finite_timestamp_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return timestamp if math.isfinite(timestamp) else None


__all__ = [
    "append_claim_evidence_event_ids",
    "ClaimEvidenceRecord",
    "claim_evidence_event_ids",
    "claim_evidence_records",
    "claim_evidence_records_for_claims",
    "normalize_evidence_timestamp",
    "refresh_claim_evidence_timestamps",
]
