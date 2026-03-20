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
from .chat_trace_read_service import AI_RESPONSE_EVENT_TYPES, USER_EVENT_TYPES, get_chat_trace_read_service

logger = get_logger(__name__)

FACT_EVENTS_TABLE = "fact_events"
RUNTIME_OBSERVATIONS_TABLE = "runtime_observations"
RUNTIME_TRACE_EVENT_TYPES = (
    "WORKER_AGENT_PROGRESS",
    "WORKER_AGENT_COMPLETED",
    "WORKER_AGENT_FAILED",
    "CHAT_TOOL_LOOP_STEP",
    "TOOL_INTERACTION",
    "TOOL_INVOKED",
)


class ChatReadService:
    """Query chat session and history from persistent storage."""

    def __init__(self) -> None:
        runtime_paths = get_runtime_paths()
        self._l1_db_path: Path = runtime_paths.l1_memory_db_path
        self._session_state_file: Path = runtime_paths.data_dir / "chat_sessions.json"
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        """Return a reusable SQLite connection, creating one lazily."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._l1_db_path))
        return self._conn

    def close(self) -> None:
        """Close the cached SQLite connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def get_current_session_id(self, user_id: str) -> str:
        mapping = self._load_session_mapping()
        existing = mapping.get(user_id)
        if existing:
            return existing
        new_session_id = str(uuid.uuid4())
        mapping[user_id] = new_session_id
        self._save_session_state(mapping=mapping, metadata=self._load_session_metadata())
        return new_session_id

    def create_new_session(self, user_id: str) -> str:
        mapping = self._load_session_mapping()
        new_session_id = str(uuid.uuid4())
        mapping[user_id] = new_session_id
        self._save_session_state(mapping=mapping, metadata=self._load_session_metadata())
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
        metadata_by_user = self._load_session_metadata().get(user_id, {})

        if self._l1_db_path.exists():
            try:
                rows = self._query_fact_rows(
                    event_types=USER_EVENT_TYPES + AI_RESPONSE_EVENT_TYPES,
                    user_id=user_id,
                    session_id=None,
                    limit=None,
                    ascending=False,
                )
            except Exception as exc:
                logger.exception(f"Failed to query session list: {exc}")
                rows = []

            for event_type, content, raw_ts, raw_session_id, turn_id in rows:
                del turn_id
                session_id = str(raw_session_id or "").strip()
                if not session_id:
                    continue
                timestamp = int(float(raw_ts or 0))
                text = str(content or "").strip()
                if event_type not in (*USER_EVENT_TYPES, *AI_RESPONSE_EVENT_TYPES):
                    continue
                if not text:
                    continue
                session = sessions.setdefault(
                    session_id,
                    {
                        "session_id": session_id,
                        "title_candidate": "",
                        "last_message_preview": "",
                        "last_user_message_preview": "",
                        "last_timestamp": 0,
                        "last_user_timestamp": 0,
                        "message_count": 0,
                    },
                )
                session["message_count"] += 1
                if timestamp >= int(session["last_timestamp"]):
                    session["last_timestamp"] = timestamp
                    session["last_message_preview"] = text[:120]
                if event_type in USER_EVENT_TYPES:
                    if timestamp >= int(session["last_user_timestamp"]):
                        session["last_user_timestamp"] = timestamp
                        session["last_user_message_preview"] = text[:120]
                    session["title_candidate"] = text[:80]

        ordered = sorted(
            sessions.values(),
            key=lambda item: int(item.get("last_timestamp", 0)),
            reverse=True,
        )[:safe_limit]

        result = [
            {
                "session_id": str(item["session_id"]),
                "title": str(
                    metadata_by_user.get(str(item["session_id"]), {}).get("title")
                    or item.get("title_candidate")
                    or item.get("last_user_message_preview")
                    or item.get("last_message_preview")
                    or "New Chat"
                ),
                "last_message_preview": str(item.get("last_message_preview") or ""),
                "last_user_message_preview": str(item.get("last_user_message_preview") or ""),
                "title_overridden": bool(
                    metadata_by_user.get(str(item["session_id"]), {}).get("title")
                ),
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
                    "title": str(
                        metadata_by_user.get(current_session_id, {}).get("title")
                        or "New Chat"
                    ),
                    "last_message_preview": "",
                    "last_user_message_preview": "",
                    "title_overridden": bool(
                        metadata_by_user.get(current_session_id, {}).get("title")
                    ),
                    "last_timestamp": 0,
                    "message_count": 0,
                },
            )
        return result[:safe_limit]

    def rename_session(self, user_id: str, session_id: str, title: str) -> dict[str, Any]:
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        normalized_title = str(title).strip()
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")
        if not normalized_title:
            raise ValueError("Session title cannot be empty")

        mapping = self._load_session_mapping()
        metadata = self._load_session_metadata()
        user_metadata = dict(metadata.get(normalized_user_id, {}))
        session_metadata = dict(user_metadata.get(normalized_session_id, {}))
        session_metadata["title"] = normalized_title
        user_metadata[normalized_session_id] = session_metadata
        metadata[normalized_user_id] = user_metadata
        self._save_session_state(mapping=mapping, metadata=metadata)
        return {
            "session_id": normalized_session_id,
            "title": normalized_title,
        }

    def delete_session(self, user_id: str, session_id: str) -> str:
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
                cur.execute(
                    f"""
                    DELETE FROM {RUNTIME_OBSERVATIONS_TABLE}
                    WHERE user_id = ?
                      AND session_id = ?
                    """,
                    (normalized_user_id, normalized_session_id),
                )
                conn.commit()
            except Exception as exc:
                logger.exception(f"Failed to delete session: {exc}")

        mapping = self._load_session_mapping()
        metadata = self._load_session_metadata()
        user_metadata = dict(metadata.get(normalized_user_id, {}))
        user_metadata.pop(normalized_session_id, None)
        if user_metadata:
            metadata[normalized_user_id] = user_metadata
        else:
            metadata.pop(normalized_user_id, None)

        current_session_id = mapping.get(normalized_user_id)
        if current_session_id == normalized_session_id:
            mapping.pop(normalized_user_id, None)
            self._save_session_state(mapping=mapping, metadata=metadata)
            remaining = self.list_sessions(normalized_user_id, limit=1)
            if remaining:
                mapping[normalized_user_id] = str(remaining[0]["session_id"])
            else:
                mapping[normalized_user_id] = str(uuid.uuid4())

        self._save_session_state(mapping=mapping, metadata=metadata)
        return mapping.get(normalized_user_id) or self.get_current_session_id(normalized_user_id)

    def get_conversation_history(self, user_id: str, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
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

        messages: list[dict[str, Any]] = []
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
                {
                    "role": role,
                    "content": str(content),
                    "timestamp": int(float(ts or 0)),
                    "turn_id": str(turn_id or "").strip() or None,
                    "kind": role,
                }
            )
        return messages

    def get_display_history(self, user_id: str, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
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
            runtime_rows = self._query_runtime_rows(
                event_types=RUNTIME_TRACE_EVENT_TYPES,
                user_id=user_id,
                session_id=session_id,
                limit=None,
                ascending=True,
            )
            rows = sorted([*fact_rows, *runtime_rows], key=lambda item: float(item[2] or 0))
        except Exception as exc:
            logger.exception(f"Failed to query display history: {exc}")
            return []

        trace_service = get_chat_trace_read_service()
        by_turn: dict[str, dict[str, Any]] = {}
        ordered_turns: list[str] = []
        legacy_messages: list[dict[str, Any]] = []

        for event_type, raw_content, ts, _, turn_id in rows:
            turn_id = str(turn_id or "").strip()
            timestamp = int(float(ts or 0))
            if event_type in USER_EVENT_TYPES:
                message = str(raw_content or "").strip()
                if not message:
                    continue
                if not turn_id:
                    legacy_messages.append(
                        {"role": "user", "kind": "user", "content": message, "timestamp": timestamp}
                    )
                    continue
                turn = by_turn.setdefault(turn_id, {"user": None, "assistant": None, "has_trace": False, "last_trace_timestamp": timestamp})
                if turn_id not in ordered_turns:
                    ordered_turns.append(turn_id)
                turn["user"] = {
                    "role": "user",
                    "kind": "user",
                    "content": message,
                    "timestamp": timestamp,
                    "turn_id": turn_id,
                }
                continue
            if event_type in AI_RESPONSE_EVENT_TYPES:
                response = str(raw_content or "").strip()
                if not response:
                    continue
                if not turn_id:
                    legacy_messages.append(
                        {"role": "assistant", "kind": "assistant", "content": response, "timestamp": timestamp}
                    )
                    continue
                turn = by_turn.setdefault(turn_id, {"user": None, "assistant": None, "has_trace": False, "last_trace_timestamp": timestamp})
                summary = trace_service.get_trace_summary(user_id=user_id, session_id=session_id, turn_id=turn_id)
                turn["assistant"] = {
                    "role": "assistant",
                    "kind": "assistant",
                    "content": response,
                    "timestamp": timestamp,
                    "turn_id": turn_id,
                    "trace_summary": summary,
                    "trace_available": bool(summary and summary.get("trace_available")),
                }
                continue
            if turn_id:
                turn = by_turn.setdefault(turn_id, {"user": None, "assistant": None, "has_trace": False, "last_trace_timestamp": timestamp})
                turn["has_trace"] = True
                turn["last_trace_timestamp"] = max(int(turn.get("last_trace_timestamp") or 0), timestamp)
                if turn_id not in ordered_turns and turn.get("user") is not None:
                    ordered_turns.append(turn_id)

        messages: list[dict[str, Any]] = []
        for turn_id in ordered_turns:
            turn = by_turn.get(turn_id, {})
            user_message = turn.get("user")
            if isinstance(user_message, dict):
                messages.append(user_message)
            assistant_message = turn.get("assistant")
            if isinstance(assistant_message, dict):
                messages.append(assistant_message)
                continue
            if turn.get("has_trace"):
                summary = trace_service.get_trace_summary(user_id=user_id, session_id=session_id, turn_id=turn_id)
                messages.append(
                    {
                        "role": "assistant",
                        "kind": "status",
                        "content": str((summary or {}).get("headline") or "Thinking"),
                        "timestamp": int(turn.get("last_trace_timestamp") or 0),
                        "turn_id": turn_id,
                        "trace_summary": summary,
                        "trace_available": bool(summary and summary.get("trace_available")),
                    }
                )
        messages.extend(legacy_messages)
        messages.sort(key=lambda item: int(item.get("timestamp", 0)))
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
            cur.execute(
                f"""
                DELETE FROM {RUNTIME_OBSERVATIONS_TABLE}
                WHERE deleted_at IS NULL
                  AND event_type IN ({", ".join("?" for _ in RUNTIME_TRACE_EVENT_TYPES)})
                  AND user_id = ?
                  AND session_id = ?
                """,
                [*RUNTIME_TRACE_EVENT_TYPES, user_id, session_id],
            )
            conn.commit()
        except Exception as exc:
            logger.exception(f"Failed to clear chat history: {exc}")

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

    def _query_runtime_rows(
        self,
        *,
        event_types: tuple[str, ...],
        user_id: str,
        session_id: str | None,
        limit: int | None,
        ascending: bool,
    ) -> list[tuple[str, str, float, str | None, str | None]]:
        return self._query_rows(
            table=RUNTIME_OBSERVATIONS_TABLE,
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

    def clear_all_sessions(self) -> int:
        """Clear all current session mappings and return removed count."""
        mapping = self._load_session_mapping()
        removed = len(mapping)
        self._save_session_state(mapping={}, metadata={})
        return removed

    def _load_session_mapping(self) -> dict[str, str]:
        data = self._load_session_state()
        mapping = data.get("current_session_by_user", {}) if isinstance(data, dict) else {}
        if not isinstance(mapping, dict):
            return {}
        return {str(k): str(v) for k, v in mapping.items() if k and v}

    def _save_session_mapping(self, mapping: dict[str, str]) -> None:
        self._save_session_state(mapping=mapping, metadata=self._load_session_metadata())

    def _load_session_metadata(self) -> dict[str, dict[str, dict[str, Any]]]:
        data = self._load_session_state()
        raw_metadata = data.get("session_meta_by_user", {}) if isinstance(data, dict) else {}
        if not isinstance(raw_metadata, dict):
            return {}
        normalized: dict[str, dict[str, dict[str, Any]]] = {}
        for user_id, session_map in raw_metadata.items():
            if not user_id or not isinstance(session_map, dict):
                continue
            next_session_map: dict[str, dict[str, Any]] = {}
            for session_id, session_meta in session_map.items():
                if not session_id or not isinstance(session_meta, dict):
                    continue
                next_session_map[str(session_id)] = dict(session_meta)
            if next_session_map:
                normalized[str(user_id)] = next_session_map
        return normalized

    def _load_session_state(self) -> dict[str, Any]:
        if not self._session_state_file.exists():
            return {}
        try:
            data = json.loads(self._session_state_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning(f"Failed to load session mapping: {exc}")
            return {}

    def _save_session_state(
        self,
        *,
        mapping: dict[str, str],
        metadata: dict[str, dict[str, dict[str, Any]]],
    ) -> None:
        try:
            from ...utils.file_io import atomic_write_text
            payload = {
                "current_session_by_user": mapping,
                "session_meta_by_user": metadata,
            }
            atomic_write_text(
                self._session_state_file,
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
        except Exception as exc:
            logger.warning(f"Failed to save session mapping: {exc}")

_chat_read_service: Optional[ChatReadService] = None


def get_chat_read_service() -> ChatReadService:
    """Get the shared ChatReadService instance."""
    global _chat_read_service
    if _chat_read_service is None:
        _chat_read_service = ChatReadService()
    return _chat_read_service
