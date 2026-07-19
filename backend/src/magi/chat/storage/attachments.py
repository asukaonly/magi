"""Attachment row persistence for the chat store."""

from __future__ import annotations

import asyncio

import aiosqlite

from ...utils.runtime import RuntimePaths
from magi.core.chat_assets.mutations import require_chat_asset_mutation
from magi.core.chat_assets.paths import is_safe_chat_asset_component
from ..asset_validation import validate_message_asset_payloads
from ..contracts import ChatMessageRecord
from .serialization import (
    extract_attachment_payloads,
    message_asset_references,
    message_attachment_storage_reference,
    public_attachment_payloads,
)


class ChatAttachmentPersistenceMixin:
    """Persist chat message attachment metadata."""

    _runtime_paths: RuntimePaths

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
        if attachment_payloads is None:
            return
        require_chat_asset_mutation()
        await asyncio.to_thread(
            validate_message_asset_payloads,
            attachment_payloads,
            session_id=message.session_id,
            turn_id=message.turn_id,
            runtime_paths=self._runtime_paths,
        )
        managed_payloads = [
            attachment
            for attachment in attachment_payloads
            if str(attachment.get("kind") or "").strip() != "mcp_resource"
        ]
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
            attachment_storage_path = str(attachment.get("storage_path") or "").strip()
            if (
                not is_safe_chat_asset_component(attachment_id)
                or not attachment_storage_path
            ):
                continue
            storage_reference = message_attachment_storage_reference(
                attachment_storage_path,
                session_id=message.session_id,
                turn_id=message.turn_id,
                attachment_id=attachment_id,
                runtime_paths=self._runtime_paths,
            )
            if storage_reference is None:
                continue
            _, relative_storage_path = storage_reference
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
        asset_references = message_asset_references(
            managed_payloads,
            session_id=message.session_id,
            turn_id=message.turn_id,
            runtime_paths=self._runtime_paths,
        )
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
