"""SQLite-backed persistence for the chat domain."""

from __future__ import annotations

from pathlib import Path
import uuid

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from .contracts import ChatMessageRecord, ChatSessionRecord
from .storage.schema import (
    CHAT_STORE_SCHEMA_SQL,
    ensure_chat_message_columns,
    ensure_chat_session_columns,
    ensure_chat_store_schema,
    ensure_chat_turn_columns,
)
from .storage.attachments import ChatAttachmentPersistenceMixin
from .storage.messages import ChatMessagePersistenceMixin
from .storage.serialization import build_user_message_payload_json
from .storage.sessions import ChatSessionPersistenceMixin
from .storage.turns import ChatTurnPersistenceMixin


class ChatStore(
    ChatAttachmentPersistenceMixin,
    ChatMessagePersistenceMixin,
    ChatSessionPersistenceMixin,
    ChatTurnPersistenceMixin,
):
    """Own chat-domain persistence for sessions, turns, and messages."""

    def __init__(self, *, db_path: str = "~/.magi/data/chat/chat.db") -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def initialize(self) -> None:
        """Create the chat-domain schema."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await ensure_chat_store_schema(db)
            await db.commit()
        self._initialized = True

    async def shutdown(self) -> None:
        """Reset initialization state."""
        self._initialized = False

    async def is_empty(self) -> bool:
        """Return whether the chat store has any durable rows."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            for table in ("chat_sessions", "chat_turns", "chat_messages"):
                cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
                row = await cur.fetchone()
                if int(row[0] or 0) > 0:
                    return False
        return True

    async def create_user_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        turn_id: str,
        message_text: str,
        attachment_payloads: list[dict[str, object]] | None = None,
        created_at_ms: int,
        reply_to_message_id: str | None = None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
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
            payload_json=self._build_user_message_payload_json(attachment_payloads),
            is_final=True,
            is_visible=True,
            created_at_ms=created_at_ms,
            sequence_no=1,
            replaces_message_id=None,
            replaced_by_message_id=None,
            reply_to_message_id=str(reply_to_message_id or "").strip() or None,
        )
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            existing_session = await self._fetch_session_row(db, session_id=session_id)
            next_message_count = int(existing_session["message_count"] or 0) + 1 if existing_session is not None else 1
            await self._upsert_session_with_connection(
                db,
                ChatSessionRecord(
                    session_id=session_id,
                    user_id=user_id,
                    title=str(existing_session["title"]) if existing_session is not None else "",
                    title_overridden=bool(int(existing_session["title_overridden"] or 0)) if existing_session is not None else False,
                    summary=str(existing_session["summary"] or "") if existing_session is not None else "",
                    created_at_ms=int(existing_session["created_at_ms"]) if existing_session is not None else created_at_ms,
                    updated_at_ms=created_at_ms,
                    last_message_at_ms=created_at_ms,
                    last_user_message_at_ms=created_at_ms,
                    last_message_preview=session_preview,
                    last_user_message_preview=session_preview,
                    message_count=next_message_count,
                    workspace_path=str(existing_session["workspace_path"]) if existing_session is not None and existing_session["workspace_path"] is not None else None,
                    history_version=int(existing_session["history_version"] or 0) + 1 if existing_session is not None else 1,
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
                    error_text,
                    run_id,
                    run_revision,
                    run_disposition,
                    response_anchor_turn_id,
                    superseded_by_turn_id,
                    supersession_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    run_id,
                    run_revision,
                    run_disposition,
                    turn_id,
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
                    replaced_by_message_id,
                    reply_to_message_id,
                    label_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    message.reply_to_message_id,
                    self._serialize_message_label(message.label),
                ),
            )
            await self._replace_message_attachments(
                db,
                message=message,
                attachment_payloads=attachment_payloads,
            )
            await db.commit()
        return message

    @staticmethod
    def _build_user_message_payload_json(attachment_payloads: list[dict[str, object]] | None) -> str:
        return build_user_message_payload_json(attachment_payloads)

    async def _ensure_chat_turn_columns(self, db: aiosqlite.Connection) -> None:
        await ensure_chat_turn_columns(db)

    async def _ensure_chat_session_columns(self, db: aiosqlite.Connection) -> None:
        await ensure_chat_session_columns(db)

    async def _ensure_chat_message_columns(self, db: aiosqlite.Connection) -> None:
        await ensure_chat_message_columns(db)

    async def _fetchone(self, sql: str, params: tuple[object, ...]) -> aiosqlite.Row | None:
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, params)
            return await cur.fetchone()
