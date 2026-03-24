"""Local parser for readable PDF chat attachments without OCR fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_PDF_ATTACHMENT_MAX_CHARS = 120_000
_STREAM_PATTERN = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
_PAGE_PATTERN = re.compile(rb"/Type\s*/Page\b")
_TEXT_BLOCK_PATTERN = re.compile(r"BT(.*?)ET", re.DOTALL)
_TEXT_STRING_PATTERN = re.compile(r"\((?:\\.|[^\\)])*\)")


@dataclass(slots=True)
class ParsedPdfAttachment:
    """Structured output for locally parsed PDF attachments."""

    text: str
    character_count: int
    truncated: bool
    excerpt: str
    page_count: int
    extraction_succeeded: bool
    error: str | None = None


class LocalPdfAttachmentParser:
    """Extract text from simple readable PDFs without external dependencies."""

    def parse_file(
        self,
        file_path: str | Path,
        *,
        max_chars: int = DEFAULT_PDF_ATTACHMENT_MAX_CHARS,
    ) -> ParsedPdfAttachment:
        """Parse one local PDF and return structured extraction output."""

        content_bytes = Path(file_path).read_bytes()
        if not content_bytes.startswith(b"%PDF-"):
            return ParsedPdfAttachment(
                text="",
                character_count=0,
                truncated=False,
                excerpt="",
                page_count=0,
                extraction_succeeded=False,
                error="Unsupported PDF format",
            )

        page_count = len(_PAGE_PATTERN.findall(content_bytes))
        extracted_segments: list[str] = []
        had_unsupported_stream = False
        for match in _STREAM_PATTERN.finditer(content_bytes):
            stream_bytes = match.group(1)
            header_window = content_bytes[max(0, match.start() - 200):match.start()]
            if b"/FlateDecode" in header_window:
                had_unsupported_stream = True
                continue
            extracted_segments.extend(self._extract_stream_text(stream_bytes))

        normalized_text = "\n".join(segment for segment in extracted_segments if segment).strip()
        if not normalized_text:
            return ParsedPdfAttachment(
                text="",
                character_count=0,
                truncated=False,
                excerpt="",
                page_count=page_count,
                extraction_succeeded=False,
                error=(
                    "PDF text extraction requires an uncompressed readable PDF stream"
                    if had_unsupported_stream
                    else "No readable text found in PDF"
                ),
            )

        character_count = len(normalized_text)
        safe_max_chars = max(1, int(max_chars))
        truncated = character_count > safe_max_chars
        visible_text = normalized_text[:safe_max_chars] if truncated else normalized_text
        return ParsedPdfAttachment(
            text=visible_text,
            character_count=character_count,
            truncated=truncated,
            excerpt=visible_text[: min(len(visible_text), 200)],
            page_count=page_count,
            extraction_succeeded=True,
            error=None,
        )

    def _extract_stream_text(self, stream_bytes: bytes) -> list[str]:
        stream_text = stream_bytes.decode("latin-1", errors="ignore")
        segments: list[str] = []
        for text_block in _TEXT_BLOCK_PATTERN.findall(stream_text):
            literals = _TEXT_STRING_PATTERN.findall(text_block)
            if not literals:
                continue
            segments.append("".join(self._decode_pdf_literal(item) for item in literals).strip())
        return [segment for segment in segments if segment]

    @staticmethod
    def _decode_pdf_literal(literal: str) -> str:
        inner = literal[1:-1]
        inner = inner.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
        return re.sub(
            r"\\([0-7]{1,3})",
            lambda match: chr(int(match.group(1), 8)),
            inner,
        )
