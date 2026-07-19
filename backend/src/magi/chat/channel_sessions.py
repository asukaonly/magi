"""Chat-owned services used by external channel ingress."""

from __future__ import annotations

import uuid

from .contracts import ChatSessionRecord
from .store import ChatStore


class ChatChannelSessionProvisioner:
    """Create chat sessions for external channel conversations."""

    def __init__(self, *, chat_store: ChatStore) -> None:
        self._chat_store = chat_store

    async def is_channel_session_available(
        self,
        *,
        magi_user_id: str,
        session_id: str,
    ) -> bool:
        """Return whether an existing channel mapping still owns a live chat."""

        return await self._chat_store.is_session_available(
            user_id=magi_user_id,
            session_id=session_id,
        )

    async def create_channel_session(
        self,
        *,
        channel_type: str,
        external_chat_id: str,
        magi_user_id: str,
        display_name: str | None,
        created_at_ms: int,
    ) -> str:
        session_id = f"chsess_{uuid.uuid4().hex[:12]}"
        title = display_name or f"{channel_type.capitalize()}: {external_chat_id}"
        await self._chat_store.upsert_session(
            ChatSessionRecord(
                session_id=session_id,
                user_id=magi_user_id,
                title=title,
                title_overridden=False,
                summary="",
                created_at_ms=created_at_ms,
                updated_at_ms=created_at_ms,
                last_message_at_ms=None,
                last_user_message_at_ms=None,
                last_message_preview="",
                last_user_message_preview="",
                message_count=0,
                archived_at_ms=None,
                deleted_at_ms=None,
                workspace_path=None,
                history_version=0,
            )
        )
        return session_id


__all__ = ["ChatChannelSessionProvisioner"]
