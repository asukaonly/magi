"""Shared guards for corrections that reference forgotten memory."""

from __future__ import annotations

import aiosqlite

from .forget_governance import correction_has_forget_barrier
from .models import CorrectionTargetKind, MemoryCorrection


async def correction_target_was_forgotten(
    db: aiosqlite.Connection,
    correction: MemoryCorrection,
) -> bool:
    """Return whether reverting would restore a user-forgotten record."""
    if await correction_has_forget_barrier(db, correction.correction_id):
        return True
    if correction.target_kind == CorrectionTargetKind.ASSERTION:
        query = "SELECT authority_ref FROM tom_trait_assertions WHERE assertion_id = ?"
    else:
        query = "SELECT status_reason FROM knowledge_graph WHERE triple_id = ?"
    async with db.execute(query, (correction.target_id,)) as cursor:
        row = await cursor.fetchone()
    marker = str(row[0] or "") if row is not None else ""
    if correction.target_kind == CorrectionTargetKind.ASSERTION:
        return marker.startswith("forget:")
    return marker == "user_forget"


__all__ = ["correction_target_was_forgotten"]
