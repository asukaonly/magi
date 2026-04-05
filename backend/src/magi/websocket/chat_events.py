"""Helpers for broadcasting chat transcript lifecycle updates."""

from __future__ import annotations

import json

from ..chat import get_chat_read_service
from ..core.logger import get_logger
from ..core.runtime_bindings import require_runtime_trace_store
from ..runtime_trace import RuntimeNotificationRecord
from .connection_manager import manager

logger = get_logger(__name__)


async def broadcast_chat_message_upsert(
    *,
    user_id: str,
    session_id: str,
    message_id: str,
) -> None:
    """Broadcast one visible transcript message snapshot to connected chat clients."""
    normalized_user_id = str(user_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    normalized_message_id = str(message_id or "").strip()
    if not normalized_user_id or not normalized_session_id or not normalized_message_id:
        return
    try:
        read_service = get_chat_read_service()
        message = await read_service.aget_display_message(
            normalized_user_id,
            normalized_session_id,
            normalized_message_id,
        )
        session_summary = await read_service.aget_session_summary(
            normalized_user_id,
            normalized_session_id,
        )
    except Exception as exc:
        logger.debug(
            "Failed to load chat message event payload",
            user_id=normalized_user_id,
            session_id=normalized_session_id,
            message_id=normalized_message_id,
            error=str(exc),
        )
        return
    if message is None:
        return

    payload_data = {
        "user_id": normalized_user_id,
        "session_id": normalized_session_id,
        "message_id": normalized_message_id,
        "message": message.to_dict(),
        "session_summary": session_summary.to_dict() if session_summary is not None else None,
    }

    # Write to runtime_notifications for Tauri event bridge
    try:
        store = require_runtime_trace_store()
        await store.append_notification(RuntimeNotificationRecord(
            notification_id=0,
            channel="chat_message_upserted",
            user_id=normalized_user_id,
            session_id=normalized_session_id,
            payload_json=json.dumps(payload_data, default=str),
        ))
    except Exception as exc:
        logger.debug("Failed to write chat_message_upserted notification", error=str(exc))

    await manager.broadcast(
        "chat_message_upserted",
        payload_data,
        room=f"user_{normalized_user_id}",
    )


async def broadcast_chat_message_hidden(
    *,
    user_id: str,
    session_id: str,
    message_id: str,
) -> None:
    """Broadcast one hidden transcript message tombstone to connected chat clients."""
    normalized_user_id = str(user_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    normalized_message_id = str(message_id or "").strip()
    if not normalized_user_id or not normalized_session_id or not normalized_message_id:
        return
    try:
        read_service = get_chat_read_service()
        session_summary = await read_service.aget_session_summary(
            normalized_user_id,
            normalized_session_id,
        )
    except Exception as exc:
        logger.debug(
            "Failed to load chat message hidden payload",
            user_id=normalized_user_id,
            session_id=normalized_session_id,
            message_id=normalized_message_id,
            error=str(exc),
        )
        return

    payload_data = {
        "user_id": normalized_user_id,
        "session_id": normalized_session_id,
        "message_id": normalized_message_id,
        "session_summary": session_summary.to_dict() if session_summary is not None else None,
    }

    # Write to runtime_notifications for Tauri event bridge
    try:
        store = require_runtime_trace_store()
        await store.append_notification(RuntimeNotificationRecord(
            notification_id=0,
            channel="chat_message_hidden",
            user_id=normalized_user_id,
            session_id=normalized_session_id,
            payload_json=json.dumps(payload_data, default=str),
        ))
    except Exception as exc:
        logger.debug("Failed to write chat_message_hidden notification", error=str(exc))

    await manager.broadcast(
        "chat_message_hidden",
        payload_data,
        room=f"user_{normalized_user_id}",
    )
