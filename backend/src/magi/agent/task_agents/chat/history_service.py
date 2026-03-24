"""History caches and explicit session validation for chat task agents."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from ....core.logger import get_logger
from ....core.sqlite import connect_sqlite
from ....utils.runtime import get_runtime_paths
from ....chat import ChatStore

logger = get_logger(__name__)

FACT_EVENTS_TABLE = "fact_events"


@dataclass(slots=True)
class CachedConversationHistory:
    """In-memory conversation history paired with the durable transcript version."""

    version: int
    messages: list[dict[str, Any]]
    loaded_at_ms: int = 0


class ChatHistoryService:
    """Owns history caches and lazy history loading for explicit sessions."""

    def __init__(
        self,
        *,
        l1_db_path: Path,
        runtime_trace_db_path: Optional[Path] = None,
        history_cache_max_sessions: int = 500,
        history_fetch_limit: int = 200,
        chat_store: ChatStore | None = None,
        chat_read_service_factory: Callable[[], Any] | None = None,
    ) -> None:
        runtime_paths = get_runtime_paths()
        self._l1_db_path = l1_db_path
        self._runtime_trace_db_path = runtime_trace_db_path or runtime_paths.runtime_trace_db_path
        self._history_cache_max_sessions = history_cache_max_sessions
        self._history_fetch_limit = history_fetch_limit
        self._conversation_history: dict[str, CachedConversationHistory] = {}
        self._tool_interactions: dict[str, list[dict[str, Any]]] = {}
        self._history_cache_order: list[str] = []
        self._chat_store = chat_store
        self._chat_read_service_factory = chat_read_service_factory

    async def get_or_load_history(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        history_key = self.history_key(user_id, session_id)
        durable_version = 0
        if self._chat_store is not None:
            durable_version = await self._chat_store.get_history_version(session_id)
        cached_entry = self._conversation_history.get(history_key)
        if cached_entry is not None and cached_entry.version == durable_version:
            return cached_entry.messages
        try:
            read_service = self._get_chat_read_service()
            history = read_service.get_conversation_history(
                user_id=user_id,
                session_id=session_id,
                limit=self._history_fetch_limit,
            )
            self._conversation_history[history_key] = CachedConversationHistory(
                version=durable_version,
                messages=[item.to_prompt_message() for item in history],
            )
            self._update_lru_cache(history_key)
            return self._conversation_history[history_key].messages
        except Exception as exc:
            logger.warning(
                "Failed to lazy load history | user=%s session=%s error=%s",
                user_id,
                session_id,
                exc,
            )
            cached = self._conversation_history.setdefault(
                history_key,
                CachedConversationHistory(version=durable_version, messages=[]),
            )
            return cached.messages

    def require_session_id(self, user_id: str, session_id: Optional[str] = None) -> str:
        _ = user_id
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("Session ID is required")
        return normalized_session_id

    def history_key(self, user_id: str, session_id: str) -> str:
        return f"{user_id}::{session_id}"

    def get_history(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        cached = self._conversation_history.setdefault(
            self.history_key(user_id, session_id),
            CachedConversationHistory(version=0, messages=[]),
        )
        return cached.messages

    def append_user_message(self, history_key: str, user_message: str) -> None:
        if not user_message:
            return
        cached = self._conversation_history.setdefault(
            history_key,
            CachedConversationHistory(version=0, messages=[]),
        )
        history = cached.messages
        if history and history[-1].get("role") == "user" and history[-1].get("content") == user_message:
            return
        history.append({"role": "user", "content": user_message})
        self._update_lru_cache(history_key)

    def append_assistant_message(self, history_key: str, response_text: str) -> None:
        if not response_text:
            return
        cached = self._conversation_history.setdefault(
            history_key,
            CachedConversationHistory(version=0, messages=[]),
        )
        cached.messages.append({"role": "assistant", "content": response_text})
        self._update_lru_cache(history_key)

    def store_tool_interaction(self, history_key: str, record: dict[str, Any]) -> None:
        records = self._tool_interactions.setdefault(history_key, [])
        records.append(record)
        if len(records) > 100:
            self._tool_interactions[history_key] = records[-100:]
        self._update_lru_cache(history_key)

    def get_recent_tool_errors(self, history_key: str, limit: int = 3) -> list[dict[str, Any]]:
        records = self._tool_interactions.get(history_key, [])
        results: list[dict[str, Any]] = []
        for item in reversed(records):
            if str(item.get("status") or "") != "error":
                continue
            result_data = item.get("result_data")
            config_path = None
            next_action = None
            if isinstance(result_data, dict):
                raw_path = result_data.get("config_path")
                if raw_path is not None:
                    config_path = str(raw_path).strip() or None
                raw_action = result_data.get("next_action")
                if raw_action is not None:
                    next_action = str(raw_action).strip() or None
            results.append(
                {
                    "tool_name": str(item.get("tool_name") or "unknown"),
                    "error_code": str(item.get("error_code") or "UNKNOWN"),
                    "error_message": str(item.get("error_message") or ""),
                    "config_path": config_path,
                    "next_action": next_action,
                }
            )
            if len(results) >= max(1, limit):
                break
        return results

    def get_conversation_history(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        active_session = self.require_session_id(user_id, session_id)
        cached = self._conversation_history.get(self.history_key(user_id, active_session))
        if cached is None:
            return []
        return cached.messages

    def clear_conversation_history(self, user_id: str, session_id: str) -> None:
        active_session = self.require_session_id(user_id, session_id)
        key = self.history_key(user_id, active_session)
        current_version = self._conversation_history.get(key).version if key in self._conversation_history else 0
        self._conversation_history[key] = CachedConversationHistory(version=current_version, messages=[])
        self._tool_interactions[key] = []

    def _update_lru_cache(self, history_key: str) -> None:
        if history_key in self._history_cache_order:
            self._history_cache_order.remove(history_key)
        self._history_cache_order.append(history_key)
        while len(self._history_cache_order) > self._history_cache_max_sessions:
            oldest_key = self._history_cache_order.pop(0)
            self._conversation_history.pop(oldest_key, None)
            self._tool_interactions.pop(oldest_key, None)
            logger.debug("Evicted history cache | key=%s", oldest_key)

    def _get_chat_read_service(self):  # type: ignore[no-untyped-def]
        if self._chat_read_service_factory is not None:
            read_service = self._chat_read_service_factory()
        else:
            from ....chat.read_service import get_chat_read_service

            read_service = get_chat_read_service()
        if self._chat_store is not None and hasattr(read_service, "_chat_db_path"):
            current_path = Path(getattr(read_service, "_chat_db_path"))
            target_path = Path(self._chat_store.db_path)
            if current_path != target_path:
                close = getattr(read_service, "close", None)
                if callable(close):
                    close()
                setattr(read_service, "_chat_db_path", target_path)
        return read_service

    def restore_conversation_from_events(self) -> None:
        fact_rows: list[tuple[Any, ...]] = []
        try:
            if not self._l1_db_path.exists():
                return
            conn = connect_sqlite(self._l1_db_path, profile="hot_write", use_row_factory=False)
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT event_type, content, timestamp, user_id, session_id, turn_id
                FROM {FACT_EVENTS_TABLE}
                WHERE deleted_at IS NULL
                  AND event_type IN ('UserMessage', 'AIResponse')
                ORDER BY timestamp ASC
                LIMIT 5000
                """
            )
            fact_rows = cur.fetchall()
            conn.close()
        except Exception as exc:
            logger.warning("Failed to restore conversation from L1 store: %s", exc)
            return

        for event_type, raw_content, _, user_id, raw_session_id, _ in fact_rows:
            if not user_id:
                continue
            session_id = str(raw_session_id or "").strip()
            if not session_id:
                continue
            key = self.history_key(user_id, session_id)
            cached = self._conversation_history.setdefault(
                key,
                CachedConversationHistory(version=0, messages=[]),
            )
            history = cached.messages
            if event_type == "UserMessage":
                content = str(raw_content or "").strip()
                if content:
                    history.append({"role": "user", "content": str(content)})
            elif event_type == "AIResponse":
                content = str(raw_content or "").strip()
                if content:
                    history.append({"role": "assistant", "content": str(content)})

        self._restore_tool_interactions_from_trace()

    def _restore_tool_interactions_from_trace(self) -> None:
        try:
            if not self._runtime_trace_db_path.exists():
                return
            conn = connect_sqlite(self._runtime_trace_db_path, profile="hot_write", use_row_factory=False)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    trace_turns.user_id,
                    trace_turns.session_id,
                    trace_tools.turn_id,
                    trace_tools.tool_name,
                    trace_tools.error_code,
                    trace_tools.error_message,
                    trace_tools.result_preview,
                    trace_tools.arguments_json,
                    trace_tools.execution_time_ms,
                    trace_tools.success
                FROM trace_tools
                JOIN trace_turns ON trace_turns.trace_id = trace_tools.trace_id
                ORDER BY trace_turns.updated_at_ms ASC
                LIMIT 5000
                """
            )
            rows = cur.fetchall()
            conn.close()
        except Exception:
            logger.warning("Failed to restore tool interactions from runtime trace store")
            return

        for user_id, raw_session_id, turn_id, tool_name, error_code, error_message, result_preview, arguments_json, execution_time_ms, success in rows:
            if not user_id:
                continue
            session_id = self.require_session_id(str(user_id), raw_session_id)
            key = self.history_key(str(user_id), session_id)
            result_data = {}
            try:
                parsed = json.loads(str(arguments_json or ""))
                if isinstance(parsed, dict):
                    result_data = parsed
            except Exception:
                result_data = {}
            self.store_tool_interaction(
                key,
                {
                    "timestamp": execution_time_ms,
                    "intent": "unknown",
                    "tool_name": str(tool_name or "unknown"),
                    "status": "success" if bool(success) else "error",
                    "error_code": str(error_code or ""),
                    "error_message": str(error_message or ""),
                    "result_summary": str(result_preview or ""),
                    "result_data": result_data,
                    "turn_id": turn_id,
                },
            )
