"""Read-side service for chat sessions and conversation history."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from ..agent.orchestration import get_orchestration_store
from ..config import get_config
from ..core.logger import get_logger
from ..core.sqlite import connect_sqlite
from ..utils.runtime import get_runtime_paths
from .asset_gc import ChatAssetGC
from .message_frontier import (
    MESSAGE_FRONTIER_SELECT_SQL,
    MESSAGE_ORDER_SQL,
    build_inclusive_frontier_filter,
)
from .read.models import (
    ChatDisplayMessage,
    ChatSessionRenameResult,
    ChatSessionSummary,
    SessionWorkspaceUpdateResult,
)
from .read.history_operations import ChatHistoryOperationsMixin
from .read.session_operations import ChatSessionOperationsMixin
from .read.schema import (
    CHAT_MESSAGES_TABLE,
    CHAT_TURNS_TABLE,
)
from .read.serialization import (
    apply_turn_ux_preferences,
    build_reply_preview,
    normalize_workspace_path,
    parse_label_payload,
    parse_message_payload_json,
    parse_turn_ux_preferences,
    row_to_display_message,
    row_to_session_summary,
)

if TYPE_CHECKING:
    from .contracts import ChatMessageLabel

logger = get_logger(__name__)

FACT_EVENTS_TABLE = "fact_events"


class ChatReadService(ChatSessionOperationsMixin, ChatHistoryOperationsMixin):
    """Query chat session and history from persistent storage."""

    def __init__(self) -> None:
        runtime_paths = get_runtime_paths()
        self._runtime_paths = runtime_paths
        self._chat_db_path: Path = runtime_paths.chat_db_path
        self._l1_db_path: Path = runtime_paths.l1_memory_db_path
        self._runtime_trace_db_path: Path = runtime_paths.runtime_trace_db_path
        self._asset_gc = ChatAssetGC(runtime_paths=runtime_paths)
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        """Return a reusable SQLite connection, creating one lazily."""
        if self._conn is None:
            self._chat_db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = connect_sqlite(self._chat_db_path, profile="mixed")
        return self._conn

    def close(self) -> None:
        """Close the cached SQLite connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    async def acreate_new_session(
        self, user_id: str, workspace_path: str | None = None
    ) -> str:
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
        return await self._run_threaded(
            "get_session_summaries_batch", user_id, session_ids
        )

    async def alist_sessions(
        self, user_id: str, limit: int = 30
    ) -> list[ChatSessionSummary]:
        """List sessions without blocking the event loop."""
        return await self._run_threaded("list_sessions", user_id, limit)

    async def arename_session(
        self, user_id: str, session_id: str, title: str
    ) -> ChatSessionRenameResult:
        """Rename a session without blocking the event loop."""
        return await self._run_threaded("rename_session", user_id, session_id, title)

    async def aupdate_session_workspace(
        self,
        user_id: str,
        session_id: str,
        workspace_path: str | None,
    ) -> SessionWorkspaceUpdateResult:
        """Update a session workspace path without blocking the event loop."""
        return await self._run_threaded(
            "update_session_workspace", user_id, session_id, workspace_path
        )

    async def adelete_session(self, user_id: str, session_id: str) -> None:
        """Delete a session without blocking the event loop."""
        await self._run_threaded("delete_session", user_id, session_id)

    async def aget_conversation_history(
        self,
        user_id: str,
        session_id: str,
        limit: int | None = 200,
    ) -> list[ChatDisplayMessage]:
        """Load conversation history without blocking the event loop."""
        return await self._run_threaded(
            "get_conversation_history", user_id, session_id, limit
        )

    async def aget_session_attachment_references(
        self,
        user_id: str,
        session_id: str,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        """Load recent session attachment references without blocking the event loop."""
        return await self._run_threaded(
            "get_session_attachment_references",
            user_id,
            session_id,
            limit,
        )

    async def aget_display_history(
        self,
        user_id: str,
        session_id: str,
        limit: int = 200,
    ) -> list[ChatDisplayMessage]:
        """Load display history without blocking the event loop."""
        return await self._run_threaded(
            "get_display_history", user_id, session_id, limit
        )

    async def aget_display_message(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> ChatDisplayMessage | None:
        """Load one visible display message without blocking the event loop."""
        return await self._run_threaded(
            "get_display_message", user_id, session_id, message_id
        )

    async def aget_attachment_payload(
        self,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        """Load one persisted attachment payload without blocking the event loop."""
        return await self._run_threaded(
            "get_attachment_payload", user_id, session_id, attachment_id
        )

    async def aclear_conversation_history(self, user_id: str, session_id: str) -> None:
        """Clear a session history without blocking the event loop."""
        await self._run_threaded("clear_conversation_history", user_id, session_id)

    async def aclear_all_sessions(self) -> int:
        """Clear all sessions without blocking the event loop."""
        return await self._run_threaded("clear_all_sessions")

    def get_worker_result(self, worker_id: str) -> Optional[dict[str, Any]]:
        if not worker_id.strip():
            return None
        store = get_orchestration_store()
        return store.get_worker_result_sync(worker_id)

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
            cur.execute(
                "DELETE FROM runtime_notifications WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.exception(f"Failed to delete runtime trace rows: {exc}")

    def _clear_all_runtime_trace_rows(self) -> None:
        """Delete all chat execution traces and live chat notifications."""
        if not self._runtime_trace_db_path.exists():
            return
        conn = connect_sqlite(self._runtime_trace_db_path, profile="hot_write")
        try:
            existing_tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            for table in (
                "trace_intent_resolutions",
                "trace_llm_calls",
                "trace_tools",
                "trace_spans",
                "trace_turns",
            ):
                if table in existing_tables:
                    conn.execute(f"DELETE FROM {table}")
            if "runtime_notifications" in existing_tables:
                conn.execute(
                    """
                    DELETE FROM runtime_notifications
                    WHERE TRIM(session_id) <> '' OR turn_id IS NOT NULL
                    """
                )
            if "user_notifications" in existing_tables:
                conn.execute(
                    """
                    DELETE FROM user_notifications
                    WHERE kind = 'suggestion'
                      AND dedupe_key LIKE 'profile_conflict:%'
                    """
                )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Failed to clear runtime trace rows")
            raise
        finally:
            conn.close()

    def _delete_chat_session_assets(self, *, session_id: str) -> None:
        if not get_config().lifecycle.chat_assets.delete_on_session_delete:
            return
        self._asset_gc.delete_session_assets(session_id)

    def _clear_all_chat_assets(self) -> None:
        if not get_config().lifecycle.chat_assets.delete_on_clear_memory:
            return
        self._asset_gc.clear_all_assets()

    def _query_chat_message_rows(
        self,
        *,
        user_id: str,
        session_id: str,
        message_kinds: tuple[str, ...] | None,
        visible_only: bool,
        exclude_replaced: bool,
        start_message_id: str | None = None,
    ) -> list[sqlite3.Row]:
        query = f"""
            SELECT message_id, session_id, turn_id, user_id, role, message_kind,
                   content_text, payload_json, is_final, is_visible, created_at_ms,
                     sequence_no, replaces_message_id, replaced_by_message_id, persona_id,
                     reply_to_message_id, label_json
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
        conn = self._get_conn()
        normalized_start = str(start_message_id or "").strip()
        if normalized_start:
            boundary = conn.execute(
                MESSAGE_FRONTIER_SELECT_SQL,
                (session_id, normalized_start),
            ).fetchone()
            if boundary is not None:
                frontier_sql, frontier_params = build_inclusive_frontier_filter(
                    boundary,
                    message_id=normalized_start,
                )
                query += frontier_sql
                params.extend(frontier_params)
        query += f" ORDER BY {MESSAGE_ORDER_SQL}"
        return conn.execute(query, params).fetchall()

    def _query_turn_rows(self, *, user_id: str, session_id: str) -> list[sqlite3.Row]:
        conn = self._get_conn()
        return conn.execute(
            f"""
            SELECT turn_id, session_id, user_id, status, response_mode, execution_mode,
                     ux_plan_json, created_at_ms, updated_at_ms, completed_at_ms,
                     error_text, run_id, run_revision, run_disposition
            FROM {CHAT_TURNS_TABLE}
            WHERE user_id = ?
              AND session_id = ?
            ORDER BY created_at_ms ASC, updated_at_ms ASC
            """,
            (user_id, session_id),
        ).fetchall()

    @staticmethod
    def _parse_turn_ux_preferences(raw_ux_plan_json: str | None) -> dict[str, Any]:
        return parse_turn_ux_preferences(raw_ux_plan_json)

    @staticmethod
    def _apply_turn_ux_preferences(
        message: ChatDisplayMessage,
        preferences: dict[str, Any] | None,
    ) -> None:
        apply_turn_ux_preferences(message, preferences)

    @staticmethod
    def _row_to_display_message(row: sqlite3.Row) -> ChatDisplayMessage | None:
        return row_to_display_message(row)

    @staticmethod
    def _build_reply_preview(target_row: sqlite3.Row | None) -> dict[str, Any] | None:
        return build_reply_preview(target_row)

    def _attach_reply_previews(
        self,
        *,
        rows: list[sqlite3.Row],
        messages: list[ChatDisplayMessage],
    ) -> None:
        rows_by_message_id = {
            str(row["message_id"]): row for row in rows if row["message_id"] is not None
        }
        for row, message in zip(rows, messages):
            reply_to_message_id = str(row["reply_to_message_id"] or "").strip()
            if not reply_to_message_id:
                message.reply_to = None
                continue
            target_row = rows_by_message_id.get(reply_to_message_id)
            if target_row is None:
                target_row = (
                    self._get_conn()
                    .execute(
                        f"""
                    SELECT message_id, role, message_kind, content_text
                    FROM {CHAT_MESSAGES_TABLE}
                    WHERE message_id = ?
                    """,
                        (reply_to_message_id,),
                    )
                    .fetchone()
                )
            message.reply_to = self._build_reply_preview(target_row)

    @staticmethod
    def _row_to_session_summary(row: sqlite3.Row) -> ChatSessionSummary:
        return row_to_session_summary(row)

    @staticmethod
    def _parse_message_payload_json(raw_payload_json: str | None) -> dict[str, Any]:
        return parse_message_payload_json(raw_payload_json)

    @staticmethod
    def _parse_label_payload(raw_label_json: str | None) -> ChatMessageLabel | None:
        return parse_label_payload(raw_label_json)

    @staticmethod
    def _normalize_workspace_path(workspace_path: str | None) -> str | None:
        return normalize_workspace_path(workspace_path)

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


def get_chat_read_service() -> ChatReadService:
    """Get the shared ChatReadService instance."""
    from .read.provider import (
        get_chat_read_service as _get_chat_read_service,
    )

    return _get_chat_read_service()


def get_chat_trace_read_service() -> Any:
    """Get the shared ChatTraceReadService instance."""
    from ..runtime_trace.chat_trace.read_service import (
        get_chat_trace_read_service as _get_chat_trace_read_service,
    )

    return _get_chat_trace_read_service()
