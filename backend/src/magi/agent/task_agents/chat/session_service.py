"""Session and history state management for chat task agents."""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Optional

from ....core.logger import get_logger

logger = get_logger(__name__)

FACT_EVENTS_TABLE = "fact_events"
RUNTIME_OBSERVATIONS_TABLE = "runtime_observations"
TOOL_INTERACTION_EVENT_TYPE = "TOOL_INTERACTION"
TOOL_INVOKED_EVENT_TYPE = "TOOL_INVOKED"


class ChatSessionService:
    """Owns session mapping, history cache, and lazy history loading."""

    def __init__(
        self,
        *,
        session_state_file: Path,
        l1_db_path: Path,
        history_cache_max_sessions: int = 500,
        history_fetch_limit: int = 200,
    ) -> None:
        self._session_state_file = session_state_file
        self._l1_db_path = l1_db_path
        self._history_cache_max_sessions = history_cache_max_sessions
        self._history_fetch_limit = history_fetch_limit
        self._conversation_history: dict[str, list[dict[str, Any]]] = {}
        self._tool_interactions: dict[str, list[dict[str, Any]]] = {}
        self._current_session_by_user: dict[str, str] = {}
        self._history_cache_order: list[str] = []
        self._load_session_state()

    async def get_or_load_history(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        history_key = self.history_key(user_id, session_id)
        if history_key in self._conversation_history:
            return self._conversation_history[history_key]
        try:
            from ....api.services.chat_read_service import get_chat_read_service

            read_service = get_chat_read_service()
            history = read_service.get_conversation_history(
                user_id=user_id,
                session_id=session_id,
                limit=self._history_fetch_limit,
            )
            self._conversation_history[history_key] = list(history)
            self._update_lru_cache(history_key)
            return self._conversation_history[history_key]
        except Exception as exc:
            logger.warning(
                "Failed to lazy load history | user=%s session=%s error=%s",
                user_id,
                session_id,
                exc,
            )
            self._conversation_history.setdefault(history_key, [])
            return self._conversation_history[history_key]

    def resolve_session_id(self, user_id: str, session_id: Optional[str] = None) -> str:
        if session_id:
            self._current_session_by_user[user_id] = session_id
            self._save_session_state()
            return session_id
        existing = self._current_session_by_user.get(user_id)
        if existing:
            return existing
        new_id = str(uuid.uuid4())
        self._current_session_by_user[user_id] = new_id
        self._save_session_state()
        return new_id

    def history_key(self, user_id: str, session_id: str) -> str:
        return f"{user_id}::{session_id}"

    def get_history(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        return self._conversation_history.setdefault(self.history_key(user_id, session_id), [])

    def append_user_message(self, history_key: str, user_message: str) -> None:
        if not user_message:
            return
        history = self._conversation_history.setdefault(history_key, [])
        if history and history[-1].get("role") == "user" and history[-1].get("content") == user_message:
            return
        history.append({"role": "user", "content": user_message})
        self._update_lru_cache(history_key)

    def append_assistant_message(self, history_key: str, response_text: str) -> None:
        if not response_text:
            return
        history = self._conversation_history.setdefault(history_key, [])
        history.append({"role": "assistant", "content": response_text})
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

    def get_current_session_id(self, user_id: str) -> str:
        return self.resolve_session_id(user_id)

    def create_new_session(self, user_id: str) -> str:
        new_id = str(uuid.uuid4())
        self._current_session_by_user[user_id] = new_id
        key = self.history_key(user_id, new_id)
        self._conversation_history.setdefault(key, [])
        self._tool_interactions.setdefault(key, [])
        self._save_session_state()
        self._update_lru_cache(key)
        return new_id

    def get_conversation_history(self, user_id: str, session_id: Optional[str] = None) -> list[dict[str, Any]]:
        active_session = self.resolve_session_id(user_id, session_id)
        return self._conversation_history.get(self.history_key(user_id, active_session), [])

    def clear_conversation_history(self, user_id: str, session_id: Optional[str] = None) -> None:
        active_session = self.resolve_session_id(user_id, session_id)
        key = self.history_key(user_id, active_session)
        self._conversation_history[key] = []
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

    def _load_session_state(self) -> None:
        try:
            if self._session_state_file.exists():
                data = json.loads(self._session_state_file.read_text(encoding="utf-8"))
                mapping = data.get("current_session_by_user", {}) if isinstance(data, dict) else {}
                if isinstance(mapping, dict):
                    self._current_session_by_user = {
                        str(key): str(value)
                        for key, value in mapping.items()
                        if key and value
                    }
        except Exception as exc:
            logger.warning("Failed to load session state: %s", exc)

    def _save_session_state(self) -> None:
        try:
            payload = {"current_session_by_user": self._current_session_by_user}
            self._session_state_file.parent.mkdir(parents=True, exist_ok=True)
            self._session_state_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save session state: %s", exc)

    def restore_conversation_from_events(self) -> None:
        try:
            if not self._l1_db_path.exists():
                return
            conn = sqlite3.connect(str(self._l1_db_path))
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT event_type, structured_payload, timestamp
                FROM {FACT_EVENTS_TABLE}
                WHERE deleted_at IS NULL
                  AND event_type IN ('UserMessage', 'AIResponse')
                UNION ALL
                SELECT event_type, structured_payload, timestamp
                FROM {RUNTIME_OBSERVATIONS_TABLE}
                WHERE deleted_at IS NULL
                  AND event_type IN (?, ?)
                ORDER BY timestamp ASC
                LIMIT 5000
                """,
                (TOOL_INTERACTION_EVENT_TYPE, TOOL_INVOKED_EVENT_TYPE),
            )
            rows = cur.fetchall()
            conn.close()
        except Exception as exc:
            logger.warning("Failed to restore conversation from L1 store: %s", exc)
            return

        for event_type, raw_data, _ in rows:
            try:
                payload = json.loads(raw_data or "{}")
            except Exception:
                continue
            user_id = payload.get("user_id")
            if not user_id:
                continue
            session_id = self.resolve_session_id(user_id, payload.get("session_id"))
            key = self.history_key(user_id, session_id)
            history = self._conversation_history.setdefault(key, [])
            if event_type == "UserMessage":
                content = payload.get("message", "")
                if content:
                    history.append({"role": "user", "content": str(content)})
            elif event_type == "AIResponse":
                content = payload.get("response", "")
                if content:
                    history.append({"role": "assistant", "content": str(content)})
            elif event_type in {TOOL_INTERACTION_EVENT_TYPE, TOOL_INVOKED_EVENT_TYPE}:
                tool_name = str(payload.get("tool_name") or payload.get("action_type") or "").strip()
                if not tool_name:
                    continue
                error_text = str(payload.get("error") or "").strip()
                status = "error" if error_text or str(payload.get("result") or "").strip() == "failed" else "success"
                self.store_tool_interaction(
                    key,
                    {
                        "timestamp": payload.get("timestamp"),
                        "intent": payload.get("intent") or "unknown",
                        "tool_name": tool_name,
                        "status": status,
                        "error_code": str(payload.get("error_code") or ""),
                        "error_message": error_text,
                        "result_summary": str(payload.get("result") or payload.get("data") or ""),
                        "result_data": payload.get("data") if isinstance(payload.get("data"), dict) else {},
                        "turn_id": payload.get("turn_id"),
                    },
                )
