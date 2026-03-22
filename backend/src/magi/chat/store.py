"""SQLite-backed persistence for the chat domain."""

from __future__ import annotations

from pathlib import Path
import uuid

import aiosqlite

from .contracts import ChatMessageRecord, ChatSessionRecord, ChatTurnRecord


class ChatStore:
    """Own chat-domain persistence for sessions, turns, and messages."""

    def __init__(self, *, db_path: str = "~/.magi/data/chat.db") -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def initialize(self) -> None:
        """Create the chat-domain schema."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    title_overridden INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL DEFAULT '',
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    last_message_at_ms INTEGER,
                    last_user_message_at_ms INTEGER,
                    last_message_preview TEXT NOT NULL DEFAULT '',
                    last_user_message_preview TEXT NOT NULL DEFAULT '',
                    message_count INTEGER NOT NULL DEFAULT 0,
                    archived_at_ms INTEGER,
                    deleted_at_ms INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_updated
                    ON chat_sessions(user_id, updated_at_ms DESC);

                CREATE TABLE IF NOT EXISTS chat_turns (
                    turn_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    trace_id TEXT,
                    orchestration_id TEXT,
                    status TEXT NOT NULL,
                    response_mode TEXT NOT NULL,
                    execution_mode TEXT,
                    ux_plan_json TEXT NOT NULL DEFAULT '{}',
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    completed_at_ms INTEGER,
                    error_text TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_chat_turns_session_created
                    ON chat_turns(session_id, created_at_ms ASC);
                CREATE INDEX IF NOT EXISTS idx_chat_turns_user_updated
                    ON chat_turns(user_id, updated_at_ms DESC);

                CREATE TABLE IF NOT EXISTS chat_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_id TEXT,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    message_kind TEXT NOT NULL,
                    content_text TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    is_final INTEGER NOT NULL DEFAULT 1,
                    is_visible INTEGER NOT NULL DEFAULT 1,
                    created_at_ms INTEGER NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    replaces_message_id TEXT,
                    replaced_by_message_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
                    ON chat_messages(session_id, created_at_ms ASC, sequence_no ASC);
                CREATE INDEX IF NOT EXISTS idx_chat_messages_turn_sequence
                    ON chat_messages(turn_id, sequence_no ASC);
                """
            )
            await db.commit()
        self._initialized = True

    async def shutdown(self) -> None:
        """Reset initialization state."""
        self._initialized = False

    async def is_empty(self) -> bool:
        """Return whether the chat store has any durable rows."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            for table in ("chat_sessions", "chat_turns", "chat_messages"):
                cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
                row = await cur.fetchone()
                if int(row[0] or 0) > 0:
                    return False
        return True

    async def upsert_session(self, record: ChatSessionRecord) -> None:
        """Insert or update one session row."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await self._upsert_session_with_connection(db, record)
            await db.commit()

    async def create_user_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        turn_id: str,
        message_text: str,
        created_at_ms: int,
    ) -> ChatMessageRecord:
        """Create a user turn and its first transcript message transactionally."""
        await self.initialize()
        session_preview = str(message_text or "").strip()[:120]
        message = ChatMessageRecord(
            message_id=f"msg_{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            turn_id=turn_id,
            user_id=user_id,
            role="user",
            message_kind="user_text",
            content_text=message_text,
            payload_json="{}",
            is_final=True,
            is_visible=True,
            created_at_ms=created_at_ms,
            sequence_no=1,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            existing_session = await self._fetch_session_row(db, session_id=session_id)
            next_message_count = int(existing_session["message_count"] or 0) + 1 if existing_session is not None else 1
            await self._upsert_session_with_connection(
                db,
                ChatSessionRecord(
                    session_id=session_id,
                    user_id=user_id,
                    title=str(existing_session["title"]) if existing_session is not None else "New Chat",
                    title_overridden=bool(int(existing_session["title_overridden"] or 0)) if existing_session is not None else False,
                    summary=str(existing_session["summary"] or "") if existing_session is not None else "",
                    created_at_ms=int(existing_session["created_at_ms"]) if existing_session is not None else created_at_ms,
                    updated_at_ms=created_at_ms,
                    last_message_at_ms=created_at_ms,
                    last_user_message_at_ms=created_at_ms,
                    last_message_preview=session_preview,
                    last_user_message_preview=session_preview,
                    message_count=next_message_count,
                    archived_at_ms=int(existing_session["archived_at_ms"]) if existing_session is not None and existing_session["archived_at_ms"] is not None else None,
                    deleted_at_ms=int(existing_session["deleted_at_ms"]) if existing_session is not None and existing_session["deleted_at_ms"] is not None else None,
                ),
            )
            await db.execute(
                """
                INSERT INTO chat_turns (
                    turn_id,
                    session_id,
                    user_id,
                    trace_id,
                    orchestration_id,
                    status,
                    response_mode,
                    execution_mode,
                    ux_plan_json,
                    created_at_ms,
                    updated_at_ms,
                    completed_at_ms,
                    error_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(turn_id) DO NOTHING
                """,
                (
                    turn_id,
                    session_id,
                    user_id,
                    None,
                    None,
                    "queued",
                    "final_only",
                    None,
                    "{}",
                    created_at_ms,
                    created_at_ms,
                    None,
                    None,
                ),
            )
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
                    replaced_by_message_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.message_id,
                    message.session_id,
                    message.turn_id,
                    message.user_id,
                    message.role,
                    message.message_kind,
                    message.content_text,
                    message.payload_json,
                    1,
                    1,
                    message.created_at_ms,
                    message.sequence_no,
                    None,
                    None,
                ),
            )
            await db.commit()
        return message

    async def upsert_turn(self, record: ChatTurnRecord) -> None:
        """Insert or update one chat turn row."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO chat_turns (
                    turn_id,
                    session_id,
                    user_id,
                    trace_id,
                    orchestration_id,
                    status,
                    response_mode,
                    execution_mode,
                    ux_plan_json,
                    created_at_ms,
                    updated_at_ms,
                    completed_at_ms,
                    error_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(turn_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    user_id = excluded.user_id,
                    trace_id = excluded.trace_id,
                    orchestration_id = excluded.orchestration_id,
                    status = excluded.status,
                    response_mode = excluded.response_mode,
                    execution_mode = excluded.execution_mode,
                    ux_plan_json = excluded.ux_plan_json,
                    updated_at_ms = excluded.updated_at_ms,
                    completed_at_ms = excluded.completed_at_ms,
                    error_text = excluded.error_text
                """,
                (
                    record.turn_id,
                    record.session_id,
                    record.user_id,
                    record.trace_id,
                    record.orchestration_id,
                    record.status,
                    record.response_mode,
                    record.execution_mode,
                    record.ux_plan_json,
                    record.created_at_ms,
                    record.updated_at_ms,
                    record.completed_at_ms,
                    record.error_text,
                ),
            )
            await db.commit()

    async def append_message(self, record: ChatMessageRecord) -> None:
        """Insert or replace one transcript message row."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
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
                    replaced_by_message_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            await db.commit()

    async def mark_message_replaced(self, *, message_id: str, replaced_by_message_id: str) -> None:
        """Mark one message as replaced by another message."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE chat_messages
                SET replaced_by_message_id = ?
                WHERE message_id = ?
                """,
                (replaced_by_message_id, message_id),
            )
            await db.commit()

    async def get_turn(self, turn_id: str) -> ChatTurnRecord | None:
        """Return one chat turn by ID."""
        row = await self._fetchone(
            """
            SELECT turn_id, session_id, user_id, trace_id, orchestration_id, status,
                   response_mode, execution_mode, ux_plan_json, created_at_ms,
                   updated_at_ms, completed_at_ms, error_text
            FROM chat_turns
            WHERE turn_id = ?
            """,
            (turn_id,),
        )
        if row is None:
            return None
        return ChatTurnRecord(
            turn_id=str(row["turn_id"]),
            session_id=str(row["session_id"]),
            user_id=str(row["user_id"]),
            trace_id=row["trace_id"],
            orchestration_id=row["orchestration_id"],
            status=str(row["status"]),
            response_mode=str(row["response_mode"]),
            execution_mode=row["execution_mode"],
            ux_plan_json=str(row["ux_plan_json"]),
            created_at_ms=int(row["created_at_ms"]),
            updated_at_ms=int(row["updated_at_ms"]),
            completed_at_ms=int(row["completed_at_ms"]) if row["completed_at_ms"] is not None else None,
            error_text=row["error_text"],
        )

    async def get_message(self, message_id: str) -> ChatMessageRecord | None:
        """Return one transcript message by ID."""
        row = await self._fetchone(
            """
            SELECT message_id, session_id, turn_id, user_id, role, message_kind,
                   content_text, payload_json, is_final, is_visible, created_at_ms,
                   sequence_no, replaces_message_id, replaced_by_message_id
            FROM chat_messages
            WHERE message_id = ?
            """,
            (message_id,),
        )
        if row is None:
            return None
        return self._row_to_message(row)

    async def list_messages(self, *, session_id: str) -> list[ChatMessageRecord]:
        """List transcript messages for one session in display order."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT message_id, session_id, turn_id, user_id, role, message_kind,
                       content_text, payload_json, is_final, is_visible, created_at_ms,
                       sequence_no, replaces_message_id, replaced_by_message_id
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY created_at_ms ASC, sequence_no ASC
                """,
                (session_id,),
            )
            rows = await cur.fetchall()
        return [self._row_to_message(row) for row in rows]

    async def _fetchone(self, sql: str, params: tuple[object, ...]) -> aiosqlite.Row | None:
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, params)
            return await cur.fetchone()

    async def _fetch_session_row(self, db: aiosqlite.Connection, *, session_id: str) -> aiosqlite.Row | None:
        cur = await db.execute(
            """
            SELECT session_id, user_id, title, title_overridden, summary, created_at_ms,
                   updated_at_ms, last_message_at_ms, last_user_message_at_ms,
                   last_message_preview, last_user_message_preview, message_count,
                   archived_at_ms, deleted_at_ms
            FROM chat_sessions
            WHERE session_id = ?
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
                archived_at_ms,
                deleted_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                record.archived_at_ms,
                record.deleted_at_ms,
            ),
        )

    @staticmethod
    def _row_to_message(row: aiosqlite.Row) -> ChatMessageRecord:
        return ChatMessageRecord(
            message_id=str(row["message_id"]),
            session_id=str(row["session_id"]),
            turn_id=str(row["turn_id"]) if row["turn_id"] is not None else None,
            user_id=str(row["user_id"]),
            role=str(row["role"]),
            message_kind=str(row["message_kind"]),
            content_text=str(row["content_text"]) if row["content_text"] is not None else None,
            payload_json=str(row["payload_json"]),
            is_final=bool(int(row["is_final"])),
            is_visible=bool(int(row["is_visible"])),
            created_at_ms=int(row["created_at_ms"]),
            sequence_no=int(row["sequence_no"]),
            replaces_message_id=str(row["replaces_message_id"]) if row["replaces_message_id"] is not None else None,
            replaced_by_message_id=str(row["replaced_by_message_id"]) if row["replaced_by_message_id"] is not None else None,
        )
