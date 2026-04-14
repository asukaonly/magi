"""Markdown → Telegram MarkdownV2 formatter."""

from __future__ import annotations

import re

# Characters that must be escaped in Telegram MarkdownV2 outside code blocks.
_ESCAPE_CHARS = r"_*[]()~`>#+=|{}.!-"
_ESCAPE_RE = re.compile(r"([" + re.escape(_ESCAPE_CHARS) + r"])")

# Match fenced code blocks (``` ... ```) so we can protect them.
_CODE_BLOCK_RE = re.compile(r"(```[\s\S]*?```)", re.MULTILINE)

# Match inline code (` ... `).
_INLINE_CODE_RE = re.compile(r"(`[^`]+`)")


def telegram_format(text: str, max_length: int = 4096) -> str:
    """Convert standard Markdown to Telegram MarkdownV2 and truncate."""
    if not text:
        return text

    result = _convert_markdown_v2(text)

    if len(result) > max_length:
        result = result[: max_length - 3] + "..."
    return result


def _convert_markdown_v2(text: str) -> str:
    """Best-effort Markdown → MarkdownV2 conversion.

    Strategy: split into code vs. non-code segments, only escape the
    non-code segments.  Code blocks are passed through untouched.
    """
    segments: list[str] = []
    last_end = 0

    for match in _CODE_BLOCK_RE.finditer(text):
        start, end = match.span()
        if start > last_end:
            segments.append(_escape_non_code(text[last_end:start]))
        segments.append(match.group(0))
        last_end = end

    if last_end < len(text):
        segments.append(_escape_non_code(text[last_end:]))

    return "".join(segments)


def _escape_non_code(text: str) -> str:
    """Escape MarkdownV2 special characters outside inline code spans."""
    parts: list[str] = []
    last_end = 0

    for match in _INLINE_CODE_RE.finditer(text):
        start, end = match.span()
        if start > last_end:
            parts.append(_escape_chars(text[last_end:start]))
        parts.append(match.group(0))
        last_end = end

    if last_end < len(text):
        parts.append(_escape_chars(text[last_end:]))

    return "".join(parts)


def _escape_chars(text: str) -> str:
    """Escape all MarkdownV2 special characters in plain text."""
    return _ESCAPE_RE.sub(r"\\\1", text)
