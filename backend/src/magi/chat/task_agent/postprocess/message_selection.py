"""Assistant chat message read selectors for post-processing."""
from __future__ import annotations

from typing import Any

from magi.chat import ChatMessageRecord, ChatStore


class ChatOutcomeMessageSelector:
    """Select persisted messages for notification and UX surfaces."""

    def __init__(self, *, chat_store: ChatStore | None) -> None:
        self._chat_store = chat_store

    async def get_notification_chat_message(
        self,
        *,
        turn_id: str | None,
        ux_plan: dict[str, Any] | None,
    ) -> ChatMessageRecord | None:
        response_mode = str((ux_plan or {}).get("assistant_surface_mode") or "").strip()
        if response_mode == "reaction_only":
            return None
        return await self.get_chat_message(turn_id=turn_id, message_kind="assistant_final")

    async def get_turn_ux_chat_message(
        self,
        *,
        turn_id: str | None,
        ux_plan: dict[str, Any] | None,
    ) -> ChatMessageRecord | None:
        response_mode = str((ux_plan or {}).get("assistant_surface_mode") or "").strip()
        if response_mode == "reaction_only":
            return None
        if response_mode == "interim_then_final":
            return await self.get_chat_message(turn_id=turn_id, message_kind="assistant_interim")
        return None

    async def get_chat_message(
        self,
        *,
        turn_id: str | None,
        message_kind: str,
    ) -> ChatMessageRecord | None:
        normalized_turn_id = str(turn_id or "").strip()
        if self._chat_store is None or not normalized_turn_id:
            return None
        return await self._chat_store.get_latest_message_for_turn(
            normalized_turn_id,
            message_kind=message_kind,
        )


__all__ = ["ChatOutcomeMessageSelector"]
