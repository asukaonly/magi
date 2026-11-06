"""Attachment row persistence for the chat store."""

from __future__ import annotations

from magi_plugin_sdk.storage_chat.statements import statement

from magi_plugin_sdk.storage_chat.relational import AsyncChatConnection

import asyncio
from .host import ChatStorageHost


from magi_plugin_sdk.storage_models.chat_asset_keys import is_safe_chat_asset_component
from magi_plugin_sdk.storage_models.chat import ChatMessageRecord



class ChatAttachmentPersistenceMixin:
    """Persist chat message attachment metadata."""

    host: ChatStorageHost

    async def _replace_message_attachments(
        self,
        db: AsyncChatConnection,
        *,
        message: ChatMessageRecord,
        attachment_payloads: list[dict[str, object]] | None,
    ) -> None:
        if attachment_payloads is None:
            return
        prepared = await asyncio.to_thread(self.host.prepare_assets, message, attachment_payloads)
        managed_payloads = prepared.attachments
        await db.execute(
            "DELETE FROM chat_attachments WHERE message_id = ?",
            (message.message_id,),
        )
        await db.execute(
            "DELETE FROM chat_message_asset_refs WHERE message_id = ?",
            (message.message_id,),
        )
        for attachment in managed_payloads:
            attachment_id = str(attachment.get("attachment_id") or "").strip()
            attachment_storage_path = str(attachment.get("storage_rel_path") or "").strip()
            if (
                not is_safe_chat_asset_component(attachment_id)
                or not attachment_storage_path
            ):
                continue
            relative_storage_path = str(attachment["storage_rel_path"])
            raw_size_bytes = attachment.get("size_bytes")
            size_bytes = raw_size_bytes if isinstance(raw_size_bytes, int) else int(str(raw_size_bytes or 0))
            await db.execute(
                statement("""
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
                """, mysql="""
                REPLACE INTO chat_attachments (
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
                """),
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
        asset_references = prepared.references
        if asset_references:
            await db.executemany(
                """
                INSERT INTO chat_message_asset_refs (
                    message_id,
                    asset_key,
                    storage_rel_path,
                    asset_kind,
                    created_at_ms
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        message.message_id,
                        asset_key,
                        relative_path,
                        asset_kind,
                        message.created_at_ms,
                    )
                    for asset_key, relative_path, asset_kind in asset_references
                ],
            )
