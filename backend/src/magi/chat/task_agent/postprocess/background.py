"""Background task completion helpers for chat post-processing."""

from __future__ import annotations

import json
import uuid
from typing import Any

from magi.chat import ChatMessageRecord


async def persist_completion_message(
    chat_store: Any,
    *,
    session_id: str,
    user_id: str,
    role: str,
    message_kind: str,
    body: str,
    payload: dict[str, Any],
    pending_message_id: str | None,
    created_at_ms: int,
) -> "ChatMessageRecord | None":
    """Append a completion transcript row with a caller-supplied body.

    Owns the record fields / pending-replacement / history-bump semantics
    for background-task completion rows so the outreach
    ``DesktopTranscriptExecutor`` writes them through one persistence path.
    """
    if chat_store is None:
        return None
    record = ChatMessageRecord(
        message_id=f"msg_{uuid.uuid4().hex[:16]}",
        session_id=session_id,
        turn_id=None,
        user_id=user_id,
        role=role,
        message_kind=message_kind,
        content_text=body,
        payload_json=json.dumps(payload, ensure_ascii=False),
        is_final=True,
        is_visible=True,
        created_at_ms=created_at_ms,
        sequence_no=await chat_store.next_sequence_no(session_id=session_id),
        replaces_message_id=pending_message_id,
        replaced_by_message_id=None,
    )
    await chat_store.append_message(record)
    if pending_message_id is not None:
        await chat_store.mark_message_replaced(
            message_id=pending_message_id,
            replaced_by_message_id=record.message_id,
        )
    await chat_store.bump_history_version(session_id)
    return record
