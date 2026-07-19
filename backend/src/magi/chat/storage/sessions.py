"""Session row persistence for the chat store."""

from __future__ import annotations

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ..contracts import ChatSessionRecord


class ChatSessionPersistenceMixin:
    """Persist chat session records and history versions."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    async def _fetchone(self, sql: str, params: tuple[object, ...]) -> aiosqlite.Row | None:
        raise NotImplementedError

    async def upsert_session(self, record: ChatSessionRecord) -> None:
        """Insert or update one session row."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await self._upsert_session_with_connection(db, record)
            await db.commit()

    async def get_history_version(self, session_id: str) -> int:
        """Return the durable prompt-history version for one session."""
        row = await self._fetchone(
            """
            SELECT history_version
            FROM chat_sessions
            WHERE session_id = ? COLLATE NOCASE
            """,
            (session_id,),
        )
        if row is None:
            return 0
        return int(row["history_version"] or 0)

    async def bump_history_version(self, session_id: str) -> int:
        """Increment and return the durable prompt-history version for one session."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute(
                """
                UPDATE chat_sessions
                SET history_version = history_version + 1
                WHERE session_id = ?
                """,
                (session_id,),
            )
            await db.commit()
        return await self.get_history_version(session_id)

    async def is_session_available(self, *, user_id: str, session_id: str) -> bool:
        """Return whether one user can still append work to a chat session."""

        row = await self._fetchone(
            """
            SELECT 1
            FROM chat_sessions
            WHERE session_id = ?
              AND user_id = ?
              AND archived_at_ms IS NULL
              AND deleted_at_ms IS NULL
            LIMIT 1
            """,
            (session_id, user_id),
        )
        return row is not None

    async def _fetch_session_row(self, db: aiosqlite.Connection, *, session_id: str) -> aiosqlite.Row | None:
        cur = await db.execute(
            """
            SELECT session_id, user_id, title, title_overridden, summary, created_at_ms,
                   updated_at_ms, last_message_at_ms, last_user_message_at_ms,
                   last_message_preview, last_user_message_preview, message_count,
                   workspace_path, history_version,
                   archived_at_ms, deleted_at_ms
            FROM chat_sessions
            WHERE session_id = ? COLLATE NOCASE
            """,
            (session_id,),
        )
        return await cur.fetchone()

    async def _upsert_session_with_connection(self, db: aiosqlite.Connection, record: ChatSessionRecord) -> None:
        await db.execute(
            """
            INSERT INTO chat_sessions (
                session_id,
                user_id,
                title,
                title_overridden,
                summary,
                created_at_ms,
                updated_at_ms,
                last_message_at_ms,
                last_user_message_at_ms,
                last_message_preview,
                last_user_message_preview,
                message_count,
                workspace_path,
                history_version,
                archived_at_ms,
                deleted_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                user_id = excluded.user_id,
                title = excluded.title,
                title_overridden = excluded.title_overridden,
                summary = excluded.summary,
                updated_at_ms = excluded.updated_at_ms,
                last_message_at_ms = excluded.last_message_at_ms,
                last_user_message_at_ms = excluded.last_user_message_at_ms,
                last_message_preview = excluded.last_message_preview,
                last_user_message_preview = excluded.last_user_message_preview,
                message_count = excluded.message_count,
                workspace_path = excluded.workspace_path,
                history_version = excluded.history_version,
                archived_at_ms = excluded.archived_at_ms,
                deleted_at_ms = excluded.deleted_at_ms
            """,
            (
                record.session_id,
                record.user_id,
                record.title,
                1 if record.title_overridden else 0,
                record.summary,
                record.created_at_ms,
                record.updated_at_ms,
                record.last_message_at_ms,
                record.last_user_message_at_ms,
                record.last_message_preview,
                record.last_user_message_preview,
                record.message_count,
                record.workspace_path,
                record.history_version,
                record.archived_at_ms,
                record.deleted_at_ms,
            ),
        )
