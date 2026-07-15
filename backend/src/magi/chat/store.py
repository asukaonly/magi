"""SQLite-backed persistence for the chat domain."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from .contracts import ChatMessageRecord, ChatSessionRecord
from .storage.context_summaries import ChatContextSummaryPersistenceMixin
from .storage.attachments import ChatAttachmentPersistenceMixin
from .storage.messages import ChatMessagePersistenceMixin
from .storage.serialization import build_user_message_payload_json
from .storage.sessions import ChatSessionPersistenceMixin
from .storage.turns import ChatTurnPersistenceMixin


class ChatStore(
    ChatAttachmentPersistenceMixin,
    ChatContextSummaryPersistenceMixin,
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
        message_payload: dict[str, object] | None = None,
        created_at_ms: int,
        reply_to_message_id: str | None = None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        persona_id: str | None = None,
    ) -> ChatMessageRecord:
        """Create a user turn and its first transcript message transactionally."""
        await self.initialize()
        session_preview = str(message_text or "").strip()[:120]
        message = self._build_user_turn_message(
            session_id=session_id,
            user_id=user_id,
            turn_id=turn_id,
            message_text=message_text,
            attachment_payloads=attachment_payloads,
            message_payload=message_payload,
            created_at_ms=created_at_ms,
            persona_id=persona_id,
            reply_to_message_id=reply_to_message_id,
        )
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            existing_session = await self._fetch_session_row(db, session_id=session_id)
            await self._upsert_user_turn_session(
                db,
                existing_session=existing_session,
                session_id=session_id,
                user_id=user_id,
                session_preview=session_preview,
                created_at_ms=created_at_ms,
            )
            await self._insert_user_turn_row(
                db,
                session_id=session_id,
                user_id=user_id,
                turn_id=turn_id,
                created_at_ms=created_at_ms,
                run_id=run_id,
                run_revision=run_revision,
                run_disposition=run_disposition,
            )
            await self._insert_user_message_row(db, message)
            await self._replace_message_attachments(
                db,
                message=message,
                attachment_payloads=attachment_payloads,
            )
            await db.commit()
        return message

    def _build_user_turn_message(
        self,
        *,
        session_id: str,
        user_id: str,
        turn_id: str,
        message_text: str,
        attachment_payloads: list[dict[str, object]] | None,
        message_payload: dict[str, object] | None,
        created_at_ms: int,
        persona_id: str | None,
        reply_to_message_id: str | None,
    ) -> ChatMessageRecord:
        return ChatMessageRecord(
            message_id=f"msg_{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            turn_id=turn_id,
            user_id=user_id,
            role="user",
            message_kind="user_text",
            content_text=message_text,
            payload_json=self._build_user_message_payload_json(
                attachment_payloads,
                message_payload,
            ),
            is_final=True,
            is_visible=True,
            created_at_ms=created_at_ms,
            sequence_no=1,
            replaces_message_id=None,
            replaced_by_message_id=None,
            persona_id=str(persona_id or "").strip() or None,
            reply_to_message_id=str(reply_to_message_id or "").strip() or None,
        )

    async def _upsert_user_turn_session(
        self,
        db: aiosqlite.Connection,
        *,
        existing_session: Any,
        session_id: str,
        user_id: str,
        session_preview: str,
        created_at_ms: int,
    ) -> None:
        await self._upsert_session_with_connection(
            db,
            self._build_user_turn_session_record(
                existing_session=existing_session,
                session_id=session_id,
                user_id=user_id,
                session_preview=session_preview,
                created_at_ms=created_at_ms,
            ),
        )

    @staticmethod
    def _build_user_turn_session_record(
        *,
        existing_session: Any,
        session_id: str,
        user_id: str,
        session_preview: str,
        created_at_ms: int,
    ) -> ChatSessionRecord:
        return ChatSessionRecord(
            session_id=session_id,
            user_id=user_id,
            title=_row_text(existing_session, "title"),
            title_overridden=_row_bool(existing_session, "title_overridden"),
            summary=_row_text(existing_session, "summary"),
            created_at_ms=_row_int(existing_session, "created_at_ms", created_at_ms),
            updated_at_ms=created_at_ms,
            last_message_at_ms=created_at_ms,
            last_user_message_at_ms=created_at_ms,
            last_message_preview=session_preview,
            last_user_message_preview=session_preview,
            message_count=_row_int(existing_session, "message_count", 0) + 1,
            workspace_path=_row_optional_text(existing_session, "workspace_path"),
            history_version=_row_int(existing_session, "history_version", 0) + 1,
            archived_at_ms=_row_optional_int(existing_session, "archived_at_ms"),
            deleted_at_ms=_row_optional_int(existing_session, "deleted_at_ms"),
        )

    @staticmethod
    async def _insert_user_turn_row(
        db: aiosqlite.Connection,
        *,
        session_id: str,
        user_id: str,
        turn_id: str,
        created_at_ms: int,
        run_id: str | None,
        run_revision: int,
        run_disposition: str | None,
    ) -> None:
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

    async def _insert_user_message_row(
        self,
        db: aiosqlite.Connection,
        message: ChatMessageRecord,
    ) -> None:
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
                message.persona_id,
                message.reply_to_message_id,
                self._serialize_message_label(message.label),
            ),
        )

    @staticmethod
    def _build_user_message_payload_json(
        attachment_payloads: list[dict[str, object]] | None,
        message_payload: dict[str, object] | None = None,
    ) -> str:
        return build_user_message_payload_json(attachment_payloads, message_payload)

    async def _fetchone(self, sql: str, params: tuple[object, ...]) -> aiosqlite.Row | None:
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, params)
            return await cur.fetchone()


def _row_text(row: Any, key: str) -> str:
    if row is None:
        return ""
    return str(row[key] or "")


def _row_bool(row: Any, key: str) -> bool:
    if row is None:
        return False
    return bool(int(row[key] or 0))


def _row_int(row: Any, key: str, default: int) -> int:
    if row is None:
        return default
    return int(row[key] or default)


def _row_optional_text(row: Any, key: str) -> str | None:
    if row is None or row[key] is None:
        return None
    return str(row[key])


def _row_optional_int(row: Any, key: str) -> int | None:
    if row is None or row[key] is None:
        return None
    return int(row[key])
