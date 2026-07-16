"""Session lifecycle operations for the chat read service."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Protocol, cast

from ...core.logger import get_logger
from ...core.sqlite import connect_sqlite
from ...memory.l1.chat_sessions import ChatSessionRecord, create_chat_session_record
from .models import ChatSessionRenameResult, ChatSessionSummary, SessionWorkspaceUpdateResult
from .schema import (
    CHAT_ATTACHMENTS_TABLE,
    CHAT_CONTEXT_SUMMARIES_TABLE,
    CHAT_MESSAGES_TABLE,
    CHAT_RUN_CONSUMED_EVENTS_TABLE,
    CHAT_SESSIONS_TABLE,
    CHAT_TURNS_TABLE,
    CHAT_USER_TURN_DELIVERY_TABLE,
)

logger = get_logger(__name__)

FACT_EVENTS_TABLE = "fact_events"
_CLIENT_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class _ChatSessionOperationsHost(Protocol):
    _chat_db_path: Path
    _l1_db_path: Path

    def _get_conn(self) -> sqlite3.Connection: ...

    def _normalize_workspace_path(self, workspace_path: str | None) -> str | None: ...

    def _row_to_session_summary(self, row: sqlite3.Row) -> ChatSessionSummary: ...

    def _delete_runtime_trace_rows(self, *, user_id: str, session_id: str) -> None: ...

    def _delete_chat_session_assets(self, *, session_id: str) -> None: ...

    def _clear_all_chat_assets(self) -> None: ...

    def _clear_all_runtime_trace_rows(self) -> None: ...


def _insert_or_return_session(
    *,
    host: _ChatSessionOperationsHost,
    record: ChatSessionRecord,
    normalized_user_id: str,
    normalized_client_session_id: str | None,
) -> str:
    conn = host._get_conn()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if normalized_client_session_id is not None:
            existing = conn.execute(
                f"""
                SELECT user_id, archived_at_ms, deleted_at_ms
                FROM {CHAT_SESSIONS_TABLE}
                WHERE session_id = ?
                """,
                (normalized_client_session_id,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["user_id"]) == normalized_user_id
                    and existing["archived_at_ms"] is None
                    and existing["deleted_at_ms"] is None
                ):
                    conn.commit()
                    return normalized_client_session_id
                raise ValueError("Client session ID is not available")

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
                int(record.last_user_message_at * 1000)
                if record.last_user_message_at is not None
                else None,
                record.last_message_preview,
                record.last_user_message_preview,
                record.message_count,
                record.workspace_path,
                int(record.archived_at * 1000) if record.archived_at is not None else None,
                int(record.deleted_at * 1000) if record.deleted_at is not None else None,
            ),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return str(record.session_id)


class ChatSessionOperationsMixin:
    """Create, update, list, and delete chat sessions."""

    def create_new_session(
        self,
        user_id: str,
        workspace_path: str | None = None,
        client_session_id: str | None = None,
    ) -> str:
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id).strip()
        if not normalized_user_id:
            raise ValueError("User ID is required")
        normalized_client_session_id = str(client_session_id or "").strip() or None
        if normalized_client_session_id is not None and not _CLIENT_SESSION_ID_PATTERN.fullmatch(
            normalized_client_session_id
        ):
            raise ValueError(
                "Client session ID must contain only letters, numbers, underscores, or hyphens and be at most 128 characters"
            )
        record = create_chat_session_record(
            user_id=normalized_user_id,
            session_id=normalized_client_session_id,
            workspace_path=host._normalize_workspace_path(workspace_path),
        )
        return _insert_or_return_session(
            host=host,
            record=record,
            normalized_user_id=normalized_user_id,
            normalized_client_session_id=normalized_client_session_id,
        )

    def get_session_summary(self, user_id: str, session_id: str) -> ChatSessionSummary | None:
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")
        if not host._chat_db_path.exists():
            return None
        row = (
            host._get_conn()
            .execute(
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
                message_count,
                history_version
            FROM {CHAT_SESSIONS_TABLE}
            WHERE user_id = ?
              AND session_id = ?
              AND deleted_at_ms IS NULL
              AND archived_at_ms IS NULL
            """,
                (normalized_user_id, normalized_session_id),
            )
            .fetchone()
        )
        return host._row_to_session_summary(row) if row is not None else None

    def get_session_summaries_batch(
        self,
        user_id: str,
        session_ids: list[str],
    ) -> dict[str, ChatSessionSummary]:
        """Fetch multiple session summaries in one query."""
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id).strip()
        if not normalized_user_id or not session_ids:
            return {}
        if not host._chat_db_path.exists():
            return {}
        clean_ids = [str(sid).strip() for sid in session_ids if str(sid).strip()]
        if not clean_ids:
            return {}
        placeholders = ", ".join("?" for _ in clean_ids)
        rows = (
            host._get_conn()
            .execute(
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
                message_count,
                history_version
            FROM {CHAT_SESSIONS_TABLE}
            WHERE user_id = ?
              AND session_id IN ({placeholders})
              AND deleted_at_ms IS NULL
              AND archived_at_ms IS NULL
            """,
                (normalized_user_id, *clean_ids),
            )
            .fetchall()
        )
        return {str(row["session_id"]): host._row_to_session_summary(row) for row in rows}

    def list_sessions(self, user_id: str, limit: int = 30) -> list[ChatSessionSummary]:
        """List recent chat sessions for a user."""
        host = cast(_ChatSessionOperationsHost, self)
        safe_limit = max(1, min(limit, 200))
        if not host._chat_db_path.exists():
            return []
        try:
            conn = host._get_conn()
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
                    message_count,
                    history_version
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

        return [host._row_to_session_summary(row) for row in rows]

    def rename_session(self, user_id: str, session_id: str, title: str) -> ChatSessionRenameResult:
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        normalized_title = str(title).strip()
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")
        if not normalized_title:
            raise ValueError("Session title cannot be empty")
        conn = host._get_conn()
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
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        normalized_workspace_path = host._normalize_workspace_path(workspace_path)
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")
        conn = host._get_conn()
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
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")

        if host._l1_db_path.exists():
            try:
                conn = connect_sqlite(host._l1_db_path, profile="hot_write")
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
        host._delete_runtime_trace_rows(
            user_id=normalized_user_id, session_id=normalized_session_id
        )
        host._delete_chat_session_assets(session_id=normalized_session_id)

        conn = host._get_conn()
        conn.execute(
            f"DELETE FROM {CHAT_MESSAGES_TABLE} WHERE user_id = ? AND session_id = ?",
            (normalized_user_id, normalized_session_id),
        )
        conn.execute(
            f"DELETE FROM {CHAT_ATTACHMENTS_TABLE} WHERE user_id = ? AND session_id = ?",
            (normalized_user_id, normalized_session_id),
        )
        conn.execute(
            f"""
            DELETE FROM {CHAT_USER_TURN_DELIVERY_TABLE}
            WHERE turn_id IN (
                SELECT turn_id
                FROM {CHAT_TURNS_TABLE}
                WHERE user_id = ? AND session_id = ?
            )
            """,
            (normalized_user_id, normalized_session_id),
        )
        conn.execute(
            f"DELETE FROM {CHAT_TURNS_TABLE} WHERE user_id = ? AND session_id = ?",
            (normalized_user_id, normalized_session_id),
        )
        conn.execute(
            f"DELETE FROM {CHAT_CONTEXT_SUMMARIES_TABLE} WHERE session_id = ?",
            (normalized_session_id,),
        )
        conn.execute(
            f"DELETE FROM {CHAT_RUN_CONSUMED_EVENTS_TABLE} WHERE session_id = ?",
            (normalized_session_id,),
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

    def clear_all_sessions(self) -> int:
        """Clear all chat session rows and return removed count."""
        host = cast(_ChatSessionOperationsHost, self)
        host._clear_all_runtime_trace_rows()
        if not host._chat_db_path.exists():
            host._clear_all_chat_assets()
            return 0
        conn = host._get_conn()
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM {CHAT_SESSIONS_TABLE} WHERE deleted_at_ms IS NULL"
        ).fetchone()
        removed = int((row["total"] if row is not None else 0) or 0)
        conn.execute(f"DELETE FROM {CHAT_MESSAGES_TABLE}")
        conn.execute(f"DELETE FROM {CHAT_ATTACHMENTS_TABLE}")
        conn.execute(f"DELETE FROM {CHAT_USER_TURN_DELIVERY_TABLE}")
        conn.execute(f"DELETE FROM {CHAT_TURNS_TABLE}")
        conn.execute(f"DELETE FROM {CHAT_CONTEXT_SUMMARIES_TABLE}")
        conn.execute(f"DELETE FROM {CHAT_RUN_CONSUMED_EVENTS_TABLE}")
        conn.execute(f"DELETE FROM {CHAT_SESSIONS_TABLE}")
        conn.commit()
        host._clear_all_chat_assets()
        return removed

    def reset_user_turn_delivery_after_failed_clear(self) -> int:
        """Make surviving chat turns replayable after a partial global clear."""
        host = cast(_ChatSessionOperationsHost, self)
        if not host._chat_db_path.exists():
            return 0
        conn = host._get_conn()
        cursor = conn.execute(
            f"""
            UPDATE {CHAT_USER_TURN_DELIVERY_TABLE}
            SET projection_completed = 0,
                runtime_enqueued = 0,
                updated_at_ms = CAST(strftime('%s', 'now') AS INTEGER) * 1000
            WHERE projection_completed != 0 OR runtime_enqueued != 0
            """
        )
        conn.commit()
        return int(cursor.rowcount or 0)


__all__ = ["ChatSessionOperationsMixin"]
