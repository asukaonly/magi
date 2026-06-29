"""Assistant chat projection persistence for post-processing."""
from __future__ import annotations

from magi.chat import ChatMessageRecord, ChatProjector


class ChatMessageProjectionWriter:
    """Project persisted assistant messages into canonical chat context."""

    def __init__(self, *, chat_projector: ChatProjector | None) -> None:
        self._chat_projector = chat_projector

    async def project_final_chat_message(
        self,
        *,
        user_id: str,
        session_id: str,
        final_message: ChatMessageRecord | None,
    ) -> None:
        if self._chat_projector is None or final_message is None or not str(final_message.content_text or "").strip():
            return
        await self._chat_projector.project_assistant_message(
            message_id=final_message.message_id,
            user_id=user_id,
            session_id=session_id,
            turn_id=str(final_message.turn_id or ""),
            content=str(final_message.content_text or ""),
            created_at_ms=final_message.created_at_ms,
        )

    async def project_canonical_assistant_response(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        message_id: str | None,
        content: str,
        created_at_ms: int,
    ) -> None:
        if self._chat_projector is None or not str(content or "").strip():
            return
        normalized_turn_id = str(turn_id or "").strip()
        normalized_message_id = str(message_id or "").strip()
        if not normalized_turn_id or not normalized_message_id:
            return
        await self._chat_projector.project_assistant_message(
            message_id=normalized_message_id,
            user_id=user_id,
            session_id=session_id,
            turn_id=normalized_turn_id,
            content=str(content or ""),
            created_at_ms=created_at_ms,
        )


__all__ = ["ChatMessageProjectionWriter"]
