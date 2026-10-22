"""Runtime notification persistence."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, TypeVar
import json
import math

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from .contracts import RuntimeNotificationRecord, NotificationFeedBatch, NotificationFeedEvent

T = TypeVar("T")


def _feed_payload(raw: str | None) -> dict[str, Any] | None:
    if not isinstance(raw, str):
        return None
    try:
        decoded = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    if not isinstance(decoded, dict):
        return None
    stack = [(decoded, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > 64 or isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
    return decoded


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

    async def read_notification_feed(self, *, after_id: int | None, limit: int = 200) -> NotificationFeedBatch:
        """Read a bounded snapshot; missing or rewound cursors require resync."""
        if after_id is not None and after_id < 0:
            raise ValueError("Notification cursor must not be negative")
        limit = max(1, min(200, limit))
        async with sqlite_connection_async(self.db_path, profile="readonly") as db:
            await db.execute("BEGIN")
            cursor = await db.execute("SELECT COALESCE(MAX(notification_id),0) FROM runtime_notifications")
            latest = int((await cursor.fetchone())[0])
            if after_id is None or after_id > latest:
                return NotificationFeedBatch(next_id=latest, reset=True, events=[])
            cursor = await db.execute(
                "SELECT notification_id, channel, user_id, session_id, turn_id, "
                "CASE WHEN length(CAST(payload_json AS BLOB))<=65536 THEN payload_json ELSE NULL END "
                "FROM runtime_notifications WHERE notification_id>? ORDER BY notification_id LIMIT ?",
                (after_id, limit),
            )
            rows = await cursor.fetchall()
        events = []
        payload_bytes = 0
        next_id = after_id
        for row in rows:
            raw = row[5]
            size = len(raw.encode("utf-8")) if isinstance(raw, str) else 0
            if events and payload_bytes + size > 1024 * 1024:
                break
            payload_bytes += size
            data = _feed_payload(raw)
            channel, user_id, session_id, turn_id = str(row[1]), str(row[2]), str(row[3]), row[4]
            if any(len(value) > 512 for value in (channel, user_id, session_id, turn_id or "")):
                channel, user_id, session_id, turn_id, data = "", "", "", None, None
            if data is not None:
                data["user_id"], data["session_id"] = user_id, session_id
                if turn_id is not None:
                    data["turn_id"] = turn_id
                else:
                    data.pop("turn_id", None)
            next_id = int(row[0])
            events.append(NotificationFeedEvent(next_id, channel, user_id, session_id, turn_id, data))
        return NotificationFeedBatch(next_id=next_id, reset=False, events=events)

    async def get_latest_notification_id(self) -> int:
        await self.initialize()
        row = await self._fetchone(
            "SELECT MAX(notification_id) AS notification_id FROM runtime_notifications",
            (),
        )
        if row is None:
            return 0
        return int(row["notification_id"] or 0)
