"""Phase F: tracking of which chat_messages each run consumed.

Used by ConversationLog.find_dependents to propagate retract events
across runs that depended on a now-redacted message.
"""
from __future__ import annotations

import time
from pathlib import Path

import aiosqlite

from ...core.logger import get_logger

logger = get_logger(__name__)


class ChatRunConsumedEventsStore:
    """Persists (session_id, run_id, revision) → list[message_id]."""

    def __init__(self, *, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def initialize(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialized = True

    async def record_consumed(
        self,
        *,
        session_id: str,
        run_id: str,
        revision: int,
        message_ids: list[str],
    ) -> None:
        if not message_ids:
            return
        now_ms = int(time.time() * 1000)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executemany(
                """
                INSERT OR IGNORE INTO chat_run_consumed_events(
                    session_id, run_id, revision, message_id, recorded_at_ms
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [(session_id, run_id, int(revision), mid, now_ms) for mid in message_ids],
            )
            await db.commit()

    async def find_runs_that_consumed(
        self,
        *,
        session_id: str,
        message_id: str,
    ) -> list[tuple[str, int]]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                """
                SELECT DISTINCT run_id, revision FROM chat_run_consumed_events
                WHERE session_id = ? AND message_id = ?
                ORDER BY run_id ASC, revision ASC
                """,
                (session_id, message_id),
            ) as cursor:
                rows = await cursor.fetchall()
        return [(row[0], int(row[1])) for row in rows]

    async def clear_for_run(
        self,
        *,
        session_id: str,
        run_id: str,
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "DELETE FROM chat_run_consumed_events WHERE session_id = ? AND run_id = ?",
                (session_id, run_id),
            )
            await db.commit()


__all__ = ["ChatRunConsumedEventsStore"]
