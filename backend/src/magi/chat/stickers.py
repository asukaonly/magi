"""User-owned sticker images, independent of the source chat's lifetime."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any, Literal
import warnings

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from magi.core.chat_assets.io import (
    open_managed_chat_attachment,
    open_resolved_managed_file,
    write_managed_chat_asset_atomically,
)
from magi.core.chat_assets.mutations import require_chat_asset_mutation
from magi.core.chat_assets.paths import verified_chat_asset_root
from magi.utils.private_data import protect_private_directory
from magi.utils.runtime import RuntimePaths, get_runtime_paths

from .attachment_ingestion import LocalChatAttachmentIngestionService

MAX_STICKERS = 64
MAX_STICKER_BYTES = 5 * 1024 * 1024
_IMAGE_FORMATS = {"PNG": "png", "JPEG": "jpeg", "WEBP": "webp", "GIF": "gif"}


class _Sticker(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sticker_id: str = Field(pattern=r"^st_[a-f0-9]{24}$")
    name: str = Field(min_length=1, max_length=80)
    extension: Literal["png", "jpeg", "webp", "gif"]

    def public(self) -> dict[str, str]:
        return {"sticker_id": self.sticker_id, "name": self.name}


class ChatStickerLibrary:
    """Manage a bounded library; writes share the chat asset mutation boundary."""

    def __init__(self, runtime_paths: RuntimePaths | None = None) -> None:
        self._paths = runtime_paths or get_runtime_paths()

    def catalog(self, user_id: str) -> list[dict[str, str]]:
        return [entry.public() for entry in self._load(user_id)]

    def save(
        self, *, user_id: str, session_id: str, attachment: dict[str, Any], name: str,
    ) -> dict[str, str]:
        """Copy one ownership-checked attachment into the user's library."""
        require_chat_asset_mutation()
        name = name.strip()
        if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
            raise ValueError("Sticker name must contain 1 to 80 characters without control characters.")
        if attachment.get("kind") != "image":
            raise ValueError("Only image attachments can be saved as stickers.")
        handle = open_managed_chat_attachment(
            attachment.get("storage_path"), session_id=session_id,
            turn_id=attachment.get("turn_id"), attachment_id=attachment.get("attachment_id"),
            original_name=attachment.get("original_name"), runtime_paths=self._paths,
        )
        if handle is None:
            raise ValueError("Sticker source attachment is unavailable.")
        with handle:
            content = handle.read(MAX_STICKER_BYTES + 1)
        if not content or len(content) > MAX_STICKER_BYTES:
            raise ValueError("Stickers must be nonempty images no larger than 5 MiB.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    extension = _IMAGE_FORMATS.get(image.format or "")
                    image.verify()
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as exc:
            raise ValueError("Sticker image data is invalid.") from exc
        if extension is None:
            raise ValueError("Stickers must use PNG, JPEG, WebP or GIF.")
        entry = _Sticker(sticker_id=self._content_id(content), name=name, extension=extension)
        entries = [item for item in self._load(user_id) if item.sticker_id != entry.sticker_id]
        if len(entries) >= MAX_STICKERS:
            raise ValueError("The sticker library is full. Remove a sticker before saving another.")
        root = self._root(user_id)
        protect_private_directory(root)
        root = self._root(user_id)
        write_managed_chat_asset_atomically(root / self._filename(entry), content)
        self._write_index(user_id, [*entries, entry])
        return entry.public()

    def remove(self, *, user_id: str, sticker_id: str) -> dict[str, str]:
        require_chat_asset_mutation()
        entries = self._load(user_id)
        entry = self._find(entries, sticker_id)
        (self._root(user_id) / self._filename(entry)).unlink(missing_ok=True)
        self._write_index(user_id, [item for item in entries if item != entry])
        return entry.public()

    def prepare_attachment(
        self, *, user_id: str, session_id: str, turn_id: str, sticker_id: str,
    ) -> tuple[dict[str, object], dict[str, str]]:
        """Copy a saved image into this turn so sent messages keep their own asset."""
        require_chat_asset_mutation()
        entry = self._find(self._load(user_id), sticker_id)
        handle = open_resolved_managed_file(lambda: self._resolve(user_id, self._filename(entry)))
        if handle is None:
            raise ValueError("Sticker image is unavailable.")
        with handle:
            content = handle.read(MAX_STICKER_BYTES + 1)
        if len(content) > MAX_STICKER_BYTES or self._content_id(content) != entry.sticker_id:
            raise ValueError("Sticker image integrity check failed.")
        attachment = LocalChatAttachmentIngestionService(runtime_paths=self._paths).ingest_attachment(
            session_id=session_id, turn_id=turn_id, original_name=self._filename(entry),
            content=content, mime_type=f"image/{entry.extension}",
        )
        return attachment, entry.public()

    def _root(self, user_id: str) -> Path:
        if not user_id:
            raise ValueError("Sticker library requires a user identity.")
        scope = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
        return verified_chat_asset_root(self._paths.chat_stickers_dir / scope, self._paths)

    def _resolve(self, user_id: str, filename: str) -> Path | None:
        path = self._root(user_id) / filename
        if path.is_symlink() or path.resolve() != path:
            raise ValueError("Sticker file path was retargeted.")
        return path if path.exists() else None

    def _load(self, user_id: str) -> list[_Sticker]:
        path = self._resolve(user_id, "index.json")
        if path is None:
            return []
        handle = open_resolved_managed_file(lambda: self._resolve(user_id, "index.json"))
        if handle is None:
            raise ValueError("Sticker library index is unreadable.")
        with handle:
            content = handle.read(64 * 1024 + 1)
        if len(content) > 64 * 1024:
            raise ValueError("Sticker library index is too large.")
        entries = TypeAdapter(list[_Sticker]).validate_json(content)
        if len(entries) > MAX_STICKERS or len({item.sticker_id for item in entries}) != len(entries):
            raise ValueError("Sticker library index has invalid entries.")
        return entries

    def _write_index(self, user_id: str, entries: list[_Sticker]) -> None:
        content = json.dumps([entry.model_dump() for entry in entries], ensure_ascii=False).encode("utf-8")
        write_managed_chat_asset_atomically(self._root(user_id) / "index.json", content)

    @staticmethod
    def _content_id(content: bytes) -> str:
        return f"st_{hashlib.sha256(content).hexdigest()[:24]}"

    @staticmethod
    def _filename(entry: _Sticker) -> str:
        return f"{entry.sticker_id}.{entry.extension}"

    @staticmethod
    def _find(entries: list[_Sticker], sticker_id: str) -> _Sticker:
        for entry in entries:
            if entry.sticker_id == sticker_id:
                return entry
        raise ValueError("Sticker ID is not in this user's library.")
