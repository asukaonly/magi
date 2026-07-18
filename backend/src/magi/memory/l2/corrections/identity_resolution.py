"""Lifecycle updates for corrections made redundant by identity convergence."""

from __future__ import annotations

import aiosqlite

IDENTITY_MERGE_NOOP_ACTOR = "system:identity_merge_noop"


async def resolve_correction_after_identity_merge(
    db: aiosqlite.Connection,
    *,
    correction_id: str,
    resolved_at: float,
) -> bool:
    """Resolve one active correction whose old and new identities converged."""
    cursor = await db.execute(
        """
        UPDATE memory_corrections
        SET state = 'reverted', reverted_at = ?, reverted_by = ?
        WHERE correction_id = ? AND state = 'active'
        """,
        (resolved_at, IDENTITY_MERGE_NOOP_ACTOR, correction_id),
    )
    if not cursor.rowcount:
        return False
    await db.execute(
        "UPDATE memory_correction_rules SET active = 0 WHERE correction_id = ?",
        (correction_id,),
    )
    return True


__all__ = [
    "IDENTITY_MERGE_NOOP_ACTOR",
    "resolve_correction_after_identity_merge",
]
