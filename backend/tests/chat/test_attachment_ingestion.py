from __future__ import annotations

from pathlib import Path

import pytest

from magi.chat.attachment_ingestion import LocalChatAttachmentIngestionService
from magi.utils.runtime import RuntimePaths


def test_ingest_text_attachment_writes_derived_text_file(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)

    payload = service.ingest_attachment(
        session_id="session-1",
        turn_id="turn-1",
        original_name="notes.md",
        content=b"# hello\nworld\n",
        mime_type="text/markdown",
    )

    assert payload["kind"] == "text_file"
    assert payload["parse_status"] == "parsed"
    assert payload["original_name"] == "notes.md"
    assert payload["derived_text_excerpt"] == "# hello\nworld\n"
    assert payload["character_count"] == len("# hello\nworld\n")
    derived_text_path = Path(str(payload["derived_text_path"]))
    assert derived_text_path.is_file()
    assert derived_text_path.read_text(encoding="utf-8") == "# hello\nworld\n"


def test_ingest_attachment_rejects_unsupported_file_type(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)

    with pytest.raises(ValueError, match="Unsupported attachment type"):
        service.ingest_attachment(
            session_id="session-1",
            turn_id="turn-1",
            original_name="archive.zip",
            content=b"PK",
            mime_type="application/zip",
        )


def test_ingest_attachment_rejects_oversized_image(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)

    with pytest.raises(ValueError, match="Image attachment exceeds the 20 MB limit"):
        service.ingest_attachment(
            session_id="session-1",
            turn_id="turn-1",
            original_name="huge.png",
            content=b"0" * (20 * 1024 * 1024 + 1),
            mime_type="image/png",
        )


def test_ingest_attachment_rejects_oversized_text_file(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)

    with pytest.raises(ValueError, match="File attachment exceeds the 50 MB limit"):
        service.ingest_attachment(
            session_id="session-1",
            turn_id="turn-1",
            original_name="huge.md",
            content=b"0" * (50 * 1024 * 1024 + 1),
            mime_type="text/markdown",
        )


def test_ingest_local_file_imports_existing_image_path(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)
    source_path = tmp_path / "photo.jpg"
    source_path.write_bytes(b"fake-jpeg")

    payload = service.ingest_local_file(
        session_id="session-1",
        turn_id="turn-1",
        file_path=str(source_path),
        mime_type="image/jpeg",
    )

    assert payload["kind"] == "image"
    assert payload["source_path"] == str(source_path)
    assert payload["source_origin"] == "local_file"
    assert Path(str(payload["storage_path"])).is_file()
