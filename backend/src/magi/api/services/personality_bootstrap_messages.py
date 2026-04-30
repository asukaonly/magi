"""Persistence helpers for persona bootstrap chat messages."""

from __future__ import annotations

import json
import time
import uuid

from ...chat.contracts import ChatMessageRecord, ChatTurnRecord
from ...chat.provider import get_chat_store
from ...core.logger import get_logger
from ...runtime_trace.contracts import RuntimeNotificationRecord
from ...runtime_trace.provider import resolve_runtime_trace_store
from ...transport.chat_events import broadcast_chat_message_upsert

logger = get_logger(__name__)


async def persist_bootstrap_assistant_message(
    *,
    session_id: str,
    user_id: str,
    turn_id: str,
    content: str,
) -> str:
    """Persist a bootstrap assistant reply as a chat message and emit a notification."""

    now_ms = int(time.time() * 1000)
    message_id = f"msg_{uuid.uuid4().hex[:16]}"

    chat_store = get_chat_store()

    await chat_store.upsert_turn(ChatTurnRecord(
        turn_id=turn_id,
        session_id=session_id,
        user_id=user_id,
        trace_id=None,
        orchestration_id=None,
        status="completed",
        response_mode="final_only",
        execution_mode=None,
        ux_plan_json="{}",
        created_at_ms=now_ms,
        updated_at_ms=now_ms,
        completed_at_ms=now_ms,
        error_text=None,
    ))

    seq_no = await chat_store.next_sequence_no(session_id=session_id)
    await chat_store.append_message(ChatMessageRecord(
        message_id=message_id,
        session_id=session_id,
        turn_id=turn_id,
        user_id=user_id,
        role="assistant",
        message_kind="assistant_final",
        content_text=content,
        payload_json="{}",
        is_final=True,
        is_visible=True,
        created_at_ms=now_ms,
        sequence_no=seq_no,
        replaces_message_id=None,
        replaced_by_message_id=None,
    ))

    await chat_store.bump_history_version(session_id)
    await broadcast_chat_message_upsert(
        user_id=user_id,
        session_id=session_id,
        message_id=message_id,
    )

    try:
        trace_store = resolve_runtime_trace_store()
        await trace_store.append_notification(RuntimeNotificationRecord(
            notification_id=0,
            channel="agent_response",
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            payload_json=json.dumps({
                "message_id": message_id,
                "message_kind": "assistant_final",
                "content": content,
                "author_type": "assistant",
                "content_type": "text",
                "timestamp": time.time(),
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "orchestration_id": None,
                "trace_summary": None,
                "trace_available": False,
                "ux_plan": {},
            }, ensure_ascii=False),
            created_at_ms=now_ms,
        ))
    except Exception as exc:
        logger.warning("Failed to emit bootstrap notification: %s", exc)

    return message_id


__all__ = ["persist_bootstrap_assistant_message"]