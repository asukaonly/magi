"""Read-side service for chat sessions and conversation history."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ..agent.orchestration import get_orchestration_store
from ..core.logger import get_logger
from ..core.sqlite import connect_sqlite
from ..memory.l1.chat_sessions import create_chat_session_record
from ..utils.runtime import get_runtime_paths
from ..api.services.chat_trace_read_service import AI_RESPONSE_EVENT_TYPES, USER_EVENT_TYPES, get_chat_trace_read_service
from .contracts import ChatMessageLabel, ChatReplyPreview

logger = get_logger(__name__)

FACT_EVENTS_TABLE = "fact_events"
CHAT_SESSIONS_TABLE = "chat_sessions"
CHAT_TURNS_TABLE = "chat_turns"
CHAT_MESSAGES_TABLE = "chat_messages"

CHAT_STORE_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {CHAT_SESSIONS_TABLE} (
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
    workspace_path TEXT,
    history_version INTEGER NOT NULL DEFAULT 0,
    archived_at_ms INTEGER,
    deleted_at_ms INTEGER
);
CREATE TABLE IF NOT EXISTS {CHAT_TURNS_TABLE} (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    trace_id TEXT,
    orchestration_id TEXT,
    status TEXT NOT NULL,
    response_mode TEXT NOT NULL,
    execution_mode TEXT,
    ux_plan_json TEXT NOT NULL DEFAULT '{{}}',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    error_text TEXT,
    run_id TEXT,
    run_revision INTEGER NOT NULL DEFAULT 0,
    run_disposition TEXT
);
CREATE TABLE IF NOT EXISTS {CHAT_MESSAGES_TABLE} (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    message_kind TEXT NOT NULL,
    content_text TEXT,
    payload_json TEXT NOT NULL DEFAULT '{{}}',
    is_final INTEGER NOT NULL DEFAULT 1,
    is_visible INTEGER NOT NULL DEFAULT 1,
    created_at_ms INTEGER NOT NULL,
    sequence_no INTEGER NOT NULL,
    replaces_message_id TEXT,
    replaced_by_message_id TEXT,
    reply_to_message_id TEXT,
    label_json TEXT
);
"""


@dataclass(slots=True)
class ChatSessionSummary:
    """Typed session summary returned by the chat read model."""

    session_id: str
    title: str
    last_message_preview: str
    last_user_message_preview: str
    title_overridden: bool
    last_timestamp: int
    message_count: int
    workspace_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "last_message_preview": self.last_message_preview,
            "last_user_message_preview": self.last_user_message_preview,
            "title_overridden": self.title_overridden,
            "last_timestamp": self.last_timestamp,
            "message_count": self.message_count,
            "workspace_path": self.workspace_path,
        }


@dataclass(slots=True)
class ChatSessionRenameResult:
    """Typed rename result for session title updates."""

    session_id: str
    title: str

    def to_dict(self) -> dict[str, str]:
        return {
            "session_id": self.session_id,
            "title": self.title,
        }


@dataclass(slots=True)
class SessionWorkspaceUpdateResult:
    """Typed update result for session workspace path changes."""

    session_id: str
    workspace_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "workspace_path": self.workspace_path,
        }


@dataclass(slots=True)
class ChatDisplayMessage:
    """Typed read model for chat history and display timeline messages."""

    role: str
    content: str
    timestamp: int
    kind: str
    attachments: list[dict[str, Any]] | None = None
    message_id: str | None = None
    message_kind: str | None = None
    turn_id: str | None = None
    trace_display_mode: str | None = None
    allow_trace_collapse: bool = False
    trace_summary: dict[str, Any] | None = None
    trace_available: bool = False
    reply_to: dict[str, Any] | None = None
    label: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "message_id": self.message_id,
            "message_kind": self.message_kind,
            "turn_id": self.turn_id,
            "kind": self.kind,
            "attachments": list(self.attachments or []),
            "trace_display_mode": self.trace_display_mode,
            "allow_trace_collapse": self.allow_trace_collapse,
            "trace_summary": self.trace_summary,
            "trace_available": self.trace_available,
            "reply_to": dict(self.reply_to) if isinstance(self.reply_to, dict) else None,
            "label": dict(self.label) if isinstance(self.label, dict) else None,
            "payload": dict(self.payload) if isinstance(self.payload, dict) else None,
        }

    def to_prompt_message(self) -> dict[str, str]:
        return {
            "role": self.role,
            "content": self.content,
        }

class ChatReadService:
    """Query chat session and history from persistent storage."""

    def __init__(self) -> None:
        runtime_paths = get_runtime_paths()
        self._chat_db_path: Path = runtime_paths.chat_db_path
        self._l1_db_path: Path = runtime_paths.l1_memory_db_path
        self._runtime_trace_db_path: Path = runtime_paths.runtime_trace_db_path
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        """Return a reusable SQLite connection, creating one lazily."""
        if self._conn is None:
            self._chat_db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = connect_sqlite(self._chat_db_path, profile="mixed")
            self._ensure_chat_store_schema(self._conn)
        return self._conn

    def close(self) -> None:
        """Close the cached SQLite connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    async def acreate_new_session(self, user_id: str, workspace_path: str | None = None) -> str:
        """Create a session without blocking the event loop."""
        return await self._run_threaded("create_new_session", user_id, workspace_path)

    async def aget_worker_result(self, worker_id: str) -> Optional[dict[str, Any]]:
        """Load a worker result without blocking the event loop."""
        return await self._run_threaded("get_worker_result", worker_id)

    async def aget_session_summary(
        self,
        user_id: str,
        session_id: str,
    ) -> ChatSessionSummary | None:
        """Load one session summary without blocking the event loop."""
        return await self._run_threaded("get_session_summary", user_id, session_id)

    async def aget_session_summaries_batch(
        self,
        user_id: str,
        session_ids: list[str],
    ) -> dict[str, "ChatSessionSummary"]:
        """Fetch multiple session summaries in one query without blocking."""
        return await self._run_threaded("get_session_summaries_batch", user_id, session_ids)

    async def alist_sessions(self, user_id: str, limit: int = 30) -> list[ChatSessionSummary]:
        """List sessions without blocking the event loop."""
        return await self._run_threaded("list_sessions", user_id, limit)

    async def arename_session(self, user_id: str, session_id: str, title: str) -> ChatSessionRenameResult:
        """Rename a session without blocking the event loop."""
        return await self._run_threaded("rename_session", user_id, session_id, title)

    async def aupdate_session_workspace(
        self,
        user_id: str,
        session_id: str,
        workspace_path: str | None,
    ) -> SessionWorkspaceUpdateResult:
        """Update a session workspace path without blocking the event loop."""
        return await self._run_threaded("update_session_workspace", user_id, session_id, workspace_path)

    async def adelete_session(self, user_id: str, session_id: str) -> None:
        """Delete a session without blocking the event loop."""
        await self._run_threaded("delete_session", user_id, session_id)

    async def aget_conversation_history(
        self,
        user_id: str,
        session_id: str,
        limit: int = 200,
    ) -> list[ChatDisplayMessage]:
        """Load conversation history without blocking the event loop."""
        return await self._run_threaded("get_conversation_history", user_id, session_id, limit)

    async def aget_display_history(
        self,
        user_id: str,
        session_id: str,
        limit: int = 200,
    ) -> list[ChatDisplayMessage]:
        """Load display history without blocking the event loop."""
        return await self._run_threaded("get_display_history", user_id, session_id, limit)

    async def aget_display_message(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> ChatDisplayMessage | None:
        """Load one visible display message without blocking the event loop."""
        return await self._run_threaded("get_display_message", user_id, session_id, message_id)

    async def aget_attachment_payload(
        self,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        """Load one persisted attachment payload without blocking the event loop."""
        return await self._run_threaded("get_attachment_payload", user_id, session_id, attachment_id)

    async def aclear_conversation_history(self, user_id: str, session_id: str) -> None:
        """Clear a session history without blocking the event loop."""
        await self._run_threaded("clear_conversation_history", user_id, session_id)

    async def aclear_all_sessions(self) -> int:
        """Clear all sessions without blocking the event loop."""
        return await self._run_threaded("clear_all_sessions")

    def create_new_session(self, user_id: str, workspace_path: str | None = None) -> str:
        normalized_user_id = str(user_id).strip()
        if not normalized_user_id:
            raise ValueError("User ID is required")
        record = create_chat_session_record(
            user_id=normalized_user_id,
            workspace_path=self._normalize_workspace_path(workspace_path),
        )
        conn = self._get_conn()
        conn.execute(
            f"""
            INSERT INTO {CHAT_SESSIONS_TABLE} (
                session_id, user_id, title, title_overridden, summary, created_at_ms, updated_at_ms,
                last_message_at_ms, last_user_message_at_ms, last_message_preview,
                last_user_message_preview, message_count, workspace_path, archived_at_ms, deleted_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.session_id,
                record.user_id,
                record.title,
                1 if record.title_overridden else 0,
                record.summary,
                int(record.created_at * 1000),
                int(record.updated_at * 1000),
                int(record.last_message_at * 1000) if record.last_message_at is not None else None,
                int(record.last_user_message_at * 1000) if record.last_user_message_at is not None else None,
                record.last_message_preview,
                record.last_user_message_preview,
                record.message_count,
                record.workspace_path,
                int(record.archived_at * 1000) if record.archived_at is not None else None,
                int(record.deleted_at * 1000) if record.deleted_at is not None else None,
            ),
        )
        conn.commit()
        return record.session_id

    def get_worker_result(self, worker_id: str) -> Optional[dict[str, Any]]:
        if not worker_id.strip():
            return None
        store = get_orchestration_store()
        return store.get_worker_result_sync(worker_id)

    def get_session_summary(self, user_id: str, session_id: str) -> ChatSessionSummary | None:
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")
        if not self._chat_db_path.exists():
            return None
        row = self._get_conn().execute(
            f"""
            SELECT
                session_id,
                title,
                title_overridden,
                last_message_preview,
                last_user_message_preview,
                workspace_path,
                updated_at_ms,
                last_message_at_ms,
                message_count
            FROM {CHAT_SESSIONS_TABLE}
            WHERE user_id = ?
              AND session_id = ?
              AND deleted_at_ms IS NULL
              AND archived_at_ms IS NULL
            """,
            (normalized_user_id, normalized_session_id),
        ).fetchone()
        return self._row_to_session_summary(row) if row is not None else None

    def get_session_summaries_batch(
        self,
        user_id: str,
        session_ids: list[str],
    ) -> dict[str, ChatSessionSummary]:
        """Fetch multiple session summaries in one query.

        Returns a dict mapping session_id -> ChatSessionSummary for found sessions.
        """
        normalized_user_id = str(user_id).strip()
        if not normalized_user_id or not session_ids:
            return {}
        if not self._chat_db_path.exists():
            return {}
        clean_ids = [str(sid).strip() for sid in session_ids if str(sid).strip()]
        if not clean_ids:
            return {}
        placeholders = ", ".join("?" for _ in clean_ids)
        rows = self._get_conn().execute(
            f"""
            SELECT
                session_id,
                title,
                title_overridden,
                last_message_preview,
                last_user_message_preview,
                workspace_path,
                updated_at_ms,
                last_message_at_ms,
                message_count
            FROM {CHAT_SESSIONS_TABLE}
            WHERE user_id = ?
              AND session_id IN ({placeholders})
              AND deleted_at_ms IS NULL
              AND archived_at_ms IS NULL
            """,
            (normalized_user_id, *clean_ids),
        ).fetchall()
        return {
            str(row["session_id"]): self._row_to_session_summary(row)
            for row in rows
        }

    def list_sessions(self, user_id: str, limit: int = 30) -> list[ChatSessionSummary]:
        """List recent chat sessions for a user."""
        safe_limit = max(1, min(limit, 200))
        if not self._chat_db_path.exists():
            return []
        try:
            conn = self._get_conn()
            rows = conn.execute(
                f"""
                SELECT
                    session_id,
                    title,
                    title_overridden,
                    last_message_preview,
                    last_user_message_preview,
                    workspace_path,
                    updated_at_ms,
                    last_message_at_ms,
                    message_count
                FROM {CHAT_SESSIONS_TABLE}
                WHERE user_id = ?
                  AND deleted_at_ms IS NULL
                  AND archived_at_ms IS NULL
                ORDER BY updated_at_ms DESC, created_at_ms DESC
                LIMIT ?
                """,
                (user_id, safe_limit),
            ).fetchall()
        except Exception as exc:
            logger.exception(f"Failed to query session list: {exc}")
            return []

        return [self._row_to_session_summary(row) for row in rows]

    def rename_session(self, user_id: str, session_id: str, title: str) -> ChatSessionRenameResult:
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        normalized_title = str(title).strip()
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")
        if not normalized_title:
            raise ValueError("Session title cannot be empty")
        conn = self._get_conn()
        cur = conn.execute(
            f"""
            UPDATE {CHAT_SESSIONS_TABLE}
            SET title = ?, title_overridden = 1, updated_at_ms = CAST(strftime('%s', 'now') AS INTEGER) * 1000
            WHERE session_id = ?
              AND user_id = ?
              AND deleted_at_ms IS NULL
            """,
            (normalized_title, normalized_session_id, normalized_user_id),
        )
        conn.commit()
        if cur.rowcount <= 0:
            raise ValueError("Session not found")
        return ChatSessionRenameResult(session_id=normalized_session_id, title=normalized_title)

    def update_session_workspace(
        self,
        user_id: str,
        session_id: str,
        workspace_path: str | None,
    ) -> SessionWorkspaceUpdateResult:
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        normalized_workspace_path = self._normalize_workspace_path(workspace_path)
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")
        conn = self._get_conn()
        cur = conn.execute(
            f"""
            UPDATE {CHAT_SESSIONS_TABLE}
            SET workspace_path = ?,
                updated_at_ms = CAST(strftime('%s', 'now') AS INTEGER) * 1000
            WHERE session_id = ?
              AND user_id = ?
              AND deleted_at_ms IS NULL
            """,
            (normalized_workspace_path, normalized_session_id, normalized_user_id),
        )
        conn.commit()
        if cur.rowcount <= 0:
            raise ValueError("Session not found")
        return SessionWorkspaceUpdateResult(
            session_id=normalized_session_id,
            workspace_path=normalized_workspace_path,
        )

    def delete_session(self, user_id: str, session_id: str) -> None:
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")

        if self._l1_db_path.exists():
            try:
                conn = connect_sqlite(self._l1_db_path, profile="hot_write")
                cur = conn.cursor()
                cur.execute(
                    f"""
                    DELETE FROM {FACT_EVENTS_TABLE}
                    WHERE user_id = ?
                      AND session_id = ?
                    """,
                    (normalized_user_id, normalized_session_id),
                )
                conn.commit()
                conn.close()
            except Exception as exc:
                logger.exception(f"Failed to delete session: {exc}")
        self._delete_runtime_trace_rows(user_id=normalized_user_id, session_id=normalized_session_id)

        conn = self._get_conn()
        conn.execute(
            f"DELETE FROM {CHAT_MESSAGES_TABLE} WHERE user_id = ? AND session_id = ?",
            (normalized_user_id, normalized_session_id),
        )
        conn.execute(
            f"DELETE FROM {CHAT_TURNS_TABLE} WHERE user_id = ? AND session_id = ?",
            (normalized_user_id, normalized_session_id),
        )
        conn.execute(
            f"""
            UPDATE {CHAT_SESSIONS_TABLE}
            SET deleted_at_ms = CAST(strftime('%s', 'now') AS INTEGER) * 1000,
                updated_at_ms = CAST(strftime('%s', 'now') AS INTEGER) * 1000,
                history_version = history_version + 1
            WHERE user_id = ?
              AND session_id = ?
              AND deleted_at_ms IS NULL
            """,
            (normalized_user_id, normalized_session_id),
        )
        conn.commit()
        return None

    def get_conversation_history(self, user_id: str, session_id: str, limit: int = 200) -> list[ChatDisplayMessage]:
        if not self._chat_db_path.exists():
            return []
        safe_limit = max(1, min(limit, 1000))
        try:
            rows = self._query_chat_message_rows(
                user_id=user_id,
                session_id=session_id,
                message_kinds=("user_text", "assistant_final"),
                visible_only=True,
                exclude_replaced=True,
            )
        except Exception as exc:
            logger.exception(f"Failed to query chat history: {exc}")
            return []

        selected_rows = rows[-safe_limit:]
        selected_message_rows: list[sqlite3.Row] = []
        messages: list[ChatDisplayMessage] = []
        for row in selected_rows:
            display_message = self._row_to_display_message(row)
            if display_message is None or display_message.kind == "status":
                continue
            if display_message.kind == "assistant" and row["message_kind"] != "assistant_final":
                continue
            selected_message_rows.append(row)
            messages.append(display_message)
        self._attach_reply_previews(rows=selected_message_rows, messages=messages)
        return messages

    def get_display_history(self, user_id: str, session_id: str, limit: int = 200) -> list[ChatDisplayMessage]:
        if not self._chat_db_path.exists():
            return []
        safe_limit = max(1, min(limit, 1000))
        try:
            turn_rows = self._query_turn_rows(
                user_id=user_id,
                session_id=session_id,
            )
            message_rows = self._query_chat_message_rows(
                user_id=user_id,
                session_id=session_id,
                message_kinds=None,
                visible_only=True,
                exclude_replaced=True,
            )
        except Exception as exc:
            logger.exception(f"Failed to query display history: {exc}")
            return []

        trace_service = get_chat_trace_read_service()
        trace_activity = trace_service.get_turn_activity_map(user_id=user_id, session_id=session_id)
        messages_by_turn: dict[str, list[ChatDisplayMessage]] = {}
        legacy_messages: list[ChatDisplayMessage] = []
        turn_ux_preferences = {
            str(row["turn_id"]): self._parse_turn_ux_preferences(row["ux_plan_json"])
            for row in turn_rows
        }

        display_rows: list[sqlite3.Row] = []
        display_messages: list[ChatDisplayMessage] = []
        for row in message_rows:
            display_message = self._row_to_display_message(row)
            if display_message is None:
                continue
            display_rows.append(row)
            display_messages.append(display_message)
            turn_id = str(row["turn_id"] or "").strip()
            if not turn_id:
                legacy_messages.append(display_message)
                continue
            self._apply_turn_ux_preferences(display_message, turn_ux_preferences.get(turn_id))
            if display_message.kind == "assistant":
                summary = trace_service.get_trace_summary(user_id=user_id, session_id=session_id, turn_id=turn_id)
                display_message.trace_summary = summary or trace_activity.get(turn_id)
                display_message.trace_available = bool((summary or trace_activity.get(turn_id) or {}).get("trace_available"))
            messages_by_turn.setdefault(turn_id, []).append(display_message)

        messages: list[ChatDisplayMessage] = []
        for turn in turn_rows:
            turn_id = str(turn["turn_id"])
            turn_messages = messages_by_turn.get(turn_id, [])
            for item in turn_messages:
                messages.append(item)
            has_assistant_message = any(item.kind == "assistant" for item in turn_messages)
            if has_assistant_message:
                continue
            summary = trace_activity.get(turn_id) or trace_service.get_trace_summary(
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
            )
            if summary is not None:
                timestamp = int(turn["updated_at_ms"] or turn["created_at_ms"] or 0)
                user_message = next((item for item in turn_messages if item.kind == "user"), None)
                if user_message is not None:
                    timestamp = user_message.timestamp
                messages.append(
                    ChatDisplayMessage(
                        role="assistant",
                        kind="status",
                        content=str((summary or {}).get("headline") or "Thinking"),
                        timestamp=timestamp,
                        turn_id=turn_id,
                        trace_display_mode=turn_ux_preferences.get(turn_id, {}).get("trace_display_mode"),
                        allow_trace_collapse=bool(
                            turn_ux_preferences.get(turn_id, {}).get("allow_trace_collapse", False)
                        ),
                        trace_summary=summary,
                        trace_available=bool(summary and summary.get("trace_available")),
                    )
                )
        messages.extend(legacy_messages)
        self._attach_reply_previews(rows=display_rows, messages=display_messages)
        messages.sort(key=lambda item: item.timestamp)
        return messages[-safe_limit:]

    def get_display_message(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> ChatDisplayMessage | None:
        _ = user_id
        if not self._chat_db_path.exists():
            return None
        normalized_session_id = str(session_id or "").strip()
        normalized_message_id = str(message_id or "").strip()
        if not normalized_session_id or not normalized_message_id:
            return None
        try:
            row = self._get_conn().execute(
                f"""
                SELECT message_id, session_id, turn_id, user_id, role, message_kind,
                       content_text, payload_json, is_final, is_visible, created_at_ms,
                       sequence_no, replaces_message_id, replaced_by_message_id, reply_to_message_id,
                       label_json
                FROM {CHAT_MESSAGES_TABLE}
                WHERE session_id = ?
                  AND message_id = ?
                  AND is_visible = 1
                LIMIT 1
                """,
                (normalized_session_id, normalized_message_id),
            ).fetchone()
        except Exception as exc:
            logger.exception(f"Failed to query display message: {exc}")
            return None
        if row is None:
            return None
        display_message = self._row_to_display_message(row)
        if display_message is None:
            return None
        self._attach_reply_previews(rows=[row], messages=[display_message])
        return display_message

    def get_attachment_payload(
        self,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        """Find one attachment payload by attachment id within a session."""
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        normalized_attachment_id = str(attachment_id).strip()
        if not normalized_user_id or not normalized_session_id or not normalized_attachment_id:
            raise ValueError("User ID, session ID, and attachment ID are required")
        if not self._chat_db_path.exists():
            return None

        rows = self._get_conn().execute(
            f"""
            SELECT payload_json
            FROM {CHAT_MESSAGES_TABLE}
            WHERE user_id = ?
              AND session_id = ?
              AND is_visible = 1
              AND payload_json != '{{}}'
            ORDER BY created_at_ms DESC
            """,
            (normalized_user_id, normalized_session_id),
        ).fetchall()

        for row in rows:
            payload = self._parse_message_payload_json(row["payload_json"])
            attachments = payload.get("attachments") if isinstance(payload.get("attachments"), list) else []
            for attachment in attachments:
                if not isinstance(attachment, dict):
                    continue
                if str(attachment.get("attachment_id") or "").strip() == normalized_attachment_id:
                    return dict(attachment)
        return None

    def clear_conversation_history(self, user_id: str, session_id: str) -> None:
        if not self._chat_db_path.exists():
            return
        try:
            conn = self._get_conn()
            conn.execute(
                f"DELETE FROM {CHAT_MESSAGES_TABLE} WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
            conn.execute(
                f"DELETE FROM {CHAT_TURNS_TABLE} WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
            conn.execute(
                f"""
                UPDATE {CHAT_SESSIONS_TABLE}
                SET
                    updated_at_ms = CAST(strftime('%s', 'now') AS INTEGER) * 1000,
                    last_message_at_ms = NULL,
                    last_user_message_at_ms = NULL,
                    last_message_preview = '',
                    last_user_message_preview = '',
                    message_count = 0,
                    history_version = history_version + 1
                WHERE user_id = ?
                  AND session_id = ?
                  AND deleted_at_ms IS NULL
                """,
                (user_id, session_id),
            )
            conn.commit()
        except Exception as exc:
            logger.exception(f"Failed to clear chat history: {exc}")
        self._delete_runtime_trace_rows(user_id=user_id, session_id=session_id)

    def _query_fact_rows(
        self,
        *,
        event_types: tuple[str, ...],
        user_id: str,
        session_id: str | None,
        limit: int | None,
        ascending: bool,
    ) -> list[tuple[str, str, float, str | None, str | None]]:
        return self._query_rows(
            table=FACT_EVENTS_TABLE,
            event_types=event_types,
            user_id=user_id,
            session_id=session_id,
            limit=limit,
            ascending=ascending,
        )

    def _query_rows(
        self,
        *,
        table: str,
        event_types: tuple[str, ...],
        user_id: str,
        session_id: str | None,
        limit: int | None,
        ascending: bool,
    ) -> list[tuple[str, str, float, str | None, str | None]]:
        if not event_types:
            return []
        order_direction = "ASC" if ascending else "DESC"
        query = f"""
            SELECT event_type, content, timestamp, session_id, turn_id
            FROM {table}
            WHERE deleted_at IS NULL
              AND event_type IN ({", ".join("?" for _ in event_types)})
              AND user_id = ?
        """
        params: list[Any] = [*event_types, user_id]
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        query += f" ORDER BY timestamp {order_direction}"
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))

        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        return rows

    def _delete_runtime_trace_rows(self, *, user_id: str, session_id: str) -> None:
        if not self._runtime_trace_db_path.exists():
            return
        try:
            conn = connect_sqlite(self._runtime_trace_db_path, profile="hot_write")
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM trace_turns WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
            cur.execute(
                "DELETE FROM trace_spans WHERE turn_id NOT IN (SELECT turn_id FROM trace_turns)",
            )
            cur.execute(
                "DELETE FROM trace_llm_calls WHERE turn_id NOT IN (SELECT turn_id FROM trace_turns)",
            )
            cur.execute(
                "DELETE FROM trace_tools WHERE turn_id NOT IN (SELECT turn_id FROM trace_turns)",
            )
            cur.execute(
                "DELETE FROM trace_intent_resolutions WHERE turn_id NOT IN (SELECT turn_id FROM trace_turns)",
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.exception(f"Failed to delete runtime trace rows: {exc}")

    def clear_all_sessions(self) -> int:
        """Clear all chat session rows and return removed count."""
        if not self._chat_db_path.exists():
            return 0
        conn = self._get_conn()
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM {CHAT_SESSIONS_TABLE} WHERE deleted_at_ms IS NULL"
        ).fetchone()
        removed = int((row["total"] if row is not None else 0) or 0)
        conn.execute(f"DELETE FROM {CHAT_MESSAGES_TABLE}")
        conn.execute(f"DELETE FROM {CHAT_TURNS_TABLE}")
        conn.execute(f"DELETE FROM {CHAT_SESSIONS_TABLE}")
        conn.commit()
        return removed

    def _query_chat_message_rows(
        self,
        *,
        user_id: str,
        session_id: str,
        message_kinds: tuple[str, ...] | None,
        visible_only: bool,
        exclude_replaced: bool,
    ) -> list[sqlite3.Row]:
        query = f"""
            SELECT message_id, session_id, turn_id, user_id, role, message_kind,
                   content_text, payload_json, is_final, is_visible, created_at_ms,
                   sequence_no, replaces_message_id, replaced_by_message_id, reply_to_message_id,
                   label_json
            FROM {CHAT_MESSAGES_TABLE}
            WHERE user_id = ?
              AND session_id = ?
        """
        params: list[Any] = [user_id, session_id]
        if message_kinds:
            query += f" AND message_kind IN ({', '.join('?' for _ in message_kinds)})"
            params.extend(message_kinds)
        if visible_only:
            query += " AND is_visible = 1"
        if exclude_replaced:
            query += " AND replaced_by_message_id IS NULL"
        query += " ORDER BY created_at_ms ASC, sequence_no ASC"
        conn = self._get_conn()
        return conn.execute(query, params).fetchall()

    def _query_turn_rows(self, *, user_id: str, session_id: str) -> list[sqlite3.Row]:
        conn = self._get_conn()
        return conn.execute(
            f"""
            SELECT turn_id, session_id, user_id, status, response_mode, execution_mode,
                   ux_plan_json, created_at_ms, updated_at_ms, completed_at_ms
            FROM {CHAT_TURNS_TABLE}
            WHERE user_id = ?
              AND session_id = ?
            ORDER BY created_at_ms ASC, updated_at_ms ASC
            """,
            (user_id, session_id),
        ).fetchall()

    def _ensure_chat_store_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(CHAT_STORE_SCHEMA_SQL)
        column_names = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({CHAT_TURNS_TABLE})").fetchall()
        }
        if "run_id" not in column_names:
            conn.execute(f"ALTER TABLE {CHAT_TURNS_TABLE} ADD COLUMN run_id TEXT")
        if "run_revision" not in column_names:
            conn.execute(
                f"ALTER TABLE {CHAT_TURNS_TABLE} ADD COLUMN run_revision INTEGER NOT NULL DEFAULT 0"
            )
        if "run_disposition" not in column_names:
            conn.execute(f"ALTER TABLE {CHAT_TURNS_TABLE} ADD COLUMN run_disposition TEXT")
        session_column_names = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({CHAT_SESSIONS_TABLE})").fetchall()
        }
        if "history_version" not in session_column_names:
            conn.execute(
                f"ALTER TABLE {CHAT_SESSIONS_TABLE} ADD COLUMN history_version INTEGER NOT NULL DEFAULT 0"
            )
        if "workspace_path" not in session_column_names:
            conn.execute(f"ALTER TABLE {CHAT_SESSIONS_TABLE} ADD COLUMN workspace_path TEXT")
        message_column_names = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({CHAT_MESSAGES_TABLE})").fetchall()
        }
        if "reply_to_message_id" not in message_column_names:
            conn.execute(f"ALTER TABLE {CHAT_MESSAGES_TABLE} ADD COLUMN reply_to_message_id TEXT")
        if "label_json" not in message_column_names:
            conn.execute(f"ALTER TABLE {CHAT_MESSAGES_TABLE} ADD COLUMN label_json TEXT")

    @staticmethod
    def _parse_turn_ux_preferences(raw_ux_plan_json: str | None) -> dict[str, Any]:
        if not raw_ux_plan_json:
            return {}
        try:
            parsed = json.loads(raw_ux_plan_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _apply_turn_ux_preferences(
        message: ChatDisplayMessage,
        preferences: dict[str, Any] | None,
    ) -> None:
        if not preferences:
            return
        trace_display_mode = preferences.get("trace_display_mode")
        if trace_display_mode is not None:
            message.trace_display_mode = str(trace_display_mode)
        if "allow_trace_collapse" in preferences:
            message.allow_trace_collapse = bool(preferences.get("allow_trace_collapse"))

    @staticmethod
    def _row_to_display_message(row: sqlite3.Row) -> ChatDisplayMessage | None:
        message_kind = str(row["message_kind"] or "")
        content = str(row["content_text"] or "").strip()
        payload = ChatReadService._parse_message_payload_json(row["payload_json"])
        attachments = payload.get("attachments") if isinstance(payload.get("attachments"), list) else []
        if not content and not attachments:
            return None
        role = str(row["role"] or "assistant")
        if message_kind == "user_text":
            return ChatDisplayMessage(
                role="user",
                kind="user",
                content=content,
                attachments=list(attachments),
                timestamp=int(row["created_at_ms"] or 0),
                message_id=str(row["message_id"]),
                message_kind=message_kind,
                turn_id=str(row["turn_id"] or "").strip() or None,
                label=ChatReadService._parse_label_payload(row["label_json"]).to_dict() if ChatReadService._parse_label_payload(row["label_json"]) else None,
            )
        if message_kind in {"assistant_final", "assistant_interim", "assistant_reaction"}:
            return ChatDisplayMessage(
                role=role,
                kind="assistant",
                content=content,
                timestamp=int(row["created_at_ms"] or 0),
                message_id=str(row["message_id"]),
                message_kind=message_kind,
                turn_id=str(row["turn_id"] or "").strip() or None,
                label=ChatReadService._parse_label_payload(row["label_json"]).to_dict() if ChatReadService._parse_label_payload(row["label_json"]) else None,
            )
        if message_kind in {
            "status_note",
            "system_notice",
            "plan_state",
            "todo_state",
            "permission_request",
            "ask_request",
        }:
            return ChatDisplayMessage(
                role=role,
                kind="status",
                content=content,
                timestamp=int(row["created_at_ms"] or 0),
                message_id=str(row["message_id"]),
                message_kind=message_kind,
                turn_id=str(row["turn_id"] or "").strip() or None,
                payload=dict(payload) if isinstance(payload, dict) else None,
                label=ChatReadService._parse_label_payload(row["label_json"]).to_dict() if ChatReadService._parse_label_payload(row["label_json"]) else None,
            )
        if message_kind == "background_task_completion":
            return ChatDisplayMessage(
                role=role,
                kind="status",
                content=content,
                timestamp=int(row["created_at_ms"] or 0),
                message_id=str(row["message_id"]),
                message_kind=message_kind,
                turn_id=str(row["turn_id"] or "").strip() or None,
                payload=dict(payload) if isinstance(payload, dict) else None,
            )
        return None

    @staticmethod
    def _build_reply_preview(target_row: sqlite3.Row | None) -> dict[str, Any] | None:
        if target_row is None:
            return None
        content = str(target_row["content_text"] or "").strip()
        return ChatReplyPreview(
            message_id=str(target_row["message_id"]),
            role=str(target_row["role"] or "assistant"),
            message_kind=str(target_row["message_kind"] or "").strip() or None,
            content_excerpt=content[:160],
        ).to_dict()

    def _attach_reply_previews(
        self,
        *,
        rows: list[sqlite3.Row],
        messages: list[ChatDisplayMessage],
    ) -> None:
        rows_by_message_id = {
            str(row["message_id"]): row
            for row in rows
            if row["message_id"] is not None
        }
        for row, message in zip(rows, messages):
            reply_to_message_id = str(row["reply_to_message_id"] or "").strip()
            if not reply_to_message_id:
                message.reply_to = None
                continue
            target_row = rows_by_message_id.get(reply_to_message_id)
            if target_row is None:
                target_row = self._get_conn().execute(
                    f"""
                    SELECT message_id, role, message_kind, content_text
                    FROM {CHAT_MESSAGES_TABLE}
                    WHERE message_id = ?
                    """,
                    (reply_to_message_id,),
                ).fetchone()
            message.reply_to = self._build_reply_preview(target_row)

    @staticmethod
    def _row_to_session_summary(row: sqlite3.Row) -> ChatSessionSummary:
        return ChatSessionSummary(
            session_id=str(row["session_id"]),
            title=str(row["title"] or ""),
            last_message_preview=str(row["last_message_preview"] or ""),
            last_user_message_preview=str(row["last_user_message_preview"] or ""),
            title_overridden=bool(int(row["title_overridden"] or 0)),
            last_timestamp=int(row["last_message_at_ms"] or row["updated_at_ms"] or 0),
            message_count=int(row["message_count"] or 0),
            workspace_path=str(row["workspace_path"]) if row["workspace_path"] is not None else None,
        )

    @staticmethod
    def _parse_message_payload_json(raw_payload_json: str | None) -> dict[str, Any]:
        if not raw_payload_json:
            return {}
        try:
            parsed = json.loads(raw_payload_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _parse_label_payload(raw_label_json: str | None) -> ChatMessageLabel | None:
        if not raw_label_json:
            return None
        try:
            parsed = json.loads(raw_label_json)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        kind = str(parsed.get("kind") or "").strip()
        text = str(parsed.get("text") or "").strip()
        applied_by = str(parsed.get("applied_by") or "").strip()
        source = str(parsed.get("source") or "").strip()
        created_at_ms = int(parsed.get("created_at_ms") or 0)
        if not kind or not text or not applied_by or not source or created_at_ms <= 0:
            return None
        return ChatMessageLabel(
            kind=kind,
            text=text,
            applied_by=applied_by,
            source=source,
            created_at_ms=created_at_ms,
        )

    @staticmethod
    def _normalize_workspace_path(workspace_path: str | None) -> str | None:
        normalized_workspace_path = str(workspace_path or "").strip()
        return normalized_workspace_path or None

    async def _run_threaded(self, method_name: str, *args: Any) -> Any:
        return await asyncio.to_thread(self._run_isolated, method_name, *args)

    @staticmethod
    def _run_isolated(method_name: str, *args: Any) -> Any:
        service = ChatReadService()
        try:
            method = getattr(service, method_name)
            return method(*args)
        finally:
            service.close()

_chat_read_service: Optional[ChatReadService] = None


def get_chat_read_service() -> ChatReadService:
    """Get the shared ChatReadService instance."""
    global _chat_read_service
    if _chat_read_service is None:
        _chat_read_service = ChatReadService()
    return _chat_read_service
