from __future__ import annotations

import zlib
from pathlib import Path

from magi.chat.pdf_attachment_parser import LocalPdfAttachmentParser


def test_parse_file_extracts_text_from_compressed_pdf_stream(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.pdf"
    file_path.write_bytes(_build_simple_pdf_bytes("Hello PDF", compressed=True))

    parser = LocalPdfAttachmentParser()
    parsed = parser.parse_file(file_path)

    assert parsed.extraction_succeeded is True
    assert parsed.text == "Hello PDF"
    assert parsed.character_count == len("Hello PDF")
    assert parsed.page_count == 1
    assert parsed.truncated is False
    assert parsed.error is None


def test_parse_file_returns_clean_failure_for_invalid_pdf(tmp_path: Path) -> None:
    file_path = tmp_path / "broken.pdf"
    file_path.write_bytes(b"not a pdf")

    parser = LocalPdfAttachmentParser()
    parsed = parser.parse_file(file_path)

    assert parsed.extraction_succeeded is False
    assert parsed.text == ""
    assert parsed.character_count == 0
    assert parsed.page_count == 0
    assert parsed.error == "Unsupported PDF format"


def test_parse_file_truncates_extracted_pdf_text(tmp_path: Path) -> None:
    file_path = tmp_path / "long.pdf"
    file_path.write_bytes(_build_simple_pdf_bytes("abcdefghijklmnopqrstuvwxyz"))

    parser = LocalPdfAttachmentParser()
    parsed = parser.parse_file(file_path, max_chars=10)

    assert parsed.extraction_succeeded is True
    assert parsed.text == "abcdefghij"
    assert parsed.character_count == 26
    assert parsed.truncated is True


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
