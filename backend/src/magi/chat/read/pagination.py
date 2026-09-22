"""Snapshot-consistent keyset pages for chat read surfaces."""

from __future__ import annotations

import base64
import binascii
import json
import sqlite3
from typing import Any


class InvalidPageCursor(ValueError):
    """The supplied page boundary does not belong to this read scope."""


class StalePageCursor(ValueError):
    """The snapshot changed after the preceding page was read."""


def read_revision(conn: sqlite3.Connection, user_id: str, scope: str) -> str:
    row = conn.execute(
        "SELECT epoch, revision FROM chat_read_revisions WHERE user_id = ? AND scope = ?",
        (user_id, scope),
    ).fetchone()
    return f"{row['epoch']}:{row['revision']}" if row is not None else "empty:0"


def encode_page_cursor(scope: list[str], revision: str, key: list[int | str]) -> str:
    raw = json.dumps([1, scope, revision, key], ensure_ascii=False, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_page_cursor(
    cursor: str | None, *, scope: list[str], revision: str
) -> tuple[int, int, str] | None:
    if cursor is None:
        return None
    try:
        if not cursor or len(cursor) > 4096:
            raise ValueError("Invalid cursor size")
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        value = json.loads(raw)
        if (
            not isinstance(value, list)
            or len(value) != 4
            or type(value[0]) is not int
            or value[0] != 1
            or value[1] != scope
        ):
            raise ValueError("Invalid cursor scope")
        key = value[3]
        if (
            not isinstance(value[2], str)
            or not isinstance(key, list)
            or len(key) != 3
            or type(key[0]) is not int
            or type(key[1]) is not int
            or not isinstance(key[2], str)
            or not key[2]
            or not -(2**63) <= key[0] < 2**63
            or not -(2**63) <= key[1] < 2**63
        ):
            raise ValueError("Invalid cursor key")
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        raise InvalidPageCursor("Invalid chat page cursor") from exc
    if value[2] != revision:
        raise StalePageCursor("Chat page snapshot changed")
    return key[0], key[1], key[2]


def session_page(
    host: Any, user_id: str, limit: int, before: str | None, known_revision: str | None
) -> dict[str, Any]:
    if not host._chat_db_path.exists():
        raise RuntimeError("Chat storage is unavailable")
    conn = host._get_conn()
    conn.execute("BEGIN")
    try:
        revision = read_revision(conn, user_id, "")
        scope = ["sessions", user_id]
        boundary = decode_page_cursor(before, scope=scope, revision=revision)
        result: dict[str, Any] = {
            "user_id": user_id,
            "sessions": [],
            "count": 0,
            "revision": revision,
            "not_modified": False,
            "has_more": False,
            "next_before": None,
        }
        if before is None and known_revision == revision:
            result["not_modified"] = True
            return result
        query = """
            SELECT session_id, title, title_overridden, last_message_preview,
                   last_user_message_preview, workspace_path, updated_at_ms,
                   created_at_ms, last_message_at_ms, message_count, history_version
            FROM chat_sessions
            WHERE user_id = ? AND deleted_at_ms IS NULL AND archived_at_ms IS NULL
        """
        params: list[Any] = [user_id]
        if boundary is not None:
            query += " AND (updated_at_ms, created_at_ms, session_id) < (?, ?, ?)"
            params.extend(boundary)
        query += " ORDER BY updated_at_ms DESC, created_at_ms DESC, session_id DESC LIMIT ?"
        params.append(limit + 1)
        rows = conn.execute(query, params).fetchall()
        result["has_more"] = len(rows) > limit
        rows = rows[:limit]
        result["sessions"] = [host._row_to_session_summary(row).to_dict() for row in rows]
        result["count"] = len(rows)
        if result["has_more"]:
            row = rows[-1]
            result["next_before"] = encode_page_cursor(
                scope, revision, [row["updated_at_ms"], row["created_at_ms"], row["session_id"]]
            )
        return result
    finally:
        conn.rollback()


class _TraceSnapshotChanged(RuntimeError):
    """Trace enrichment changed while the transcript snapshot was projected."""


def history_page(
    host: Any,
    user_id: str,
    session_id: str,
    limit: int,
    before: str | None,
    known_revision: str | None,
    turn_id: str | None,
) -> dict[str, Any]:
    from .history_operations import _get_chat_trace_read_service

    trace_service = _get_chat_trace_read_service()
    for _ in range(3):
        try:
            return _history_page_snapshot(
                host, trace_service, user_id, session_id, limit, before, known_revision, turn_id
            )
        except _TraceSnapshotChanged:
            continue
    raise RuntimeError("Conversation trace changed during history read")


def _checked_history_page(
    trace_service: Any, user_id: str, session_id: str, trace_revision: str, result: dict[str, Any]
) -> dict[str, Any]:
    if trace_service.get_read_revision(user_id=user_id, session_id=session_id) != trace_revision:
        raise _TraceSnapshotChanged("Conversation trace changed during history read")
    return result


def _history_page_snapshot(
    host: Any,
    trace_service: Any,
    user_id: str,
    session_id: str,
    limit: int,
    before: str | None,
    known_revision: str | None,
    turn_id: str | None,
) -> dict[str, Any]:
    from .history_operations import (
        _DisplayHistoryRows,
        _build_turn_display_metadata,
        _project_display_history,
        _build_trace_status_message,
    )

    if not host._chat_db_path.exists():
        raise RuntimeError("Chat storage is unavailable")
    conn = host._get_conn()
    conn.execute("BEGIN")
    try:
        trace_revision = trace_service.get_read_revision(user_id=user_id, session_id=session_id)
        revision = f"{read_revision(conn, user_id, session_id)}|{trace_revision}"
        scope = ["history", user_id, session_id, turn_id or ""]
        boundary = decode_page_cursor(before, scope=scope, revision=revision)
        session = conn.execute(
            "SELECT history_version FROM chat_sessions WHERE user_id = ? AND session_id = ? AND deleted_at_ms IS NULL",
            (user_id, session_id),
        ).fetchone()
        result: dict[str, Any] = {
            "user_id": user_id,
            "session_id": session_id,
            "messages": [],
            "count": 0,
            "history_version": int(session["history_version"]) if session else 0,
            "context_usage": None,
            "revision": revision,
            "not_modified": False,
            "has_more": False,
            "next_before": None,
        }
        active = conn.execute(
            """SELECT 1 FROM chat_turns WHERE user_id = ? AND session_id = ?
               AND status NOT IN ('completed', 'failed', 'cancelled', 'discarded', 'superseded') LIMIT 1""",
            (user_id, session_id),
        ).fetchone()
        if before is None and known_revision == revision and active is None:
            result["not_modified"] = True
            return _checked_history_page(trace_service, user_id, session_id, trace_revision, result)
        if session is None:
            return _checked_history_page(trace_service, user_id, session_id, trace_revision, result)
        query = """
            SELECT * FROM chat_messages
            WHERE user_id = ? AND session_id = ? AND is_visible = 1
              AND (replaced_by_message_id IS NULL OR message_kind = 'assistant_interim')
        """
        params: list[Any] = [user_id, session_id]
        if turn_id is not None:
            query += " AND turn_id = ?"
            params.append(turn_id)
        if boundary is not None:
            query += " AND (created_at_ms, sequence_no, message_id) < (?, ?, ?)"
            params.extend(boundary)
        query += " ORDER BY created_at_ms DESC, sequence_no DESC, message_id DESC LIMIT ?"
        params.append(limit + 1)
        rows = conn.execute(query, params).fetchall()
        result["has_more"] = len(rows) > limit
        rows = rows[:limit]
        if result["has_more"]:
            row = rows[-1]
            result["next_before"] = encode_page_cursor(
                scope, revision, [row["created_at_ms"], row["sequence_no"], row["message_id"]]
            )
        if turn_id is not None:
            anchor = conn.execute(
                """SELECT * FROM chat_messages WHERE user_id = ? AND session_id = ? AND turn_id = ?
                   AND message_kind = 'user_text' AND is_visible = 1 AND replaced_by_message_id IS NULL
                   ORDER BY created_at_ms, sequence_no, message_id LIMIT 1""",
                (user_id, session_id, turn_id),
            ).fetchone()
            if anchor is not None and all(
                row["message_id"] != anchor["message_id"] for row in rows
            ):
                rows.append(anchor)
        rows.sort(key=lambda row: (row["created_at_ms"], row["sequence_no"], row["message_id"]))
        turn_ids = sorted({str(row["turn_id"]) for row in rows if row["turn_id"]})
        turn_rows = []
        if turn_ids:
            placeholders = ",".join("?" for _ in turn_ids)
            turn_rows = conn.execute(
                f"SELECT * FROM chat_turns WHERE user_id = ? AND session_id = ? AND turn_id IN ({placeholders})",
                (user_id, session_id, *turn_ids),
            ).fetchall()
        trace_activity = {
            selected: summary
            for selected in turn_ids
            if (
                summary := trace_service.get_trace_summary(
                    user_id=user_id, session_id=session_id, turn_id=selected
                )
            )
        }
        metadata = _build_turn_display_metadata(host, turn_rows)
        projection = _project_display_history(
            host=host,
            trace_service=trace_service,
            trace_activity=trace_activity,
            rows=_DisplayHistoryRows(turn_rows, rows),
            metadata=metadata,
            user_id=user_id,
            session_id=session_id,
        )
        messages = list(projection.display_messages)
        selected_ids = {row["message_id"] for row in rows}
        for turn in turn_rows:
            selected = str(turn["turn_id"])
            first = conn.execute(
                """SELECT message_id FROM chat_messages WHERE user_id = ? AND session_id = ? AND turn_id = ?
                   AND is_visible = 1 AND replaced_by_message_id IS NULL
                   ORDER BY created_at_ms, sequence_no, message_id LIMIT 1""",
                (user_id, session_id, selected),
            ).fetchone()
            assistant = conn.execute(
                """SELECT 1 FROM chat_messages WHERE user_id = ? AND session_id = ? AND turn_id = ?
                   AND is_visible = 1 AND role = 'assistant'
                   AND message_kind IN ('assistant_final', 'assistant_interim', 'assistant_reaction', 'assistant_rhythm_segment', 'ask_request')
                   AND (replaced_by_message_id IS NULL OR message_kind = 'assistant_interim') LIMIT 1""",
                (user_id, session_id, selected),
            ).fetchone()
            if first is None or first["message_id"] not in selected_ids or assistant is not None:
                continue
            status = _build_trace_status_message(
                turn=turn,
                turn_messages=projection.messages_by_turn.get(selected, []),
                trace_service=trace_service,
                trace_activity=trace_activity,
                metadata=metadata,
                user_id=user_id,
                session_id=session_id,
                turn_id=selected,
            )
            if status is not None:
                messages.append(status)
        host._attach_reply_previews(
            rows=projection.display_rows, messages=projection.display_messages
        )
        messages.sort(key=lambda item: item.timestamp)
        result["messages"] = [message.to_dict() for message in messages]
        result["count"] = len(messages)
        usage = host.get_latest_context_usage(user_id, session_id)
        result["context_usage"] = usage.to_dict() if usage is not None else None
        return _checked_history_page(trace_service, user_id, session_id, trace_revision, result)
    finally:
        conn.rollback()
