"""Runtime notification persistence."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, TypeVar

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from .contracts import RuntimeNotificationRecord

T = TypeVar("T")


class RuntimeNotificationPersistenceMixin:
    """Persist runtime_notifications rows (the primary IPC bus to the Rust
    notification bridge).
    """

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    async def _execute_hot_write(
        self,
        *,
        operation: str,
        write: Callable[[aiosqlite.Connection], Awaitable[T]],
    ) -> T:
        raise NotImplementedError

    async def _fetchone(self, sql: str, params: tuple[Any, ...]) -> aiosqlite.Row | None:
        raise NotImplementedError

    def _row_to_record(self, record_type: type[T], row: aiosqlite.Row | None) -> T | None:
        raise NotImplementedError

    @staticmethod
    def _now_ms() -> int:
        raise NotImplementedError

    async def append_notification(self, record: RuntimeNotificationRecord) -> int:
        await self.initialize()
        return await self._execute_hot_write(
            operation="append_notification",
            write=lambda db: self._insert_notification(db, record),
        )

    async def _insert_notification(
        self,
        db: aiosqlite.Connection,
        record: RuntimeNotificationRecord,
    ) -> int:
        cursor = await db.execute(
            """
            INSERT INTO runtime_notifications (
                channel,
                user_id,
                session_id,
                turn_id,
                run_id,
                run_revision,
                payload_json,
                created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.channel,
                record.user_id,
                record.session_id,
                record.turn_id,
                record.run_id,
                record.run_revision,
                record.payload_json,
                record.created_at_ms or self._now_ms(),
            ),
        )
        return int(cursor.lastrowid)

    async def list_notifications(
        self, *, after_id: int, limit: int = 50
    ) -> list[RuntimeNotificationRecord]:
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT *
                FROM runtime_notifications
                WHERE notification_id > ?
                ORDER BY notification_id ASC
                LIMIT ?
                """,
                (int(after_id), int(limit)),
            )
            rows = await cursor.fetchall()
        return [
            RuntimeNotificationRecord(
                notification_id=int(row["notification_id"]),
                channel=str(row["channel"]),
                user_id=str(row["user_id"]),
                session_id=str(row["session_id"]),
                turn_id=str(row["turn_id"]) if row["turn_id"] is not None else None,
                run_id=str(row["run_id"]) if row["run_id"] is not None else None,
                run_revision=int(row["run_revision"] or 0),
                payload_json=str(row["payload_json"]),
                created_at_ms=int(row["created_at_ms"] or 0),
            )
            for row in rows
        ]

    async def get_latest_notification_id(self) -> int:
        await self.initialize()
        row = await self._fetchone(
            "SELECT MAX(notification_id) AS notification_id FROM runtime_notifications",
            (),
        )
        if row is None:
            return 0
        return int(row["notification_id"] or 0)
