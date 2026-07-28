"""Row construction and SQL writes used by user-turn acceptance."""

from __future__ import annotations

import uuid

import aiosqlite

from ..contracts import ChatMessageRecord, ChatSessionRecord
from .messages import MESSAGE_SELECT_COLUMNS
from .serialization import (
    build_user_message_payload_json,
    row_to_message,
    serialize_message_label,
)
from .user_turn_delivery_errors import ChatTurnConflictError


def validate_user_turn_session(
    existing_session: aiosqlite.Row | None,
    *,
    session_id: str,
    user_id: str,
) -> None:
    """Prevent a new turn from taking over or reviving an existing session."""

    if existing_session is None:
        return
    if str(existing_session["session_id"] or "") != str(session_id):
        raise ChatTurnConflictError(
            f"Session '{session_id}' conflicts with an existing session identifier"
        )
    if str(existing_session["user_id"] or "") != str(user_id):
        raise ChatTurnConflictError(f"Session '{session_id}' belongs to a different user")
    if (
        existing_session["archived_at_ms"] is not None
        or existing_session["deleted_at_ms"] is not None
    ):
        raise ChatTurnConflictError(f"Session '{session_id}' is not available")


async def fetch_existing_user_turn_message(
    db: aiosqlite.Connection,
    *,
    turn_id: str,
) -> ChatMessageRecord | None:
    """Load the committed user message or reject a broken partial turn."""

    cursor = await db.execute(
        f"""
        SELECT {MESSAGE_SELECT_COLUMNS}
        FROM chat_messages
        WHERE turn_id = ?
          AND role = 'user'
          AND message_kind = 'user_text'
        ORDER BY created_at_ms ASC, sequence_no ASC
        LIMIT 1
        """,
        (turn_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        turn_cursor = await db.execute(
            "SELECT 1 FROM chat_turns WHERE turn_id = ? LIMIT 1",
            (turn_id,),
        )
        if await turn_cursor.fetchone() is not None:
            raise ChatTurnConflictError(f"Turn '{turn_id}' exists without a committed user message")
        return None
    return row_to_message(row)


def validate_user_turn_retry(
    existing_message: ChatMessageRecord,
    *,
    requested_message: ChatMessageRecord,
) -> None:
    """Reject reuse of one stable turn identity for different user input."""

    comparable_existing = (
        existing_message.session_id,
        existing_message.user_id,
        existing_message.content_text or "",
        existing_message.payload_json,
        existing_message.reply_to_message_id,
    )
    comparable_requested = (
        requested_message.session_id,
        requested_message.user_id,
        requested_message.content_text or "",
        requested_message.payload_json,
        requested_message.reply_to_message_id,
    )
    if comparable_existing != comparable_requested:
        raise ChatTurnConflictError(
            f"Turn '{requested_message.turn_id}' was already used for different input"
        )


def build_user_turn_message(
    *,
    session_id: str,
    user_id: str,
    turn_id: str,
    message_text: str,
    attachment_payloads: list[dict[str, object]] | None,
    message_payload: dict[str, object] | None,
    created_at_ms: int,
    persona_id: str | None,
    reply_to_message_id: str | None,
) -> ChatMessageRecord:
    """Build the canonical first message for one accepted user turn."""

    return ChatMessageRecord(
        message_id=f"msg_{uuid.uuid4().hex[:16]}",
        session_id=session_id,
        turn_id=turn_id,
        user_id=user_id,
        role="user",
        message_kind="user_text",
        content_text=message_text,
        payload_json=build_user_message_payload_json(
            attachment_payloads,
            message_payload,
        ),
        is_final=True,
        is_visible=True,
        created_at_ms=created_at_ms,
        sequence_no=1,
        replaces_message_id=None,
        replaced_by_message_id=None,
        persona_id=str(persona_id or "").strip() or None,
        reply_to_message_id=str(reply_to_message_id or "").strip() or None,
    )


def build_user_turn_session_record(
    *,
    existing_session: aiosqlite.Row | None,
    session_id: str,
    user_id: str,
    session_preview: str,
    created_at_ms: int,
    workspace_path: str | None,
) -> ChatSessionRecord:
    """Build the session row update owned by the acceptance transaction."""

    return ChatSessionRecord(
        session_id=session_id,
        user_id=user_id,
        title=_row_text(existing_session, "title"),
        title_overridden=_row_bool(existing_session, "title_overridden"),
        summary=_row_text(existing_session, "summary"),
        created_at_ms=_row_int(
            existing_session,
            "created_at_ms",
            created_at_ms,
        ),
        updated_at_ms=created_at_ms,
        last_message_at_ms=created_at_ms,
        last_user_message_at_ms=created_at_ms,
        last_message_preview=session_preview,
        last_user_message_preview=session_preview,
        message_count=_row_int(existing_session, "message_count", 0) + 1,
        workspace_path=workspace_path,
        history_version=_row_int(existing_session, "history_version", 0) + 1,
        archived_at_ms=_row_optional_int(existing_session, "archived_at_ms"),
        deleted_at_ms=_row_optional_int(existing_session, "deleted_at_ms"),
    )


def existing_session_workspace_path(
    existing_session: aiosqlite.Row | None,
) -> str | None:
    """Return the workspace already owned by one existing session."""

    if existing_session is None or existing_session["workspace_path"] is None:
        return None
    return str(existing_session["workspace_path"])


async def insert_user_turn_row(
    db: aiosqlite.Connection,
    *,
    session_id: str,
    user_id: str,
    turn_id: str,
    created_at_ms: int,
    run_id: str | None,
    run_revision: int,
    run_disposition: str | None,
) -> None:
    """Insert the queued turn row inside its owning acceptance transaction."""

    await db.execute(
        """
        INSERT INTO chat_turns (
            turn_id,
            session_id,
            user_id,
            trace_id,
            orchestration_id,
            status,
            response_mode,
            execution_mode,
            ux_plan_json,
            created_at_ms,
            updated_at_ms,
            completed_at_ms,
            error_text,
            run_id,
            run_revision,
            run_disposition,
            response_anchor_turn_id,
            superseded_by_turn_id,
            supersession_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(turn_id) DO NOTHING
        """,
        (
            turn_id,
            session_id,
            user_id,
            None,
            None,
            "queued",
            "final_only",
            None,
            "{}",
            created_at_ms,
            created_at_ms,
            None,
            None,
            run_id,
            run_revision,
            run_disposition,
            turn_id,
            None,
            None,
        ),
    )


async def insert_user_message_row(
    db: aiosqlite.Connection,
    message: ChatMessageRecord,
) -> None:
    """Insert the first transcript row inside its owning acceptance transaction."""

    await db.execute(
        """
        INSERT OR REPLACE INTO chat_messages (
            message_id,
            session_id,
            turn_id,
            user_id,
            role,
            message_kind,
            content_text,
            payload_json,
            is_final,
            is_visible,
            created_at_ms,
            sequence_no,
            replaces_message_id,
            replaced_by_message_id,
            persona_id,
            reply_to_message_id,
            label_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message.message_id,
            message.session_id,
            message.turn_id,
            message.user_id,
            message.role,
            message.message_kind,
            message.content_text,
            message.payload_json,
            1,
            1,
            message.created_at_ms,
            message.sequence_no,
            None,
            None,
            message.persona_id,
            message.reply_to_message_id,
            serialize_message_label(message.label),
        ),
    )


def _row_text(row: aiosqlite.Row | None, key: str) -> str:
    if row is None:
        return ""
    return str(row[key] or "")


def _row_bool(row: aiosqlite.Row | None, key: str) -> bool:
    if row is None:
        return False
    return bool(int(row[key] or 0))


def _row_int(row: aiosqlite.Row | None, key: str, default: int) -> int:
    if row is None:
        return default
    return int(row[key] or default)


def _row_optional_int(
    row: aiosqlite.Row | None,
    key: str,
) -> int | None:
    if row is None or row[key] is None:
        return None
    return int(row[key])


__all__ = [
    "build_user_turn_message",
    "build_user_turn_session_record",
    "existing_session_workspace_path",
    "fetch_existing_user_turn_message",
    "insert_user_message_row",
    "insert_user_turn_row",
    "validate_user_turn_retry",
    "validate_user_turn_session",
]
