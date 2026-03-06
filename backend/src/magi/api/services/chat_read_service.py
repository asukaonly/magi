"""
Read-side service for chat sessions and conversation history.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Optional

from ...agent.orchestration import get_orchestration_store
from ...core.logger import get_logger
from ...utils.runtime import get_runtime_paths

logger = get_logger(__name__)
WORKER_AGENT_EVENT_TYPES = ("WORKER_AGENT_PROGRESS", "WORKER_AGENT_COMPLETED", "WORKER_AGENT_FAILED")


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

    def get_worker_result(self, worker_id: str) -> Optional[dict[str, Any]]:
        if not worker_id.strip():
            return None
        store = get_orchestration_store()
        return store.get_worker_result_sync(worker_id)

    def list_sessions(self, user_id: str, limit: int = 30) -> list[dict[str, Any]]:
        """List recent chat sessions for a user."""
        safe_limit = max(1, min(limit, 200))
        sessions: dict[str, dict[str, Any]] = {}

        if self._events_db_path.exists():
            query = """
                SELECT type, data, timestamp
                FROM event_store
                WHERE type IN (
                    'USER_INPUT', 'AI_RESPONSE', 'UserMessage', 'AIResponse',
                    'WORKER_AGENT_PROGRESS', 'WORKER_AGENT_COMPLETED', 'WORKER_AGENT_FAILED'
                )
                  AND json_extract(data, '$.user_id') = ?
                ORDER BY timestamp DESC
            """
            try:
                conn = sqlite3.connect(str(self._events_db_path))
                cur = conn.cursor()
                cur.execute(query, (user_id,))
                rows = cur.fetchall()
                conn.close()
            except Exception as exc:
                logger.warning(f"Failed to query session list: {exc}")
                rows = []

            for event_type, raw_data, raw_ts in rows:
                try:
                    payload = json.loads(raw_data or "{}")
                except Exception:
                    continue
                session_id = str(payload.get("session_id") or "").strip()
                if not session_id:
                    continue
                timestamp = int(float(raw_ts or 0))
                if event_type in ("USER_INPUT", "UserMessage"):
                    content = str(payload.get("message") or "").strip()
                elif event_type in ("AI_RESPONSE", "AIResponse"):
                    content = str(payload.get("response") or "").strip()
                elif event_type in WORKER_AGENT_EVENT_TYPES:
                    content = self._format_worker_event_content(payload, event_type)
                else:
                    continue

                session = sessions.setdefault(
                    session_id,
                    {
                        "session_id": session_id,
                        "title_candidate": "",
                        "last_message_preview": "",
                        "last_timestamp": 0,
                        "message_count": 0,
                    },
                )
                session["message_count"] += 1
                if timestamp >= int(session["last_timestamp"]):
                    session["last_timestamp"] = timestamp
                    session["last_message_preview"] = content[:120]
                # Iterate desc by timestamp: repeatedly setting this keeps the oldest
                # user message as title seed after full traversal.
                if event_type in ("USER_INPUT", "UserMessage") and content:
                    session["title_candidate"] = content[:80]

        ordered = sorted(
            sessions.values(),
            key=lambda item: int(item.get("last_timestamp", 0)),
            reverse=True,
        )[:safe_limit]

        result = [
            {
                "session_id": str(item["session_id"]),
                "title": str(item.get("title_candidate") or item.get("last_message_preview") or "New Chat"),
                "last_message_preview": str(item.get("last_message_preview") or ""),
                "last_timestamp": int(item.get("last_timestamp") or 0),
                "message_count": int(item.get("message_count") or 0),
            }
            for item in ordered
        ]

        current_session_id = self._load_session_mapping().get(user_id)
        if current_session_id and all(item["session_id"] != current_session_id for item in result):
            result.insert(
                0,
                {
                    "session_id": current_session_id,
                    "title": "New Chat",
                    "last_message_preview": "",
                    "last_timestamp": 0,
                    "message_count": 0,
                },
            )
        return result[:safe_limit]

    def get_conversation_history(self, user_id: str, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        if not self._events_db_path.exists():
            return []
        safe_limit = max(1, min(limit, 1000))
        query = """
            SELECT type, data, timestamp
            FROM event_store
            WHERE type IN (
                'USER_INPUT', 'AI_RESPONSE', 'UserMessage', 'AIResponse',
                'WORKER_AGENT_PROGRESS', 'WORKER_AGENT_COMPLETED', 'WORKER_AGENT_FAILED'
            )
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
            elif event_type in WORKER_AGENT_EVENT_TYPES:
                content = self._format_worker_event_content(payload, event_type)
                role = "system"
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
            WHERE type IN (
                'USER_INPUT', 'AI_RESPONSE', 'UserMessage', 'AIResponse',
                'WORKER_AGENT_PROGRESS', 'WORKER_AGENT_COMPLETED', 'WORKER_AGENT_FAILED'
            )
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

    def _format_worker_event_content(self, payload: dict[str, Any], event_type: str) -> str:
        worker_id = str(payload.get("worker_id") or "worker")
        short_worker_id = worker_id[:10]
        stage = str(payload.get("stage") or "")
        subagent_type = str(payload.get("worker_subagent_type") or payload.get("subagent_type") or "worker")
        description = str(payload.get("worker_description") or payload.get("description") or "").strip()
        tool_name = str(payload.get("tool_name") or "").strip()
        success = payload.get("success")
        error = str(payload.get("error") or "").strip()

        if event_type == "WORKER_AGENT_COMPLETED":
            preview = str(payload.get("result_preview") or "").strip()
            suffix = f": {preview[:80]}" if preview else ""
            return f"[Worker:{short_worker_id}] Completed ({subagent_type}){suffix}"
        if event_type == "WORKER_AGENT_FAILED":
            suffix = f": {error}" if error else ""
            return f"[Worker:{short_worker_id}] Failed ({subagent_type}){suffix}"
        if stage == "started":
            suffix = f" - {description}" if description else ""
            return f"[Worker:{short_worker_id}] Started ({subagent_type}){suffix}"
        if stage == "tool_result":
            status = "ok" if bool(success) else "failed"
            tool_suffix = f" {tool_name}" if tool_name else ""
            error_suffix = f": {error}" if error and not bool(success) else ""
            return f"[Worker:{short_worker_id}] Tool{tool_suffix} {status}{error_suffix}"
        return f"[Worker:{short_worker_id}] Progress ({subagent_type})"


_chat_read_service: Optional[ChatReadService] = None


def get_chat_read_service() -> ChatReadService:
    """Get ChatReadService instance - checks DI container first, falls back to global."""
    global _chat_read_service
    # Try container first
    try:
        from ...core.container import get_container
        container = get_container()
        instance = container.chat_read_service()
        if instance is not None and type(instance).__name__ != "function":
            return instance
    except Exception:
        pass
    # Fallback to global
    if _chat_read_service is None:
        _chat_read_service = ChatReadService()
    return _chat_read_service
