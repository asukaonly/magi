"""
Read-side service for chat sessions and conversation history.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ...core.logger import get_logger
from ...utils.runtime import get_runtime_paths

logger = get_logger(__name__)


class ChatReadService:
    """Query chat session and history from persistent storage."""

    def __init__(self) -> None:
        runtime_paths = get_runtime_paths()
        self._events_db_path: Path = runtime_paths.events_db_path
        self._session_state_file: Path = runtime_paths.data_dir / "chat_sessions.json"

    def get_current_session_id(self, user_id: str) -> str:
        mapping = self._load_session_mapping()
        existing = mapping.get(user_id)
        if existing:
            return existing
        new_session_id = str(uuid.uuid4())
        mapping[user_id] = new_session_id
        self._save_session_mapping(mapping)
        return new_session_id

    def create_new_session(self, user_id: str) -> str:
        mapping = self._load_session_mapping()
        new_session_id = str(uuid.uuid4())
        mapping[user_id] = new_session_id
        self._save_session_mapping(mapping)
        return new_session_id

    def get_conversation_history(self, user_id: str, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        if not self._events_db_path.exists():
            return []
        safe_limit = max(1, min(limit, 1000))
        query = """
            SELECT type, data, timestamp
            FROM event_store
            WHERE type IN ('USER_INPUT', 'AI_RESPONSE', 'UserMessage', 'AIResponse')
              AND json_extract(data, '$.user_id') = ?
              AND json_extract(data, '$.session_id') = ?
            ORDER BY timestamp ASC
            LIMIT ?
        """
        try:
            conn = sqlite3.connect(str(self._events_db_path))
            cur = conn.cursor()
            cur.execute(query, (user_id, session_id, safe_limit))
            rows = cur.fetchall()
            conn.close()
        except Exception as exc:
            logger.warning(f"Failed to query chat history: {exc}")
            return []

        messages: list[dict[str, Any]] = []
        for event_type, raw_data, ts in rows:
            try:
                payload = json.loads(raw_data or "{}")
            except Exception:
                continue
            if event_type in ("USER_INPUT", "UserMessage"):
                content = payload.get("message")
                role = "user"
            elif event_type in ("AI_RESPONSE", "AIResponse"):
                content = payload.get("response")
                role = "assistant"
            else:
                continue
            if not content:
                continue
            messages.append(
                {
                    "role": role,
                    "content": str(content),
                    "timestamp": int(float(ts or 0)),
                }
            )
        return messages

    def clear_conversation_history(self, user_id: str, session_id: str) -> None:
        if not self._events_db_path.exists():
            return
        delete_sql = """
            DELETE FROM event_store
            WHERE type IN ('USER_INPUT', 'AI_RESPONSE', 'UserMessage', 'AIResponse')
              AND json_extract(data, '$.user_id') = ?
              AND json_extract(data, '$.session_id') = ?
        """
        try:
            conn = sqlite3.connect(str(self._events_db_path))
            cur = conn.cursor()
            cur.execute(delete_sql, (user_id, session_id))
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning(f"Failed to clear chat history: {exc}")

    def clear_all_sessions(self) -> int:
        """Clear all current session mappings and return removed count."""
        mapping = self._load_session_mapping()
        removed = len(mapping)
        self._save_session_mapping({})
        return removed

    def _load_session_mapping(self) -> dict[str, str]:
        if not self._session_state_file.exists():
            return {}
        try:
            data = json.loads(self._session_state_file.read_text(encoding="utf-8"))
            mapping = data.get("current_session_by_user", {}) if isinstance(data, dict) else {}
            if not isinstance(mapping, dict):
                return {}
            return {str(k): str(v) for k, v in mapping.items() if k and v}
        except Exception as exc:
            logger.warning(f"Failed to load session mapping: {exc}")
            return {}

    def _save_session_mapping(self, mapping: dict[str, str]) -> None:
        try:
            payload = {"current_session_by_user": mapping}
            self._session_state_file.parent.mkdir(parents=True, exist_ok=True)
            self._session_state_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning(f"Failed to save session mapping: {exc}")


_chat_read_service: ChatReadService | None = None


def get_chat_read_service() -> ChatReadService:
    global _chat_read_service
    if _chat_read_service is None:
        _chat_read_service = ChatReadService()
    return _chat_read_service
