"""Attachment row persistence for the chat store."""

from __future__ import annotations

import aiosqlite

from ..contracts import ChatMessageRecord
from .serialization import extract_attachment_payloads, public_attachment_payloads, storage_rel_path


class ChatAttachmentPersistenceMixin:
    """Persist chat message attachment metadata."""

    @staticmethod
    def _extract_attachment_payloads(raw_payload_json: str | None) -> list[dict[str, object]]:
        return extract_attachment_payloads(raw_payload_json)

    @staticmethod
    def _public_attachment_payloads(
        attachment_payloads: list[dict[str, object]] | None,
    ) -> list[dict[str, object]]:
        return public_attachment_payloads(attachment_payloads)

    async def _replace_message_attachments(
        self,
        db: aiosqlite.Connection,
        *,
        message: ChatMessageRecord,
        attachment_payloads: list[dict[str, object]] | None,
    ) -> None:
        await db.execute(
            "DELETE FROM chat_attachments WHERE message_id = ?",
            (message.message_id,),
        )
        for attachment in attachment_payloads or []:
            attachment_id = str(attachment.get("attachment_id") or "").strip()
            attachment_storage_path = str(attachment.get("storage_path") or "").strip()
            if not attachment_id or not attachment_storage_path:
                continue
            relative_storage_path = self._storage_rel_path(attachment_storage_path)
            if not relative_storage_path:
                continue
            raw_size_bytes = attachment.get("size_bytes")
            size_bytes = raw_size_bytes if isinstance(raw_size_bytes, int) else int(str(raw_size_bytes or 0))
            await db.execute(
                """
                INSERT OR REPLACE INTO chat_attachments (
                    attachment_id,
                    session_id,
                    turn_id,
                    message_id,
                    user_id,
                    kind,
                    original_name,
                    mime_type,
                    size_bytes,
                    storage_rel_path,
                    sha256,
                    created_at_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment_id,
                    message.session_id,
                    message.turn_id,
                    message.message_id,
                    message.user_id,
                    str(attachment.get("kind") or "file").strip() or "file",
                    str(attachment.get("original_name") or "").strip(),
                    str(attachment.get("mime_type") or "application/octet-stream").strip()
                    or "application/octet-stream",
                    size_bytes,
                    relative_storage_path,
                    str(attachment.get("sha256") or "").strip() or None,
                    message.created_at_ms,
                ),
            )

    @staticmethod
    def _storage_rel_path(storage_path: str) -> str | None:
        return storage_rel_path(storage_path)