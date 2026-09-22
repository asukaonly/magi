"""Durable L1-owned handoff ledger for cognition projection."""

from __future__ import annotations

import time

from ...core.sqlite import sqlite_connection_async


class L1CognitionHandoffMixin:
    """Keep delivery pending until L2 acknowledges it or governance retires it."""

    db_path: str

    async def list_ready_cognition_handoffs(self, *, limit: int = 100) -> list[str]:
        """Read a bounded ready page; failed rows cannot starve later facts."""
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT event_id FROM l1_cognition_handoffs
                WHERE available_at <= ?
                ORDER BY available_at, created_at, event_id LIMIT ?
                """,
                (time.time(), max(1, min(int(limit), 1000))),
            ) as cursor:
                return [str(row[0]) for row in await cursor.fetchall()]

    async def complete_cognition_handoff(self, event_id: str) -> None:
        """Acknowledge an idempotent downstream handoff without retaining content."""
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                "DELETE FROM l1_cognition_handoffs WHERE event_id = ?", (event_id,)
            )
            await db.commit()

    async def retry_cognition_handoff(self, event_id: str, *, error: str) -> None:
        """Retain a failed obligation with bounded backoff across restarts."""
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                UPDATE l1_cognition_handoffs
                SET attempt_count = attempt_count + 1,
                    available_at = ? + MIN(60, 1 << MIN(attempt_count, 6)),
                    last_error = ?
                WHERE event_id = ?
                """,
                (time.time(), error[:200], event_id),
            )
            await db.commit()
