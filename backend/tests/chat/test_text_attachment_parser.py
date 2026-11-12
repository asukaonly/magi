from __future__ import annotations

from pathlib import Path

from magi.chat.text_attachment_parser import LocalTextAttachmentParser


def test_parse_file_reads_utf8_text_without_truncation(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.md"
    file_path.write_text("hello world", encoding="utf-8")

    parser = LocalTextAttachmentParser()
    parsed = parser.parse_file(file_path)

    assert parsed.text == "hello world"
    assert parsed.encoding == "utf-8"
    assert parsed.character_count == 11
    assert parsed.truncated is False
    assert parsed.excerpt == "hello world"


def test_parse_file_falls_back_to_latin_1_when_utf8_decode_fails(tmp_path: Path) -> None:
    file_path = tmp_path / "latin1.txt"
    file_path.write_bytes("café".encode("latin-1"))

    parser = LocalTextAttachmentParser()
    parsed = parser.parse_file(file_path)

    assert parsed.text == "café"
    assert parsed.encoding == "latin-1"
    assert parsed.truncated is False


def test_parse_file_preserves_long_text_for_paged_reads(tmp_path: Path) -> None:
    file_path = tmp_path / "long.txt"
    text = "A" * 120_000 + "Tail"
    file_path.write_text(text, encoding="utf-8")

    parser = LocalTextAttachmentParser()
    parsed = parser.parse_file(file_path)

    assert parsed.text == text
    assert parsed.character_count == len(text)
    assert parsed.truncated is False
    assert parsed.excerpt == text[:200]
