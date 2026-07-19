"""Local parser for text-like chat attachments."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_TEXT_ATTACHMENT_MAX_CHARS = 120_000
_UTF8_ENCODING_CANDIDATES = ("utf-8", "utf-8-sig")
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


@dataclass(slots=True)
class ParsedTextAttachment:
    """Structured output for locally parsed text attachments."""

    text: str
    encoding: str
    character_count: int
    truncated: bool
    excerpt: str


class LocalTextAttachmentParser:
    """Parse local text-like files with lightweight encoding fallback."""

    def parse_file(
        self,
        file_path: str | Path,
        *,
        max_chars: int = DEFAULT_TEXT_ATTACHMENT_MAX_CHARS,
    ) -> ParsedTextAttachment:
        """Load and normalize one local text-like file."""

        return self.parse_bytes(
            Path(file_path).read_bytes(),
            max_chars=max_chars,
        )

    def parse_bytes(
        self,
        content_bytes: bytes,
        *,
        max_chars: int = DEFAULT_TEXT_ATTACHMENT_MAX_CHARS,
    ) -> ParsedTextAttachment:
        """Normalize text from bytes already opened by the owning boundary."""

        text, encoding = self._decode_bytes(content_bytes)
        character_count = len(text)
        safe_max_chars = max(1, int(max_chars))
        truncated = character_count > safe_max_chars
        visible_text = text[:safe_max_chars] if truncated else text
        return ParsedTextAttachment(
            text=visible_text,
            encoding=encoding,
            character_count=character_count,
            truncated=truncated,
            excerpt=visible_text[: min(len(visible_text), 200)],
        )

    @staticmethod
    def _decode_bytes(content_bytes: bytes) -> tuple[str, str]:
        last_error: UnicodeDecodeError | None = None
        for encoding in _UTF8_ENCODING_CANDIDATES:
            try:
                return content_bytes.decode(encoding), encoding
            except UnicodeDecodeError as exc:
                last_error = exc
        if content_bytes.startswith(_UTF16_BOMS):
            try:
                return content_bytes.decode("utf-16"), "utf-16"
            except UnicodeDecodeError as exc:
                last_error = exc
        try:
            return content_bytes.decode("latin-1"), "latin-1"
        except UnicodeDecodeError as exc:
            last_error = exc
        if last_error is not None:
            raise last_error
        return "", "utf-8"
