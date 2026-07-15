"""Transcript message persistence for the chat store."""

from __future__ import annotations

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ..contracts import ChatMessageLabel, ChatMessageRecord
from ..message_frontier import (
    MESSAGE_FRONTIER_SELECT_SQL,
    MESSAGE_ORDER_SQL,
    build_inclusive_frontier_filter,
)
from .serialization import normalize_message_label, parse_message_label, row_to_message, serialize_message_label


MESSAGE_SELECT_COLUMNS = """
    message_id, session_id, turn_id, user_id, role, message_kind,
    content_text, payload_json, is_final, is_visible, created_at_ms,
    sequence_no, replaces_message_id, replaced_by_message_id, persona_id,
    reply_to_message_id, label_json
"""


class ChatMessagePersistenceMixin:
    """Persist chat transcript message records."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    async def _fetchone(self, sql: str, params: tuple[object, ...]) -> aiosqlite.Row | None:
        raise NotImplementedError

    @staticmethod
    def _extract_attachment_payloads(raw_payload_json: str | None) -> list[dict[str, object]]:
        raise NotImplementedError

    async def _replace_message_attachments(
        self,
        db: aiosqlite.Connection,
        *,
        message: ChatMessageRecord,
        attachment_payloads: list[dict[str, object]] | None,
    ) -> None:
        raise NotImplementedError

    async def append_message(
        self,
        record: ChatMessageRecord,
        *,
        attachment_payloads: list[dict[str, object]] | None = None,
    ) -> None:
        """Insert or replace one transcript message row."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO chat_messages (
                    message_id,
                    session_id,
                    turn_id,
                    user_id,
                    role,
                    message_kind,
                    content_text,
                    payload_json,
                    is_final,
                    is_visible,
                    created_at_ms,
                    sequence_no,
                    replaces_message_id,
                    replaced_by_message_id,
                    persona_id,
                    reply_to_message_id,
                    label_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.message_id,
                    record.session_id,
                    record.turn_id,
                    record.user_id,
                    record.role,
                    record.message_kind,
                    record.content_text,
                    record.payload_json,
                    1 if record.is_final else 0,
                    1 if record.is_visible else 0,
                    record.created_at_ms,
                    record.sequence_no,
                    record.replaces_message_id,
                    record.replaced_by_message_id,
                    record.persona_id,
                    record.reply_to_message_id,
                    self._serialize_message_label(record.label),
                ),
            )
            await self._replace_message_attachments(
                db,
                message=record,
                attachment_payloads=(
                    attachment_payloads
                    if attachment_payloads is not None
                    else self._extract_attachment_payloads(record.payload_json)
                ),
            )
            await db.commit()

    async def mark_message_replaced(self, *, message_id: str, replaced_by_message_id: str) -> None:
        """Mark one message as replaced by another message."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute(
                """
                UPDATE chat_messages
                SET replaced_by_message_id = ?
                WHERE message_id = ?
                """,
                (replaced_by_message_id, message_id),
            )
            await db.commit()

    async def get_latest_message_for_turn(
        self,
        turn_id: str,
        *,
        message_kind: str | None = None,
    ) -> ChatMessageRecord | None:
        """Return the latest transcript message for one turn."""
        sql = f"""
            SELECT {MESSAGE_SELECT_COLUMNS}
            FROM chat_messages
            WHERE turn_id = ?
        """
        params: tuple[object, ...]
        if message_kind:
            sql += " AND message_kind = ?"
            params = (turn_id, message_kind)
        else:
            params = (turn_id,)
        sql += " ORDER BY created_at_ms DESC, sequence_no DESC LIMIT 1"
        row = await self._fetchone(sql, params)
        if row is None:
            return None
        return self._row_to_message(row)

    async def get_latest_message_for_session(
        self,
        session_id: str,
        *,
        role: str | None = None,
        message_kind: str | None = None,
        exclude_turn_id: str | None = None,
    ) -> ChatMessageRecord | None:
        """Return the latest transcript message for one session."""
        sql = f"""
            SELECT {MESSAGE_SELECT_COLUMNS}
            FROM chat_messages
            WHERE session_id = ?
              AND is_visible = 1
        """
        params: list[object] = [session_id]
        if role:
            sql += " AND role = ?"
            params.append(role)
        if message_kind:
            sql += " AND message_kind = ?"
            params.append(message_kind)
        if exclude_turn_id:
            sql += " AND (turn_id IS NULL OR turn_id != ?)"
            params.append(exclude_turn_id)
        sql += " ORDER BY created_at_ms DESC, sequence_no DESC LIMIT 1"
        row = await self._fetchone(sql, tuple(params))
        if row is None:
            return None
        return self._row_to_message(row)

    async def next_sequence_no(self, *, session_id: str) -> int:
        """Return the next display sequence number for one session."""
        row = await self._fetchone(
            """
            SELECT COALESCE(MAX(sequence_no), 0) AS max_sequence_no
            FROM chat_messages
            WHERE session_id = ?
            """,
            (session_id,),
        )
        if row is None:
            return 1
        return int(row["max_sequence_no"] or 0) + 1

    async def get_message(self, message_id: str) -> ChatMessageRecord | None:
        """Return one transcript message by ID."""
        row = await self._fetchone(
            f"""
            SELECT {MESSAGE_SELECT_COLUMNS}
            FROM chat_messages
            WHERE message_id = ?
            """,
            (message_id,),
        )
        if row is None:
            return None
        return self._row_to_message(row)

    async def list_messages(
        self,
        *,
        session_id: str,
        start_message_id: str | None = None,
    ) -> list[ChatMessageRecord]:
        """List transcript messages from an optional inclusive frontier."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            where_sql = "session_id = ?"
            params: list[object] = [session_id]
            normalized_start = str(start_message_id or "").strip()
            if normalized_start:
                boundary = await self._fetch_message_boundary(
                    db,
                    session_id=session_id,
                    message_id=normalized_start,
                )
                if boundary is not None:
                    frontier_sql, frontier_params = build_inclusive_frontier_filter(
                        boundary,
                        message_id=normalized_start,
                    )
                    where_sql += frontier_sql
                    params.extend(frontier_params)
            cur = await db.execute(
                f"""
                SELECT {MESSAGE_SELECT_COLUMNS}
                FROM chat_messages
                WHERE {where_sql}
                ORDER BY {MESSAGE_ORDER_SQL}
                """,
                tuple(params),
            )
            rows = await cur.fetchall()
        return [self._row_to_message(row) for row in rows]

    @staticmethod
    async def _fetch_message_boundary(
        db: aiosqlite.Connection,
        *,
        session_id: str,
        message_id: str,
    ) -> aiosqlite.Row | None:
        cursor = await db.execute(
            MESSAGE_FRONTIER_SELECT_SQL,
            (session_id, message_id),
        )
        return await cursor.fetchone()

    async def update_message_label(
        self,
        *,
        session_id: str,
        message_id: str,
        label: dict[str, object] | ChatMessageLabel | None,
    ) -> ChatMessageRecord | None:
        """Replace the durable label payload for one message and return the updated row."""
        await self.initialize()
        normalized_label = self._normalize_message_label(label)
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute(
                """
                UPDATE chat_messages
                SET label_json = ?
                WHERE session_id = ?
                  AND message_id = ?
                """,
                (
                    self._serialize_message_label(normalized_label),
                    session_id,
                    message_id,
                ),
            )
            await db.execute(
                """
                UPDATE chat_sessions
                SET history_version = history_version + 1
                WHERE session_id = ?
                """,
                (session_id,),
            )
            await db.commit()
        return await self.get_message(message_id)

    async def hide_message(
        self,
        *,
        session_id: str,
        message_id: str,
    ) -> ChatMessageRecord | None:
        """Soft-delete one transcript message from display history."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            cur = await db.execute(
                """
                UPDATE chat_messages
                SET is_visible = 0
                WHERE session_id = ?
                  AND message_id = ?
                  AND is_visible = 1
                """,
                (
                    session_id,
                    message_id,
                ),
            )
            if int(cur.rowcount or 0) <= 0:
                await db.rollback()
                return None
            await db.execute(
                """
                UPDATE chat_sessions
                SET history_version = history_version + 1
                WHERE session_id = ?
                """,
                (session_id,),
            )
            await db.commit()
        return await self.get_message(message_id)

    @staticmethod
    def _row_to_message(row: aiosqlite.Row) -> ChatMessageRecord:
        return row_to_message(row)

    @staticmethod
    def _normalize_message_label(
        label: dict[str, object] | ChatMessageLabel | None,
    ) -> ChatMessageLabel | None:
        return normalize_message_label(label)

    @staticmethod
    def _serialize_message_label(label: ChatMessageLabel | None) -> str | None:
        return serialize_message_label(label)

    @staticmethod
    def _parse_message_label(raw_label_json: object) -> ChatMessageLabel | None:
        return parse_message_label(raw_label_json)
