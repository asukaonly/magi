"""SQLite implementation of the channel session repository."""
from __future__ import annotations

import time
from pathlib import Path
import aiosqlite
from ...core.sqlite import secure_compact_sqlite, sqlite_connection_async
from ..contracts import ChannelSessionMapping


class SqliteChannelSessionRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser())

    async def initialize(self) -> None:
        """Prepare the directory; schema migration belongs to bootstrap."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    async def lookup(
        self,
        channel_type: str,
        external_chat_id: str,
        *,
        external_thread_id: str | None = None,
    ) -> ChannelSessionMapping | None:
        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM channel_session_mappings WHERE channel_type = ? AND external_chat_id = ? AND external_thread_id = ?",
                (channel_type, external_chat_id, external_thread_id or ""),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._row_to_mapping(row)

    async def list_all(self) -> list[ChannelSessionMapping]:
        """Return every (channel, chat) → session mapping known to
        the host. Used by the channels-bindings API to render the
        full list of connected accounts (and their per-binding
        auto-approve toggles)."""
        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM channel_session_mappings "
                "ORDER BY last_active_at_ms DESC"
            )
            rows = await cursor.fetchall()
            return [self._row_to_mapping(row) for row in rows]

    async def lookup_by_session(
        self,
        magi_session_id: str,
    ) -> ChannelSessionMapping | None:
        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM channel_session_mappings WHERE magi_session_id = ?",
                (magi_session_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._row_to_mapping(row)

    async def delete_mapping(
        self,
        channel_type: str,
        external_chat_id: str,
        *,
        external_thread_id: str | None = None,
    ) -> None:
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute(
                "DELETE FROM channel_session_mappings WHERE channel_type = ? AND external_chat_id = ? AND external_thread_id = ?",
                (channel_type, external_chat_id, external_thread_id or ""),
            )
            await db.commit()

    async def clear_conversation_state(self) -> dict[str, int]:
        """Remove channel data that can retain or recreate cleared conversations."""

        table_names = (
            "delivery_receipts",
            "outreach_outbox",
            "outreach_delivery_log",
            "channel_notification_cursors",
            "channel_session_mappings",
        )
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                counts: dict[str, int] = {}
                for table_name in table_names:
                    cursor = await db.execute(f"DELETE FROM {table_name}")
                    counts[table_name] = int(cursor.rowcount or 0)
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        await secure_compact_sqlite(self._db_path)
        return counts

    # -- notification cursor --------------------------------------------------

    async def get_notification_cursor(
        self,
        channel_type: str,
        external_chat_id: str,
    ) -> int:
        async with sqlite_connection_async(self._db_path) as db:
            cursor = await db.execute(
                "SELECT last_notification_id FROM channel_notification_cursors WHERE channel_type = ? AND external_chat_id = ?",
                (channel_type, external_chat_id),
            )
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def update_notification_cursor(
        self,
        channel_type: str,
        external_chat_id: str,
        notification_id: int,
    ) -> None:
        now_ms = int(time.time() * 1000)
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute(
                """INSERT INTO channel_notification_cursors
                       (channel_type, external_chat_id, last_notification_id, updated_at_ms)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(channel_type, external_chat_id)
                   DO UPDATE SET last_notification_id = excluded.last_notification_id,
                                 updated_at_ms = excluded.updated_at_ms""",
                (channel_type, external_chat_id, notification_id, now_ms),
            )
            await db.commit()

    async def get_relay_cursor(self, state_key: str) -> int:
        async with sqlite_connection_async(self._db_path) as db:
            cursor = await db.execute(
                "SELECT value_integer FROM channel_relay_state WHERE state_key = ?",
                (state_key,),
            )
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def update_relay_cursor(self, state_key: str, notification_id: int) -> None:
        now_ms = int(time.time() * 1000)
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute(
                """INSERT INTO channel_relay_state (state_key, value_integer, updated_at_ms)
                   VALUES (?, ?, ?)
                   ON CONFLICT(state_key)
                   DO UPDATE SET value_integer = excluded.value_integer,
                                 updated_at_ms = excluded.updated_at_ms""",
                (state_key, int(notification_id), now_ms),
            )
            await db.commit()

    # -- internals ------------------------------------------------------------

    async def insert(self, mapping: ChannelSessionMapping) -> None:
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute(
                """INSERT INTO channel_session_mappings
                       (channel_type, external_chat_id, external_thread_id, magi_session_id, magi_user_id,
                        is_group, created_at_ms, last_active_at_ms, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mapping.channel_type,
                    mapping.external_chat_id,
                    mapping.external_thread_id or "",
                    mapping.magi_session_id,
                    mapping.magi_user_id,
                    1 if mapping.is_group else 0,
                    mapping.created_at_ms,
                    mapping.last_active_at_ms,
                    mapping.metadata_json,
                ),
            )
            await db.commit()

    async def touch(self, channel_type: str, external_chat_id: str, now_ms: int, *, external_thread_id: str | None = None) -> None:
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute(
                "UPDATE channel_session_mappings SET last_active_at_ms = ? WHERE channel_type = ? AND external_chat_id = ? AND external_thread_id = ?",
                (now_ms, channel_type, external_chat_id, external_thread_id or ""),
            )
            await db.commit()

    @staticmethod
    def _row_to_mapping(row: aiosqlite.Row) -> ChannelSessionMapping:
        return ChannelSessionMapping(
            channel_type=row["channel_type"],
            external_chat_id=row["external_chat_id"],
            external_thread_id=row["external_thread_id"] or None,
            magi_session_id=row["magi_session_id"],
            magi_user_id=row["magi_user_id"],
            is_group=bool(row["is_group"]),
            created_at_ms=int(row["created_at_ms"]),
            last_active_at_ms=int(row["last_active_at_ms"]),
            metadata_json=row["metadata_json"],
        )
