"""Exact SQLite fencing helpers for durable L2 projection writes."""

from __future__ import annotations

from collections.abc import Iterable

import aiosqlite

from ..batch_models import L2ProjectionLease
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


async def assert_current_projection_attempt(
    db: aiosqlite.Connection,
    leases: Iterable[L2ProjectionLease],
) -> None:
    """Fence a write transaction to the exact currently running batch attempt."""

    for lease in leases:
        async with db.execute(
            f"""
            SELECT 1
            FROM l2_projection_jobs AS jobs
            WHERE jobs.event_id = ?
              AND jobs.status = 'running'
              AND jobs.lease_token = ?
              AND jobs.attempt_count = ?
              AND {active_projection_event_predicate('jobs.event_id')}
            """,
            (lease.event_id, lease.lease_token, lease.attempt_count),
        ) as cursor:
            if await cursor.fetchone() is None:
                raise ProjectionAttemptFencedError("projection_attempt_fenced")


__all__ = ["assert_current_projection_attempt", "normalize_projection_leases"]
