from __future__ import annotations

from pathlib import Path

from magi.chat.pdf_attachment_parser import LocalPdfAttachmentParser


def test_parse_file_extracts_text_from_simple_pdf(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.pdf"
    file_path.write_bytes(_build_simple_pdf_bytes("Hello PDF"))

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


def _build_simple_pdf_bytes(text: str) -> bytes:
    content_stream = f"BT\n/F1 12 Tf\n72 72 Td\n({text}) Tj\nET".encode("latin-1")
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n"
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>\n"
            b"endobj\n"
        ),
        b"4 0 obj\n<< /Length " + str(len(content_stream)).encode("ascii") + b" >>\nstream\n" + content_stream + b"\nendstream\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    body = b"".join(objects)
    return b"%PDF-1.4\n" + body + b"%%EOF\n"
