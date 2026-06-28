"""Runtime notifications for chat message lifecycle changes."""

from __future__ import annotations

from ..core.logger import get_logger
from ..runtime_trace.notification_payloads import (
    CHAT_MESSAGE_HIDDEN,
    CHAT_MESSAGE_UPSERTED,
    build_notification_record,
    chat_message_hidden_payload,
    chat_message_upsert_payload,
)
from ..runtime_trace.provider import resolve_runtime_trace_store
from .read_service import get_chat_read_service

logger = get_logger(__name__)


async def broadcast_chat_message_upsert(
    *,
    user_id: str,
    session_id: str,
    message_id: str,
) -> None:
    """Write a chat message upsert notification for the Rust event bridge."""
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

    try:
        store = resolve_runtime_trace_store()
        await store.append_notification(
            build_notification_record(
                channel=CHAT_MESSAGE_UPSERTED,
                user_id=normalized_user_id,
                session_id=normalized_session_id,
                payload=chat_message_upsert_payload(
                    user_id=normalized_user_id,
                    session_id=normalized_session_id,
                    message_id=normalized_message_id,
                    message=message,
                    session_summary=session_summary,
                ),
            )
        )
    except Exception as exc:
        logger.debug("Failed to write chat_message_upserted notification", error=str(exc))


async def broadcast_chat_message_hidden(
    *,
    user_id: str,
    session_id: str,
    message_id: str,
) -> None:
    """Write a chat message hidden notification for the Rust event bridge."""
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

    try:
        store = resolve_runtime_trace_store()
        await store.append_notification(
            build_notification_record(
                channel=CHAT_MESSAGE_HIDDEN,
                user_id=normalized_user_id,
                session_id=normalized_session_id,
                payload=chat_message_hidden_payload(
                    user_id=normalized_user_id,
                    session_id=normalized_session_id,
                    message_id=normalized_message_id,
                    session_summary=session_summary,
                ),
            )
        )
    except Exception as exc:
        logger.debug("Failed to write chat_message_hidden notification", error=str(exc))


class ChatMessageNotifier:
    """Bound chat notification implementation for boundary-facing callers."""

    async def broadcast_chat_message_upsert(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> None:
        await broadcast_chat_message_upsert(
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
        )

    async def broadcast_chat_message_hidden(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> None:
        await broadcast_chat_message_hidden(
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
        )


chat_message_notifier = ChatMessageNotifier()


__all__ = [
    "ChatMessageNotifier",
    "broadcast_chat_message_hidden",
    "broadcast_chat_message_upsert",
    "chat_message_notifier",
]
