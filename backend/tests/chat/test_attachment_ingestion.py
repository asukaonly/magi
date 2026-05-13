from __future__ import annotations

import zlib
from pathlib import Path

import pytest

from magi.chat.attachment_ingestion import LocalChatAttachmentIngestionService
from magi.i18n import language_context
from magi.utils.runtime import RuntimePaths


def test_ingest_text_attachment_returns_unparsed_upload_metadata(tmp_path: Path) -> None:
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
    assert payload["parse_status"] == "pending"
    assert payload["original_name"] == "notes.md"
    assert Path(str(payload["storage_path"])).is_file()
    assert "derived_text_path" not in payload


def test_prepare_runtime_text_attachment_writes_derived_text_file(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)

    upload_payload = service.ingest_attachment(
        session_id="session-1",
        turn_id="turn-1",
        original_name="notes.md",
        content=b"# hello\nworld\n",
        mime_type="text/markdown",
    )

    payload = service.prepare_runtime_attachment(
        session_id="session-1",
        turn_id="turn-1",
        attachment=upload_payload,
    )

    assert payload["kind"] == "text_file"
    assert payload["parse_status"] == "parsed"
    assert payload["derived_text_excerpt"] == "# hello\nworld\n"
    assert payload["character_count"] == len("# hello\nworld\n")
    derived_text_path = Path(str(payload["derived_text_path"]))
    assert derived_text_path.is_file()
    assert derived_text_path.read_text(encoding="utf-8") == "# hello\nworld\n"


def test_ingest_attachment_rejects_unsupported_file_type(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)

    with language_context("en"), pytest.raises(ValueError, match="Unsupported attachment type"):
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

    with language_context("en"), pytest.raises(
        ValueError,
        match="Image attachment exceeds the 20 MB limit",
    ):
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

    with language_context("en"), pytest.raises(
        ValueError,
        match="File attachment exceeds the 50 MB limit",
    ):
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


def test_prepare_runtime_pdf_attachment_writes_derived_text_file(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)

    upload_payload = service.ingest_attachment(
        session_id="session-1",
        turn_id="turn-1",
        original_name="report.pdf",
        content=_build_simple_pdf_bytes("Hello PDF", compressed=True),
        mime_type="application/pdf",
    )

    assert upload_payload["kind"] == "pdf"
    assert upload_payload["parse_status"] == "pending"
    assert "derived_text_path" not in upload_payload

    payload = service.prepare_runtime_attachment(
        session_id="session-1",
        turn_id="turn-1",
        attachment=upload_payload,
    )

    assert payload["kind"] == "pdf"
    assert payload["parse_status"] == "parsed"
    assert payload["original_name"] == "report.pdf"
    assert payload["derived_text_excerpt"] == "Hello PDF"
    assert payload["character_count"] == len("Hello PDF")
    assert payload["page_count"] == 1
    derived_text_path = Path(str(payload["derived_text_path"]))
    assert derived_text_path.is_file()
    assert derived_text_path.read_text(encoding="utf-8") == "Hello PDF"


def _build_simple_pdf_bytes(text: str, *, compressed: bool = False) -> bytes:
    content_stream = f"BT\n/F1 12 Tf\n72 72 Td\n({text}) Tj\nET".encode("latin-1")
    stored_stream = zlib.compress(content_stream) if compressed else content_stream
    filter_entry = b" /Filter /FlateDecode" if compressed else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length "
        + str(len(stored_stream)).encode("ascii")
        + filter_entry
        + b" >>\nstream\n"
        + stored_stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    return _build_pdf_bytes(objects)


def _build_pdf_bytes(objects: list[bytes]) -> bytes:
    header = b"%PDF-1.4\n"
    body = b""
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body += f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"
    xref_offset = len(header) + len(body)
    xref_entries = b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets)
    xref = (
        b"xref\n0 "
        + str(len(objects) + 1).encode("ascii")
        + b"\n0000000000 65535 f \n"
        + xref_entries
    )
    trailer = (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode("ascii")
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    return header + body + xref + trailer
