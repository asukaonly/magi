"""Exact SQLite fencing helpers for durable L2 projection writes."""

from __future__ import annotations

from collections.abc import Iterable

import aiosqlite

from ..batch_models import (
    L2ProjectionLease,
    derive_projection_attempt_key,
    projection_attempt_descriptor_json,
)
from .errors import ProjectionAttemptFencedError
from .governance import active_projection_event_predicate


def normalize_projection_leases(
    leases: Iterable[L2ProjectionLease],
    *,
    required: bool,
) -> tuple[L2ProjectionLease, ...]:
    """Validate a complete, unique set of typed projection leases."""

    normalized = tuple(leases)
    if required and not normalized:
        raise ValueError("projection_leases must not be empty")
    event_ids: set[str] = set()
    for lease in normalized:
        if not isinstance(lease, L2ProjectionLease):
            raise TypeError("projection lease must be an L2ProjectionLease")
        if lease.event_id in event_ids:
            raise ValueError("projection leases must contain unique event IDs")
        event_ids.add(lease.event_id)
    return normalized


def assert_projection_attempt_key(
    attempt_key: str,
    leases: Iterable[L2ProjectionLease],
) -> None:
    """Require a caller-supplied attempt identity to prove its exact lease set."""

    normalized = normalize_projection_leases(leases, required=True)
    if str(attempt_key or "").strip() != derive_projection_attempt_key(normalized):
        raise ValueError("attempt_key does not match the complete projection lease set")


async def assert_current_projection_attempt(
    db: aiosqlite.Connection,
    leases: Iterable[L2ProjectionLease],
) -> None:
    """Fence a write transaction to the exact currently running batch attempt."""

    await assert_bound_projection_attempt(
        db,
        leases,
        allowed_statuses=("running",),
    )


async def assert_bound_projection_attempt(
    db: aiosqlite.Connection,
    leases: Iterable[L2ProjectionLease],
    *,
    allowed_statuses: Iterable[str],
    claimed_by: str | None = None,
) -> None:
    """Require the durable queue-issued descriptor for an exact lease set."""

    normalized = normalize_projection_leases(leases, required=True)
    statuses = tuple(
        dict.fromkeys(str(status or "").strip() for status in allowed_statuses if status)
    )
    if not statuses:
        raise ValueError("allowed_statuses must not be empty")
    expected_attempt_key = derive_projection_attempt_key(normalized)
    expected_descriptor = projection_attempt_descriptor_json(normalized)
    event_ids = [lease.event_id for lease in normalized]
    event_placeholders = ", ".join("?" for _ in event_ids)
    status_placeholders = ", ".join("?" for _ in statuses)
    claimed_by_clause = ""
    args: list[object] = [*event_ids, *statuses]
    if claimed_by is not None:
        claimed_by_clause = " AND jobs.claimed_by = ?"
        args.append(str(claimed_by))

    async with db.execute(
        f"""
        SELECT jobs.event_id, jobs.lease_token, jobs.attempt_count,
               jobs.batch_attempt_key, jobs.batch_descriptor_json,
               jobs.batch_bound_at
        FROM l2_projection_jobs AS jobs
        WHERE jobs.event_id IN ({event_placeholders})
          AND jobs.status IN ({status_placeholders})
          {claimed_by_clause}
          AND {active_projection_event_predicate('jobs.event_id')}
        """,
        tuple(args),
    ) as cursor:
        rows = await cursor.fetchall()
    if len(rows) != len(normalized):
        raise ProjectionAttemptFencedError("projection_attempt_fenced")

    leases_by_event = {lease.event_id: lease for lease in normalized}
    for row in rows:
        event_id = str(row[0])
        lease = leases_by_event.get(event_id)
        if (
            lease is None
            or str(row[1] or "") != lease.lease_token
            or int(row[2] or 0) != lease.attempt_count
            or str(row[3] or "") != expected_attempt_key
            or str(row[4] or "") != expected_descriptor
            or row[5] is None
        ):
            raise ProjectionAttemptFencedError("projection_attempt_fenced")

    async with db.execute(
        """
        SELECT event_id, batch_descriptor_json
        FROM l2_projection_jobs
        WHERE batch_attempt_key = ?
        """,
        (expected_attempt_key,),
    ) as cursor:
        bound_rows = await cursor.fetchall()
    if (
        {str(row[0]) for row in bound_rows} != set(event_ids)
        or any(str(row[1] or "") != expected_descriptor for row in bound_rows)
    ):
        raise ProjectionAttemptFencedError("projection_attempt_fenced")


__all__ = [
    "assert_bound_projection_attempt",
    "assert_current_projection_attempt",
    "assert_projection_attempt_key",
    "normalize_projection_leases",
]
