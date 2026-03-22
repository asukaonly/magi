"""Read-side service for chat sessions and conversation history."""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ...agent.orchestration import get_orchestration_store
from ...core.logger import get_logger
from ...memory.l1.chat_sessions import (
    CHAT_SESSIONS_TABLE,
    CHAT_SESSIONS_SCHEMA_SQL,
    create_chat_session_record,
)
from ...utils.runtime import get_runtime_paths
from .chat_trace_read_service import AI_RESPONSE_EVENT_TYPES, USER_EVENT_TYPES, get_chat_trace_read_service

logger = get_logger(__name__)

FACT_EVENTS_TABLE = "fact_events"


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "last_message_preview": self.last_message_preview,
            "last_user_message_preview": self.last_user_message_preview,
            "title_overridden": self.title_overridden,
            "last_timestamp": self.last_timestamp,
            "message_count": self.message_count,
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
class ChatDisplayMessage:
    """Typed read model for chat history and display timeline messages."""

    role: str
    content: str
    timestamp: int
    kind: str
    turn_id: str | None = None
    trace_summary: dict[str, Any] | None = None
    trace_available: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "turn_id": self.turn_id,
            "kind": self.kind,
            "trace_summary": self.trace_summary,
            "trace_available": self.trace_available,
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
        self._l1_db_path: Path = runtime_paths.l1_memory_db_path
        self._runtime_trace_db_path: Path = runtime_paths.runtime_trace_db_path
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        """Return a reusable SQLite connection, creating one lazily."""
        if self._conn is None:
            self._l1_db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._l1_db_path))
            self._conn.row_factory = sqlite3.Row
            self._ensure_chat_sessions_table(self._conn)
        return self._conn

    def close(self) -> None:
        """Close the cached SQLite connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    async def acreate_new_session(self, user_id: str) -> str:
        """Create a session without blocking the event loop."""
        return await self._run_threaded("create_new_session", user_id)

    async def aget_worker_result(self, worker_id: str) -> Optional[dict[str, Any]]:
        """Load a worker result without blocking the event loop."""
        return await self._run_threaded("get_worker_result", worker_id)

    async def alist_sessions(self, user_id: str, limit: int = 30) -> list[ChatSessionSummary]:
        """List sessions without blocking the event loop."""
        return await self._run_threaded("list_sessions", user_id, limit)

    async def arename_session(self, user_id: str, session_id: str, title: str) -> ChatSessionRenameResult:
        """Rename a session without blocking the event loop."""
        return await self._run_threaded("rename_session", user_id, session_id, title)

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

    async def aclear_conversation_history(self, user_id: str, session_id: str) -> None:
        """Clear a session history without blocking the event loop."""
        await self._run_threaded("clear_conversation_history", user_id, session_id)

    async def aclear_all_sessions(self) -> int:
        """Clear all sessions without blocking the event loop."""
        return await self._run_threaded("clear_all_sessions")

    def create_new_session(self, user_id: str) -> str:
        normalized_user_id = str(user_id).strip()
        if not normalized_user_id:
            raise ValueError("User ID is required")
        record = create_chat_session_record(user_id=normalized_user_id)
        conn = self._get_conn()
        conn.execute(
            f"""
            INSERT INTO {CHAT_SESSIONS_TABLE} (
                session_id, user_id, title, title_overridden, summary, created_at, updated_at,
                last_message_at, last_user_message_at, last_message_preview,
                last_user_message_preview, message_count, archived_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.session_id,
                record.user_id,
                record.title,
                1 if record.title_overridden else 0,
                record.summary,
                record.created_at,
                record.updated_at,
                record.last_message_at,
                record.last_user_message_at,
                record.last_message_preview,
                record.last_user_message_preview,
                record.message_count,
                record.archived_at,
                record.deleted_at,
            ),
        )
        conn.commit()
        return record.session_id

    def get_worker_result(self, worker_id: str) -> Optional[dict[str, Any]]:
        if not worker_id.strip():
            return None
        store = get_orchestration_store()
        return store.get_worker_result_sync(worker_id)

    def list_sessions(self, user_id: str, limit: int = 30) -> list[ChatSessionSummary]:
        """List recent chat sessions for a user."""
        safe_limit = max(1, min(limit, 200))
        if not self._l1_db_path.exists():
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
                    updated_at,
                    last_message_at,
                    message_count
                FROM {CHAT_SESSIONS_TABLE}
                WHERE user_id = ?
                  AND deleted_at IS NULL
                  AND archived_at IS NULL
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                (user_id, safe_limit),
            ).fetchall()
        except Exception as exc:
            logger.exception(f"Failed to query session list: {exc}")
            return []

        return [
            ChatSessionSummary(
                session_id=str(row["session_id"]),
                title=str(row["title"] or "New Chat"),
                last_message_preview=str(row["last_message_preview"] or ""),
                last_user_message_preview=str(row["last_user_message_preview"] or ""),
                title_overridden=bool(int(row["title_overridden"] or 0)),
                last_timestamp=int(float(row["last_message_at"] or row["updated_at"] or 0)),
                message_count=int(row["message_count"] or 0),
            )
            for row in rows
        ]

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
            SET title = ?, title_overridden = 1, updated_at = strftime('%s', 'now')
            WHERE session_id = ?
              AND user_id = ?
              AND deleted_at IS NULL
            """,
            (normalized_title, normalized_session_id, normalized_user_id),
        )
        conn.commit()
        if cur.rowcount <= 0:
            raise ValueError("Session not found")
        return ChatSessionRenameResult(session_id=normalized_session_id, title=normalized_title)

    def delete_session(self, user_id: str, session_id: str) -> None:
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")

        if self._l1_db_path.exists():
            try:
                conn = self._get_conn()
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
            except Exception as exc:
                logger.exception(f"Failed to delete session: {exc}")
        self._delete_runtime_trace_rows(user_id=normalized_user_id, session_id=normalized_session_id)

        conn = self._get_conn()
        conn.execute(
            f"""
            UPDATE {CHAT_SESSIONS_TABLE}
            SET deleted_at = strftime('%s', 'now'), updated_at = strftime('%s', 'now')
            WHERE user_id = ?
              AND session_id = ?
              AND deleted_at IS NULL
            """,
            (normalized_user_id, normalized_session_id),
        )
        conn.commit()
        return None

    def get_conversation_history(self, user_id: str, session_id: str, limit: int = 200) -> list[ChatDisplayMessage]:
        if not self._l1_db_path.exists():
            return []
        safe_limit = max(1, min(limit, 1000))
        try:
            rows = self._query_fact_rows(
                event_types=USER_EVENT_TYPES + AI_RESPONSE_EVENT_TYPES,
                user_id=user_id,
                session_id=session_id,
                limit=safe_limit,
                ascending=True,
            )
        except Exception as exc:
            logger.exception(f"Failed to query chat history: {exc}")
            return []

        messages: list[ChatDisplayMessage] = []
        for event_type, content, ts, _, turn_id in rows:
            if event_type in USER_EVENT_TYPES:
                role = "user"
            elif event_type in AI_RESPONSE_EVENT_TYPES:
                role = "assistant"
            else:
                continue
            if not content:
                continue
            messages.append(
                ChatDisplayMessage(
                    role=role,
                    content=str(content),
                    timestamp=int(float(ts or 0)),
                    turn_id=str(turn_id or "").strip() or None,
                    kind=role,
                )
            )
        return messages

    def get_display_history(self, user_id: str, session_id: str, limit: int = 200) -> list[ChatDisplayMessage]:
        if not self._l1_db_path.exists():
            return []
        safe_limit = max(1, min(limit, 1000))
        try:
            fact_rows = self._query_fact_rows(
                event_types=USER_EVENT_TYPES + AI_RESPONSE_EVENT_TYPES,
                user_id=user_id,
                session_id=session_id,
                limit=None,
                ascending=True,
            )
        except Exception as exc:
            logger.exception(f"Failed to query display history: {exc}")
            return []

        trace_service = get_chat_trace_read_service()
        trace_activity = trace_service.get_turn_activity_map(user_id=user_id, session_id=session_id)
        by_turn: dict[str, dict[str, Any]] = {}
        ordered_turns: list[str] = []
        legacy_messages: list[ChatDisplayMessage] = []

        for event_type, raw_content, ts, _, turn_id in fact_rows:
            turn_id = str(turn_id or "").strip()
            timestamp = int(float(ts or 0))
            if event_type in USER_EVENT_TYPES:
                message = str(raw_content or "").strip()
                if not message:
                    continue
                if not turn_id:
                    legacy_messages.append(
                        ChatDisplayMessage(role="user", kind="user", content=message, timestamp=timestamp)
                    )
                    continue
                turn = by_turn.setdefault(turn_id, {"user": None, "assistant": None, "has_trace": False, "last_trace_timestamp": timestamp})
                if turn_id not in ordered_turns:
                    ordered_turns.append(turn_id)
                turn["user"] = ChatDisplayMessage(
                    role="user",
                    kind="user",
                    content=message,
                    timestamp=timestamp,
                    turn_id=turn_id,
                )
                continue
            if event_type in AI_RESPONSE_EVENT_TYPES:
                response = str(raw_content or "").strip()
                if not response:
                    continue
                if not turn_id:
                    legacy_messages.append(
                        ChatDisplayMessage(role="assistant", kind="assistant", content=response, timestamp=timestamp)
                    )
                    continue
                turn = by_turn.setdefault(turn_id, {"user": None, "assistant": None, "has_trace": False, "last_trace_timestamp": timestamp})
                summary = trace_service.get_trace_summary(user_id=user_id, session_id=session_id, turn_id=turn_id)
                turn["assistant"] = ChatDisplayMessage(
                    role="assistant",
                    kind="assistant",
                    content=response,
                    timestamp=timestamp,
                    turn_id=turn_id,
                    trace_summary=summary or trace_activity.get(turn_id),
                    trace_available=bool((summary or trace_activity.get(turn_id) or {}).get("trace_available")),
                )
                continue

        messages: list[ChatDisplayMessage] = []
        for turn_id in ordered_turns:
            turn = by_turn.get(turn_id, {})
            user_message = turn.get("user")
            if isinstance(user_message, ChatDisplayMessage):
                messages.append(user_message)
            assistant_message = turn.get("assistant")
            if isinstance(assistant_message, ChatDisplayMessage):
                messages.append(assistant_message)
                continue
            summary = trace_activity.get(turn_id) or trace_service.get_trace_summary(
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
            )
            if summary is not None:
                messages.append(
                    ChatDisplayMessage(
                        role="assistant",
                        kind="status",
                        content=str((summary or {}).get("headline") or "Thinking"),
                        timestamp=int(getattr(user_message, "timestamp", 0) or 0),
                        turn_id=turn_id,
                        trace_summary=summary,
                        trace_available=bool(summary and summary.get("trace_available")),
                    )
                )
        messages.extend(legacy_messages)
        messages.sort(key=lambda item: item.timestamp)
        return messages[-safe_limit:]

    def clear_conversation_history(self, user_id: str, session_id: str) -> None:
        if not self._l1_db_path.exists():
            return
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                f"""
                DELETE FROM {FACT_EVENTS_TABLE}
                WHERE deleted_at IS NULL
                  AND event_type IN ({", ".join("?" for _ in (USER_EVENT_TYPES + AI_RESPONSE_EVENT_TYPES))})
                  AND user_id = ?
                  AND session_id = ?
                """,
                [*(USER_EVENT_TYPES + AI_RESPONSE_EVENT_TYPES), user_id, session_id],
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
            conn = sqlite3.connect(str(self._runtime_trace_db_path))
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
        if not self._l1_db_path.exists():
            return 0
        conn = self._get_conn()
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM {CHAT_SESSIONS_TABLE} WHERE deleted_at IS NULL"
        ).fetchone()
        removed = int((row["total"] if row is not None else 0) or 0)
        conn.execute(f"DELETE FROM {CHAT_SESSIONS_TABLE}")
        conn.commit()
        return removed

    def _ensure_chat_sessions_table(self, conn: sqlite3.Connection) -> None:
        conn.executescript(CHAT_SESSIONS_SCHEMA_SQL)

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
