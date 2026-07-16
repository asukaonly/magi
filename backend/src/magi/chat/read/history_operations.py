"""Conversation history and attachment read operations for chat storage."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol, cast

from ...core.logger import get_logger
from .models import ChatDisplayMessage
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


@dataclass(slots=True)
class _DisplayHistoryRows:
    turn_rows: list[sqlite3.Row]
    message_rows: list[sqlite3.Row]


@dataclass(slots=True)
class _DisplayHistoryProjection:
    messages_by_turn: dict[str, list[ChatDisplayMessage]]
    legacy_messages: list[ChatDisplayMessage]
    display_rows: list[sqlite3.Row]
    display_messages: list[ChatDisplayMessage]


@dataclass(slots=True)
class _TurnDisplayMetadata:
    ux_preferences: dict[str, dict[str, Any]]
    run_state_by_turn: dict[str, dict[str, object] | None]


def _collapse_rhythm_segments_for_prompt(
    messages: list[ChatDisplayMessage],
) -> list[ChatDisplayMessage]:
    collapsed_messages: list[ChatDisplayMessage] = []
    rhythm_index_by_turn: dict[str, int] = {}
    for message in messages:
        if message.message_kind != "assistant_rhythm_segment":
            collapsed_messages.append(message)
            continue
        turn_id = str(message.turn_id or "").strip()
        if not turn_id:
            collapsed_messages.append(message)
            continue
        existing_index = rhythm_index_by_turn.get(turn_id)
        if existing_index is not None:
            existing = collapsed_messages[existing_index]
            parts = [part for part in (existing.content.strip(), message.content.strip()) if part]
            existing.content = "\n\n".join(parts)
            if message.attachments:
                existing.attachments = message.attachments
            continue
        rhythm_index_by_turn[turn_id] = len(collapsed_messages)
        collapsed_messages.append(
            replace(
                message,
                message_kind="assistant_final",
                payload=None,
            )
        )
    return collapsed_messages


def _build_turn_run_state(turn: sqlite3.Row) -> dict[str, object] | None:
    status = str(turn["status"] or "").strip()
    run_id = str(turn["run_id"] or "").strip()
    if not status and not run_id:
        return None
    return {
        "state": status or "unknown",
        "run_id": run_id or None,
        "run_revision": int(turn["run_revision"] or 0),
        "run_disposition": turn["run_disposition"],
        "can_cancel": bool(run_id) and status in {"running", "cancelling"},
        "can_detach": bool(run_id) and status == "running",
        "error_text": turn["error_text"],
        "completed_at_ms": turn["completed_at_ms"],
    }


def _get_chat_trace_read_service() -> Any:
    from .. import read_service as chat_read_service_module

    return chat_read_service_module.get_chat_trace_read_service()


class _ChatHistoryOperationsHost(Protocol):
    _chat_db_path: Path
    _runtime_paths: Any

    def _get_conn(self) -> sqlite3.Connection: ...

    def _query_chat_message_rows(
        self,
        *,
        user_id: str,
        session_id: str,
        message_kinds: tuple[str, ...] | None,
        visible_only: bool,
        exclude_replaced: bool,
        start_message_id: str | None = None,
    ) -> list[sqlite3.Row]: ...

    def _query_turn_rows(self, *, user_id: str, session_id: str) -> list[sqlite3.Row]: ...

    def _row_to_display_message(self, row: sqlite3.Row) -> ChatDisplayMessage | None: ...

    def _attach_reply_previews(
        self,
        *,
        rows: list[sqlite3.Row],
        messages: list[ChatDisplayMessage],
    ) -> None: ...

    def _parse_turn_ux_preferences(self, raw_ux_plan_json: str | None) -> dict[str, Any]: ...

    def _apply_turn_ux_preferences(
        self,
        message: ChatDisplayMessage,
        preferences: dict[str, Any] | None,
    ) -> None: ...

    def _parse_message_payload_json(self, raw_payload_json: str | None) -> dict[str, Any]: ...

    def _delete_runtime_trace_rows(self, *, user_id: str, session_id: str) -> None: ...

    def _delete_chat_session_assets(self, *, session_id: str) -> None: ...


def _query_display_history_rows(
    *,
    host: _ChatHistoryOperationsHost,
    user_id: str,
    session_id: str,
) -> _DisplayHistoryRows:
    turn_rows = host._query_turn_rows(user_id=user_id, session_id=session_id)
    message_rows = host._query_chat_message_rows(
        user_id=user_id,
        session_id=session_id,
        message_kinds=None,
        visible_only=True,
        exclude_replaced=True,
    )
    replaced_interim_rows = [
        row
        for row in host._query_chat_message_rows(
            user_id=user_id,
            session_id=session_id,
            message_kinds=("assistant_interim",),
            visible_only=True,
            exclude_replaced=False,
        )
        if row["replaced_by_message_id"] is not None
    ]
    return _DisplayHistoryRows(
        turn_rows=turn_rows,
        message_rows=_merge_replaced_interim_rows(message_rows, replaced_interim_rows),
    )


def _merge_replaced_interim_rows(
    message_rows: list[sqlite3.Row],
    replaced_interim_rows: list[sqlite3.Row],
) -> list[sqlite3.Row]:
    if not replaced_interim_rows:
        return message_rows
    return sorted(
        [*message_rows, *replaced_interim_rows],
        key=lambda row: (
            int(row["created_at_ms"] or 0),
            int(row["sequence_no"] or 0),
        ),
    )


def _build_turn_display_metadata(
    host: _ChatHistoryOperationsHost,
    turn_rows: list[sqlite3.Row],
) -> _TurnDisplayMetadata:
    return _TurnDisplayMetadata(
        ux_preferences={
            str(row["turn_id"]): host._parse_turn_ux_preferences(row["ux_plan_json"])
            for row in turn_rows
        },
        run_state_by_turn={str(row["turn_id"]): _build_turn_run_state(row) for row in turn_rows},
    )


def _project_display_history(
    *,
    host: _ChatHistoryOperationsHost,
    trace_service: Any,
    trace_activity: dict[str, Any],
    rows: _DisplayHistoryRows,
    metadata: _TurnDisplayMetadata,
    user_id: str,
    session_id: str,
) -> _DisplayHistoryProjection:
    projection = _DisplayHistoryProjection({}, [], [], [])
    for row in rows.message_rows:
        display_message = host._row_to_display_message(row)
        if display_message is None:
            continue
        projection.display_rows.append(row)
        projection.display_messages.append(display_message)
        turn_id = str(row["turn_id"] or "").strip()
        if not turn_id:
            projection.legacy_messages.append(display_message)
            continue
        _decorate_turn_message(
            host=host,
            trace_service=trace_service,
            trace_activity=trace_activity,
            metadata=metadata,
            message=display_message,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )
        projection.messages_by_turn.setdefault(turn_id, []).append(display_message)
    return projection


def _decorate_turn_message(
    *,
    host: _ChatHistoryOperationsHost,
    trace_service: Any,
    trace_activity: dict[str, Any],
    metadata: _TurnDisplayMetadata,
    message: ChatDisplayMessage,
    user_id: str,
    session_id: str,
    turn_id: str,
) -> None:
    host._apply_turn_ux_preferences(message, metadata.ux_preferences.get(turn_id))
    message.run_state = metadata.run_state_by_turn.get(turn_id)
    if message.kind != "assistant":
        return
    summary = trace_service.get_trace_summary(
        user_id=user_id, session_id=session_id, turn_id=turn_id
    )
    message.trace_summary = summary or trace_activity.get(turn_id)
    message.trace_available = bool(
        (summary or trace_activity.get(turn_id) or {}).get("trace_available")
    )


def _assemble_display_messages(
    *,
    turn_rows: list[sqlite3.Row],
    projection: _DisplayHistoryProjection,
    trace_service: Any,
    trace_activity: dict[str, Any],
    metadata: _TurnDisplayMetadata,
    user_id: str,
    session_id: str,
) -> list[ChatDisplayMessage]:
    messages: list[ChatDisplayMessage] = []
    for turn in turn_rows:
        turn_id = str(turn["turn_id"])
        turn_messages = projection.messages_by_turn.get(turn_id, [])
        messages.extend(turn_messages)
        if any(item.kind == "assistant" for item in turn_messages):
            continue
        status_message = _build_trace_status_message(
            turn=turn,
            turn_messages=turn_messages,
            trace_service=trace_service,
            trace_activity=trace_activity,
            metadata=metadata,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )
        if status_message is not None:
            messages.append(status_message)
    messages.extend(projection.legacy_messages)
    return messages


def _build_trace_status_message(
    *,
    turn: sqlite3.Row,
    turn_messages: list[ChatDisplayMessage],
    trace_service: Any,
    trace_activity: dict[str, Any],
    metadata: _TurnDisplayMetadata,
    user_id: str,
    session_id: str,
    turn_id: str,
) -> ChatDisplayMessage | None:
    summary = trace_activity.get(turn_id) or trace_service.get_trace_summary(
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
    )
    if summary is None:
        return None
    preferences = metadata.ux_preferences.get(turn_id, {})
    return ChatDisplayMessage(
        role="assistant",
        kind="status",
        content=str((summary or {}).get("headline") or "Thinking"),
        timestamp=_trace_status_timestamp(turn, turn_messages),
        turn_id=turn_id,
        trace_display_mode=preferences.get("trace_display_mode"),
        allow_trace_collapse=bool(preferences.get("allow_trace_collapse", False)),
        trace_summary=summary,
        trace_available=bool(summary and summary.get("trace_available")),
        run_state=metadata.run_state_by_turn.get(turn_id),
    )


def _trace_status_timestamp(
    turn: sqlite3.Row,
    turn_messages: list[ChatDisplayMessage],
) -> int:
    user_message = next((item for item in turn_messages if item.kind == "user"), None)
    if user_message is not None:
        return user_message.timestamp
    return int(turn["updated_at_ms"] or turn["created_at_ms"] or 0)


class ChatHistoryOperationsMixin:
    """Read display history, single messages, attachments, and clear history."""

    def get_conversation_history(
        self,
        user_id: str,
        session_id: str,
        limit: int | None = 200,
        *,
        start_message_id: str | None = None,
    ) -> list[ChatDisplayMessage]:
        host = cast(_ChatHistoryOperationsHost, self)
        if not host._chat_db_path.exists():
            return []
        safe_limit = None if limit is None else max(1, min(limit, 1000))
        try:
            rows = host._query_chat_message_rows(
                user_id=user_id,
                session_id=session_id,
                message_kinds=(
                    "user_text",
                    "assistant_final",
                    "assistant_rhythm_segment",
                ),
                visible_only=True,
                exclude_replaced=True,
                start_message_id=start_message_id,
            )
        except Exception as exc:
            logger.exception(f"Failed to query chat history: {exc}")
            raise

        selected_rows = rows if safe_limit is None else rows[-safe_limit:]
        selected_message_rows: list[sqlite3.Row] = []
        messages: list[ChatDisplayMessage] = []
        for row in selected_rows:
            display_message = host._row_to_display_message(row)
            if display_message is None or display_message.kind == "status":
                continue
            if display_message.kind == "assistant" and row["message_kind"] not in {
                "assistant_final",
                "assistant_rhythm_segment",
            }:
                continue
            selected_message_rows.append(row)
            messages.append(display_message)
        host._attach_reply_previews(rows=selected_message_rows, messages=messages)
        return _collapse_rhythm_segments_for_prompt(messages)

    def get_session_attachment_references(
        self,
        user_id: str,
        session_id: str,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        """Return recent durable attachment references without loading transcript bodies."""

        host = cast(_ChatHistoryOperationsHost, self)
        if not host._chat_db_path.exists():
            return []
        safe_limit = max(1, min(limit, 200))
        rows = (
            host._get_conn()
            .execute(
                f"""
                SELECT turn_id, payload_json
                FROM {CHAT_MESSAGES_TABLE}
                WHERE user_id = ?
                  AND session_id = ?
                  AND is_visible = 1
                  AND replaced_by_message_id IS NULL
                  AND json_type(payload_json, '$.attachments') = 'array'
                  AND json_array_length(payload_json, '$.attachments') > 0
                ORDER BY created_at_ms DESC, sequence_no DESC, message_id DESC
                LIMIT ?
                """,
                (user_id, session_id, safe_limit),
            )
            .fetchall()
        )
        references: list[dict[str, Any]] = []
        for row in rows:
            payload = host._parse_message_payload_json(row["payload_json"])
            attachments = payload.get("attachments")
            if not isinstance(attachments, list):
                continue
            turn_id = str(row["turn_id"] or "").strip()
            for attachment in reversed(attachments):
                if not isinstance(attachment, dict):
                    continue
                reference = dict(attachment)
                if turn_id:
                    reference["turn_id"] = turn_id
                references.append(reference)
                if len(references) >= safe_limit:
                    return list(reversed(references))
        return list(reversed(references))

    def get_display_history(
        self,
        user_id: str,
        session_id: str,
        limit: int = 200,
    ) -> list[ChatDisplayMessage]:
        host = cast(_ChatHistoryOperationsHost, self)
        if not host._chat_db_path.exists():
            return []
        safe_limit = max(1, min(limit, 1000))
        try:
            rows = _query_display_history_rows(
                host=host,
                user_id=user_id,
                session_id=session_id,
            )
        except Exception as exc:
            logger.exception(f"Failed to query display history: {exc}")
            return []

        trace_service = _get_chat_trace_read_service()
        trace_activity = trace_service.get_turn_activity_map(user_id=user_id, session_id=session_id)
        metadata = _build_turn_display_metadata(host, rows.turn_rows)
        projection = _project_display_history(
            host=host,
            trace_service=trace_service,
            trace_activity=trace_activity,
            rows=rows,
            metadata=metadata,
            user_id=user_id,
            session_id=session_id,
        )
        messages = _assemble_display_messages(
            turn_rows=rows.turn_rows,
            projection=projection,
            trace_service=trace_service,
            trace_activity=trace_activity,
            metadata=metadata,
            user_id=user_id,
            session_id=session_id,
        )
        host._attach_reply_previews(
            rows=projection.display_rows,
            messages=projection.display_messages,
        )
        messages.sort(key=lambda item: item.timestamp)
        return messages[-safe_limit:]

    def get_display_message(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> ChatDisplayMessage | None:
        _ = user_id
        host = cast(_ChatHistoryOperationsHost, self)
        if not host._chat_db_path.exists():
            return None
        normalized_session_id = str(session_id or "").strip()
        normalized_message_id = str(message_id or "").strip()
        if not normalized_session_id or not normalized_message_id:
            return None
        try:
            row = (
                host._get_conn()
                .execute(
                    f"""
                SELECT message_id, session_id, turn_id, user_id, role, message_kind,
                       content_text, payload_json, is_final, is_visible, created_at_ms,
                      sequence_no, replaces_message_id, replaced_by_message_id, persona_id,
                      reply_to_message_id, label_json
                FROM {CHAT_MESSAGES_TABLE}
                WHERE session_id = ?
                  AND message_id = ?
                  AND is_visible = 1
                LIMIT 1
                """,
                    (normalized_session_id, normalized_message_id),
                )
                .fetchone()
            )
        except Exception as exc:
            logger.exception(f"Failed to query display message: {exc}")
            return None
        if row is None:
            return None
        display_message = host._row_to_display_message(row)
        if display_message is None:
            return None
        host._attach_reply_previews(rows=[row], messages=[display_message])
        return display_message

    def get_attachment_payload(
        self,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        """Find one attachment payload by attachment id within a session."""
        host = cast(_ChatHistoryOperationsHost, self)
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        normalized_attachment_id = str(attachment_id).strip()
        if not normalized_user_id or not normalized_session_id or not normalized_attachment_id:
            raise ValueError("User ID, session ID, and attachment ID are required")
        if not host._chat_db_path.exists():
            return None

        row = (
            host._get_conn()
            .execute(
                f"""
                 SELECT a.attachment_id, a.turn_id, a.kind, a.original_name, a.mime_type,
                   a.size_bytes, a.storage_rel_path, a.sha256
            FROM {CHAT_ATTACHMENTS_TABLE} a
            JOIN {CHAT_MESSAGES_TABLE} m ON m.message_id = a.message_id
            WHERE a.user_id = ?
              AND a.session_id = ?
              AND a.attachment_id = ?
              AND m.is_visible = 1
            LIMIT 1
            """,
                (normalized_user_id, normalized_session_id, normalized_attachment_id),
            )
            .fetchone()
        )
        if row is None:
            return None
        storage_rel_path = str(row["storage_rel_path"] or "").strip()
        if not storage_rel_path:
            return None
        storage_path = host._runtime_paths.base_dir / Path(storage_rel_path)
        return {
            "attachment_id": str(row["attachment_id"] or "").strip(),
            "turn_id": str(row["turn_id"] or "").strip(),
            "kind": str(row["kind"] or "file").strip() or "file",
            "original_name": str(row["original_name"] or "").strip(),
            "mime_type": str(row["mime_type"] or "application/octet-stream").strip()
            or "application/octet-stream",
            "size_bytes": int(row["size_bytes"] or 0),
            "storage_rel_path": storage_rel_path,
            "storage_path": str(storage_path),
            "sha256": str(row["sha256"] or "").strip() or None,
        }

    def clear_conversation_history(self, user_id: str, session_id: str) -> None:
        host = cast(_ChatHistoryOperationsHost, self)
        if not host._chat_db_path.exists():
            return
        try:
            conn = host._get_conn()
            conn.execute(
                f"DELETE FROM {CHAT_MESSAGES_TABLE} WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
            conn.execute(
                f"DELETE FROM {CHAT_ATTACHMENTS_TABLE} WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
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
                (user_id, session_id),
            )
            conn.execute(
                f"DELETE FROM {CHAT_TURNS_TABLE} WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
            conn.execute(
                f"DELETE FROM {CHAT_CONTEXT_SUMMARIES_TABLE} WHERE session_id = ?",
                (session_id,),
            )
            conn.execute(
                f"DELETE FROM {CHAT_RUN_CONSUMED_EVENTS_TABLE} WHERE session_id = ?",
                (session_id,),
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
        host._delete_runtime_trace_rows(user_id=user_id, session_id=session_id)
        host._delete_chat_session_assets(session_id=session_id)


__all__ = ["ChatHistoryOperationsMixin"]
