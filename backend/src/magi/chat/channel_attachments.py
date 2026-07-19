"""Chat-owned attachment store for channel plugins."""

from __future__ import annotations

from typing import Any

from magi_plugin_sdk.channels import ChannelAttachmentStoreProtocol

from ..utils.runtime import RuntimePaths
from magi.core.chat_assets.mutations import run_chat_asset_mutation
from .attachment_storage import LocalChatAttachmentStorage, StoredChatAttachment


class ChatChannelAttachmentStore(ChannelAttachmentStoreProtocol):
    """Persist channel inbound attachments through the chat attachment store."""

    def __init__(self, *, runtime_paths: RuntimePaths) -> None:
        self._storage = LocalChatAttachmentStorage(runtime_paths=runtime_paths)

    async def store_attachment(
        self,
        *,
        session_id: str,
        turn_id: str,
        kind: str,
        original_name: str,
        content: bytes,
        mime_type: str,
    ) -> dict[str, Any]:
        stored = await run_chat_asset_mutation(
            self._store_sync,
            session_id=session_id,
            turn_id=turn_id,
            kind=kind,
            original_name=original_name,
            content=content,
            mime_type=mime_type,
        )
        return {
            "attachment_id": stored.attachment_id,
            "kind": stored.kind,
            "original_name": stored.original_name,
            "mime_type": stored.mime_type,
            "size_bytes": stored.size_bytes,
            "storage_path": stored.storage_path,
            "sha256": stored.sha256,
        }

    def _store_sync(
        self,
        *,
        session_id: str,
        turn_id: str,
        kind: str,
        original_name: str,
        content: bytes,
        mime_type: str,
    ) -> StoredChatAttachment:
        if str(kind or "").strip() == "image" or str(mime_type or "").startswith("image/"):
            return self._storage.store_image_attachment(
                session_id=session_id,
                turn_id=turn_id,
                original_name=original_name,
                content=content,
                mime_type=mime_type,
            )
        return self._storage.store_file_attachment(
            session_id=session_id,
            turn_id=turn_id,
            original_name=original_name,
            content=content,
            mime_type=mime_type,
        )


__all__ = ["ChatChannelAttachmentStore"]
