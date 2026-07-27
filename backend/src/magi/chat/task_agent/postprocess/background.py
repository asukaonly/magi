"""Background task completion helpers for chat post-processing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from magi.chat import ChatMessageRecord

_OUTREACH_METADATA_KEY = "_magi_outreach"


@dataclass(frozen=True, slots=True)
class CompletionMessageWriteResult:
    """Authoritative completion row and whether this call created it."""

    record: ChatMessageRecord | None
    created: bool


async def persist_completion_message(
    chat_store: Any,
    *,
    session_id: str,
    user_id: str,
    role: str,
    message_kind: str,
    body: str,
    payload: dict[str, Any],
    turn_id: str | None,
    pending_message_id: str | None,
    created_at_ms: int,
    message_id: str,
    correlation_id: str,
    identity_fingerprint: str,
) -> CompletionMessageWriteResult:
    """Append a completion transcript row with a caller-supplied body.

    Owns the record fields / pending-replacement / history-bump semantics
    for background-task completion rows so the outreach
    ``DesktopTranscriptExecutor`` writes them through one persistence path.
    """
    if chat_store is None:
        return CompletionMessageWriteResult(record=None, created=False)
    durable_payload = dict(payload)
    durable_payload[_OUTREACH_METADATA_KEY] = {
        "correlation_id": correlation_id,
        "intent_fingerprint": identity_fingerprint,
    }
    record = ChatMessageRecord(
        message_id=message_id,
        session_id=session_id,
        turn_id=(str(turn_id or "").strip() or None),
        user_id=user_id,
        role=role,
        message_kind=message_kind,
        content_text=body,
        payload_json=json.dumps(
            durable_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        is_final=True,
        is_visible=True,
        created_at_ms=created_at_ms,
        sequence_no=await chat_store.next_sequence_no(session_id=session_id),
        replaces_message_id=pending_message_id,
        replaced_by_message_id=None,
    )
    persisted, created = await chat_store.append_completion_message_once(record)
    return CompletionMessageWriteResult(record=persisted, created=created)


__all__ = [
    "CompletionMessageWriteResult",
    "persist_completion_message",
]
