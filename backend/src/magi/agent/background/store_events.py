"""Background task event log persistence."""

from __future__ import annotations

import json

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from .contracts import BackgroundTaskEvent


class BackgroundTaskEventStoreMixin:
    """Persist and query background task event logs."""

    db_path: str

    async def append_event(self, event: BackgroundTaskEvent) -> BackgroundTaskEvent:
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute(
                """
                INSERT INTO background_task_events (
                    event_id, task_id, attempt_index, event_type,
                    from_status, to_status, message, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.task_id,
                    int(event.attempt_index),
                    event.event_type,
                    event.from_status.value if event.from_status is not None else None,
                    event.to_status.value if event.to_status is not None else None,
                    event.message,
                    json.dumps(event.payload, ensure_ascii=False),
                    float(event.created_at),
                ),
            )
            await db.commit()
        return event

    async def list_events(
        self,
        task_id: str,
        *,
        limit: int = 500,
    ) -> list[BackgroundTaskEvent]:
        """Return events for a task in insertion (creation) order."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM background_task_events
                WHERE task_id = ?
                ORDER BY created_at ASC, event_id ASC
                LIMIT ?
                """,
                (task_id, int(limit)),
            )
            rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]


__all__ = ["BackgroundTaskEventStoreMixin"]
