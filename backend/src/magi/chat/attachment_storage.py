"""Managed local storage for chat attachments."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..utils.runtime import RuntimePaths, get_runtime_paths
from magi.core.chat_assets.io import write_managed_chat_asset_atomically
from magi.core.chat_assets.paths import (
    normalize_chat_asset_component,
    prepare_chat_asset_turn_directory,
)

_NON_SAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(slots=True)
class StoredChatAttachment:
    """Metadata describing one stored chat attachment."""

    attachment_id: str
    kind: str
    original_name: str
    mime_type: str
    size_bytes: int
    storage_path: str
    sha256: str


class LocalChatAttachmentStorage:
    """Store chat attachments inside the managed runtime resource directory."""

    def __init__(self, *, runtime_paths: RuntimePaths | None = None) -> None:
        self._runtime_paths = runtime_paths or get_runtime_paths()

    def store_image_attachment(
        self,
        *,
        session_id: str,
        turn_id: str,
        original_name: str,
        content: bytes,
        mime_type: str,
    ) -> StoredChatAttachment:
        """Persist one image attachment for a chat turn."""

        return self._store_attachment(
            kind="image",
            root_dir=self._runtime_paths.chat_images_dir,
            session_id=session_id,
            turn_id=turn_id,
            original_name=original_name,
            content=content,
            mime_type=mime_type,
        )

    def store_file_attachment(
        self,
        *,
        session_id: str,
        turn_id: str,
        original_name: str,
        content: bytes,
        mime_type: str,
    ) -> StoredChatAttachment:
        """Persist one non-image chat attachment for a chat turn."""

        return self._store_attachment(
            kind="file",
            root_dir=self._runtime_paths.chat_files_dir,
            session_id=session_id,
            turn_id=turn_id,
            original_name=original_name,
            content=content,
            mime_type=mime_type,
        )

    def _store_attachment(
        self,
        *,
        kind: str,
        root_dir: Path,
        session_id: str,
        turn_id: str,
        original_name: str,
        content: bytes,
        mime_type: str,
    ) -> StoredChatAttachment:
        normalized_session_id = self._normalize_path_component(session_id, label="session_id")
        normalized_turn_id = self._normalize_path_component(turn_id, label="turn_id")
        display_name = self._sanitize_original_name(original_name)
        attachment_id = uuid.uuid4().hex
        content_bytes = bytes(content)
        target_dir = prepare_chat_asset_turn_directory(
            root_dir,
            session_id=normalized_session_id,
            turn_id=normalized_turn_id,
            runtime_paths=self._runtime_paths,
        )
        target_path = target_dir / f"{attachment_id}__{display_name}"
        if target_path.is_symlink():
            raise ValueError(
                "Managed chat attachment path is outside the expected turn directory"
            )
        write_managed_chat_asset_atomically(target_path, content_bytes)
        return StoredChatAttachment(
            attachment_id=attachment_id,
            kind=kind,
            original_name=display_name,
            mime_type=str(mime_type or "application/octet-stream").strip() or "application/octet-stream",
            size_bytes=len(content_bytes),
            storage_path=str(target_path),
            sha256=hashlib.sha256(content_bytes).hexdigest(),
        )

    @staticmethod
    def _normalize_path_component(value: str, *, label: str) -> str:
        return normalize_chat_asset_component(value, label=label)

    @staticmethod
    def _sanitize_original_name(original_name: str) -> str:
        candidate = Path(str(original_name or "").strip()).name
        if not candidate:
            candidate = "attachment"
        safe_name = _NON_SAFE_FILENAME_CHARS.sub("_", candidate).strip("._")
        return safe_name or "attachment"
