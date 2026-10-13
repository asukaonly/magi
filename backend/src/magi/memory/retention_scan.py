"""Durable keyset progress for bounded, cyclic retention maintenance."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Literal

from ..core.sqlite import sqlite_connection_async

RETENTION_SCAN_LIMIT = 10_000
RetentionLayer = Literal["l1", "l3"]
RetentionPosition = tuple[float, str]


@dataclass(frozen=True, slots=True)
class RetentionScanCursor:
    """One page's stable starting point and optimistic write revision."""

    revision: int = 0
    cutoff_at: float | None = None
    position: RetentionPosition | None = None


async def load_retention_scan_cursor(db_path: str, layer: RetentionLayer) -> RetentionScanCursor:
    """Read the next bounded page to scan without changing stored progress."""
    async with sqlite_connection_async(db_path) as db:
        async with db.execute(
            "SELECT revision, cutoff_at, position_at, position_id "
            "FROM memory_retention_scan_cursors WHERE layer = ?",
            (layer,),
        ) as query:
            row = await query.fetchone()
    if row is None:
        return RetentionScanCursor()
    return RetentionScanCursor(
        revision=int(row[0]),
        cutoff_at=float(row[1]) if row[1] is not None else None,
        position=(float(row[2]), str(row[3])) if row[2] is not None else None,
    )


async def advance_retention_scan_cursor(
    db_path: str,
    *,
    layer: RetentionLayer,
    previous: RetentionScanCursor,
    cutoff_at: float,
    positions: list[RetentionPosition],
    limit: int,
) -> bool:
    """Advance after a successful page, or restart the circle after its last page."""
    position = positions[-1] if len(positions) == limit else None
    async with sqlite_connection_async(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO memory_retention_scan_cursors (
                layer, cutoff_at, position_at, position_id, revision, updated_at
            ) SELECT ?, ?, ?, ?, ?, ?
            WHERE ? = 0 OR EXISTS (
                SELECT 1 FROM memory_retention_scan_cursors WHERE layer = ? AND revision = ?
            )
            ON CONFLICT(layer) DO UPDATE SET
                cutoff_at = excluded.cutoff_at,
                position_at = excluded.position_at,
                position_id = excluded.position_id,
                revision = excluded.revision,
                updated_at = excluded.updated_at
            WHERE memory_retention_scan_cursors.revision = ?
            """,
            (
                layer,
                cutoff_at if position is not None else None,
                position[0] if position is not None else None,
                position[1] if position is not None else None,
                previous.revision + 1,
                time.time(),
                previous.revision,
                layer,
                previous.revision,
                previous.revision,
            ),
        )
        await db.commit()
        return cursor.rowcount == 1
