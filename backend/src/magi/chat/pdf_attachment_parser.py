"""Local parser for readable PDF chat attachments."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import BinaryIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError


DEFAULT_PDF_ATTACHMENT_MAX_CHARS = 120_000
PDF_PARSER_BACKEND = "pypdf"


def _resolve_pdf_parser_backend_version() -> str:
    try:
        return metadata.version(PDF_PARSER_BACKEND)
    except metadata.PackageNotFoundError:
        return "unknown"


PDF_PARSER_BACKEND_VERSION = _resolve_pdf_parser_backend_version()


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
    """Extract embedded text from readable digital PDFs."""

    def parse_file(
        self,
        file_path: str | Path,
        *,
        max_chars: int = DEFAULT_PDF_ATTACHMENT_MAX_CHARS,
    ) -> ParsedPdfAttachment:
        """Parse one local PDF and return structured extraction output."""

        path = Path(file_path)
        try:
            with path.open("rb") as file:
                return self.parse_stream(file, max_chars=max_chars)
        except OSError:
            return _failed_parse("Unsupported PDF format")

    def parse_stream(
        self,
        file: BinaryIO,
        *,
        max_chars: int = DEFAULT_PDF_ATTACHMENT_MAX_CHARS,
    ) -> ParsedPdfAttachment:
        """Parse a PDF from an already-validated, held file handle."""

        try:
            file.seek(0)
            header = file.read(5)
            file.seek(0)
        except OSError:
            return _failed_parse("Unsupported PDF format")
        if header != b"%PDF-":
            return _failed_parse("Unsupported PDF format")

        try:
            reader = PdfReader(file, strict=False)
        except (OSError, PdfReadError, ValueError):
            return _failed_parse("Unsupported PDF format")

        if reader.is_encrypted:
            try:
                decrypt_result = reader.decrypt("")
            except (PdfReadError, ValueError, NotImplementedError):
                return _failed_parse("Encrypted PDF requires a password")
            if not decrypt_result:
                return _failed_parse("Encrypted PDF requires a password")

        try:
            pages = list(reader.pages)
        except (PdfReadError, ValueError, RuntimeError):
            return _failed_parse("Unable to read PDF pages")

        page_count = len(pages)
        extracted_segments: list[str] = []
        for page in pages:
            try:
                page_text = page.extract_text() or ""
            except (AttributeError, KeyError, PdfReadError, TypeError, ValueError):
                continue
            normalized_page_text = _normalize_extracted_text(page_text)
            if normalized_page_text:
                extracted_segments.append(normalized_page_text)

        normalized_text = "\n\n".join(extracted_segments).strip()
        if not normalized_text:
            return ParsedPdfAttachment(
                text="",
                character_count=0,
                truncated=False,
                excerpt="",
                page_count=page_count,
                extraction_succeeded=False,
                error="No readable text found in PDF",
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


def _failed_parse(error: str, *, page_count: int = 0) -> ParsedPdfAttachment:
    return ParsedPdfAttachment(
        text="",
        character_count=0,
        truncated=False,
        excerpt="",
        page_count=page_count,
        extraction_succeeded=False,
        error=error,
    )


def _normalize_extracted_text(text: str) -> str:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip()
