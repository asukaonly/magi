from __future__ import annotations

import hashlib
from pathlib import Path

from magi.chat.attachment_storage import LocalChatAttachmentStorage
from magi.utils.runtime import RuntimePaths


def test_store_image_attachment_writes_to_managed_image_directory(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / ".magi")
    storage = LocalChatAttachmentStorage(runtime_paths=runtime_paths)

    stored = storage.store_image_attachment(
        session_id="session-1",
        turn_id="turn-1",
        original_name="diagram.png",
        content=b"image-bytes",
        mime_type="image/png",
    )

    stored_path = Path(stored.storage_path)

    assert stored.kind == "image"
    assert stored.original_name == "diagram.png"
    assert stored.mime_type == "image/png"
    assert stored.size_bytes == len(b"image-bytes")
    assert stored.sha256 == hashlib.sha256(b"image-bytes").hexdigest()
    assert stored_path.parent == runtime_paths.data_dir / "chat_assets" / "images" / "session-1" / "turn-1"
    assert stored_path.read_bytes() == b"image-bytes"


def test_store_file_attachment_writes_to_managed_file_directory_and_sanitizes_name(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / ".magi")
    storage = LocalChatAttachmentStorage(runtime_paths=runtime_paths)

    stored = storage.store_file_attachment(
        session_id="session-1",
        turn_id="turn-2",
        original_name="../notes.md",
        content=b"# notes",
        mime_type="text/markdown",
    )

    stored_path = Path(stored.storage_path)

    assert stored.kind == "file"
    assert stored.original_name == "notes.md"
    assert stored.mime_type == "text/markdown"
    assert stored.size_bytes == len(b"# notes")
    assert stored.sha256 == hashlib.sha256(b"# notes").hexdigest()
    assert stored_path.parent == runtime_paths.data_dir / "chat_assets" / "files" / "session-1" / "turn-2"
    assert stored_path.name.endswith("__notes.md")
    assert stored_path.read_bytes() == b"# notes"
