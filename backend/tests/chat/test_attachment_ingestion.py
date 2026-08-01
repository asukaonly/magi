from __future__ import annotations

import asyncio
import zlib
from pathlib import Path
from typing import Any, Callable, TypeVar

import pytest

from magi.core.chat_assets.mutations import chat_asset_mutation, run_chat_asset_mutation
from magi.chat.attachment_ingestion import LocalChatAttachmentIngestionService
from magi.i18n import language_context
from magi.utils.runtime import RuntimePaths


R = TypeVar("R")


def _mutate(func: Callable[..., R], **kwargs: Any) -> R:
    return asyncio.run(run_chat_asset_mutation(func, **kwargs))


class FakeHeicPreviewConverter:
    def __init__(self, *, output: bytes = b"fake-jpeg-preview") -> None:
        self.output = output
        self.calls: list[tuple[bytes, str]] = []

    def convert_heic_to_jpeg(self, *, content: bytes, original_name: str) -> bytes:
        self.calls.append((content, original_name))
        return self.output


class FailingHeicPreviewConverter:
    def convert_heic_to_jpeg(self, *, content: bytes, original_name: str) -> bytes:
        raise RuntimeError("decoder unavailable")


@pytest.mark.asyncio
async def test_upload_rechecks_session_after_global_asset_clear(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    session_exists = True
    clear_started = asyncio.Event()
    release_clear = asyncio.Event()

    class _ReadService:
        calls = 0

        async def aget_session_summary(self, _user_id: str, _session_id: str):
            self.calls += 1
            return object() if session_exists else None

    read_service = _ReadService()
    service = LocalChatAttachmentIngestionService(
        runtime_paths=runtime_paths,
        chat_read_service_factory=lambda: read_service,
    )

    async def hold_global_clear_boundary() -> None:
        nonlocal session_exists
        async with chat_asset_mutation():
            clear_started.set()
            await release_clear.wait()
            session_exists = False

    clear_task = asyncio.create_task(hold_global_clear_boundary())
    await clear_started.wait()
    upload_task = asyncio.create_task(
        service.ingest_uploaded_attachment(
            user_id="user-1",
            session_id="session-1",
            turn_id="turn-1",
            original_name="private.txt",
            content=b"private content",
            mime_type="text/plain",
        )
    )
    await asyncio.sleep(0)
    assert read_service.calls == 0

    release_clear.set()
    await clear_task

    assert await upload_task is None
    assert read_service.calls == 1
    assert list(runtime_paths.chat_resources_dir.rglob("*")) == []


def test_ingest_text_attachment_returns_unparsed_upload_metadata(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)

    payload = _mutate(
        service.ingest_attachment,
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

    upload_payload = _mutate(
        service.ingest_attachment,
        session_id="session-1",
        turn_id="turn-1",
        original_name="notes.md",
        content=b"# hello\nworld\n",
        mime_type="text/markdown",
    )

    payload = _mutate(
        service.prepare_runtime_attachment,
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


def test_prepare_runtime_attachment_rejects_traversal_attachment_id(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)
    upload_payload = _mutate(
        service.ingest_attachment,
        session_id="session-1",
        turn_id="turn-1",
        original_name="notes.md",
        content=b"safe source",
        mime_type="text/markdown",
    )
    victim = runtime_paths.base_dir / "victim.txt"
    victim.write_text("keep-me", encoding="utf-8")
    malicious_payload = {
        **upload_payload,
        "attachment_id": "../../../../../../victim",
    }

    prepared = _mutate(
        service.prepare_runtime_attachment,
        session_id="session-1",
        turn_id="turn-1",
        attachment=malicious_payload,
    )

    assert prepared["parse_status"] == "failed"
    assert "storage_path" not in prepared
    assert "derived_text_path" not in prepared
    assert victim.read_text(encoding="utf-8") == "keep-me"


def test_prepare_runtime_attachment_rejects_storage_outside_chat_resources(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)
    outside = runtime_paths.base_dir / "private.txt"
    outside.write_text("private", encoding="utf-8")

    prepared = _mutate(
        service.prepare_runtime_attachment,
        session_id="session-1",
        turn_id="turn-1",
        attachment={
            "attachment_id": "attachment-1",
            "kind": "text_file",
            "original_name": "private.txt",
            "mime_type": "text/plain",
            "storage_path": str(outside),
            "parse_status": "pending",
        },
    )

    assert prepared["parse_status"] == "failed"
    assert "storage_path" not in prepared
    assert "derived_text_path" not in prepared


def test_prepare_runtime_attachment_ignores_untrusted_prepared_text_path(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)
    upload_payload = _mutate(
        service.ingest_attachment,
        session_id="session-1",
        turn_id="turn-1",
        original_name="notes.md",
        content=b"safe source",
        mime_type="text/markdown",
    )
    outside = runtime_paths.base_dir / "private.txt"
    outside.write_text("private content", encoding="utf-8")

    prepared = _mutate(
        service.prepare_runtime_attachment,
        session_id="session-1",
        turn_id="turn-1",
        attachment={
            **upload_payload,
            "parse_status": "parsed",
            "derived_text_path": str(outside),
        },
    )

    expected_path = (
        runtime_paths.chat_derived_dir
        / "session-1"
        / "turn-1"
        / f"{upload_payload['attachment_id']}.txt"
    )
    assert prepared["derived_text_path"] == str(expected_path)
    assert expected_path.read_text(encoding="utf-8") == "safe source"
    assert outside.read_text(encoding="utf-8") == "private content"


def test_prepare_runtime_attachment_rejects_another_attachment_in_same_turn(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)
    first = _mutate(
        service.ingest_attachment,
        session_id="session-1",
        turn_id="turn-1",
        original_name="first.md",
        content=b"first secret",
        mime_type="text/markdown",
    )
    second = _mutate(
        service.ingest_attachment,
        session_id="session-1",
        turn_id="turn-1",
        original_name="second.md",
        content=b"second secret",
        mime_type="text/markdown",
    )

    prepared = _mutate(
        service.prepare_runtime_attachment,
        session_id="session-1",
        turn_id="turn-1",
        attachment={
            **second,
            "storage_path": first["storage_path"],
        },
    )

    assert prepared["parse_status"] == "failed"
    assert "storage_path" not in prepared
    assert "derived_text_path" not in prepared


def test_ingest_attachment_rejects_unsupported_file_type(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)

    with language_context("en"), pytest.raises(ValueError, match="Unsupported attachment type"):
        _mutate(
            service.ingest_attachment,
            session_id="session-1",
            turn_id="turn-1",
            original_name="archive.zip",
            content=b"PK",
            mime_type="application/zip",
        )


def test_ingest_attachment_converts_heic_to_jpeg_preview(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    converter = FakeHeicPreviewConverter()
    service = LocalChatAttachmentIngestionService(
        runtime_paths=runtime_paths,
        heic_preview_converter=converter,
    )

    payload = _mutate(
        service.ingest_attachment,
        session_id="session-1",
        turn_id="turn-1",
        original_name="IMG_3367.HEIC",
        content=b"fake-heic",
        mime_type="image/heic",
    )

    assert converter.calls == [(b"fake-heic", "IMG_3367.HEIC")]
    assert payload["kind"] == "image"
    assert payload["original_name"] == "IMG_3367.jpg"
    assert payload["mime_type"] == "image/jpeg"
    assert payload["source_original_name"] == "IMG_3367.HEIC"
    assert payload["source_original_mime_type"] == "image/heic"
    assert payload["preview_generated"] is True
    assert Path(str(payload["storage_path"])).read_bytes() == b"fake-jpeg-preview"


def test_ingest_local_file_converts_heic_path_to_jpeg_preview(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    converter = FakeHeicPreviewConverter(output=b"local-preview")
    service = LocalChatAttachmentIngestionService(
        runtime_paths=runtime_paths,
        heic_preview_converter=converter,
    )
    source_path = tmp_path / "IMG_3379.heic"
    source_path.write_bytes(b"local-heic")

    payload = _mutate(
        service.ingest_local_file,
        session_id="session-1",
        turn_id="turn-1",
        file_path=str(source_path),
    )

    assert converter.calls == [(b"local-heic", "IMG_3379.heic")]
    assert payload["kind"] == "image"
    assert payload["original_name"] == "IMG_3379.jpg"
    assert payload["mime_type"] == "image/jpeg"
    assert payload["source_path"] == str(source_path)
    assert payload["source_origin"] == "local_file"
    assert payload["source_original_name"] == "IMG_3379.heic"
    assert payload["source_original_mime_type"] == "image/heic"
    assert Path(str(payload["storage_path"])).read_bytes() == b"local-preview"


def test_ingest_attachment_reports_heic_conversion_failure(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(
        runtime_paths=runtime_paths,
        heic_preview_converter=FailingHeicPreviewConverter(),
    )

    with language_context("en"), pytest.raises(ValueError, match="HEIC image conversion failed"):
        _mutate(
            service.ingest_attachment,
            session_id="session-1",
            turn_id="turn-1",
            original_name="IMG_3578.HEIC",
            content=b"fake-heic",
            mime_type="image/heic",
        )


def test_ingest_attachment_rejects_oversized_image(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = LocalChatAttachmentIngestionService(runtime_paths=runtime_paths)

    with language_context("en"), pytest.raises(
        ValueError,
        match="Image attachment exceeds the 20 MB limit",
    ):
        _mutate(
            service.ingest_attachment,
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
        _mutate(
            service.ingest_attachment,
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

    payload = _mutate(
        service.ingest_local_file,
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

    upload_payload = _mutate(
        service.ingest_attachment,
        session_id="session-1",
        turn_id="turn-1",
        original_name="report.pdf",
        content=_build_simple_pdf_bytes("Hello PDF", compressed=True),
        mime_type="application/pdf",
    )

    assert upload_payload["kind"] == "pdf"
    assert upload_payload["parse_status"] == "pending"
    assert "derived_text_path" not in upload_payload

    payload = _mutate(
        service.prepare_runtime_attachment,
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
