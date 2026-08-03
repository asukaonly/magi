"""Deterministic authorship spans for imported Markdown documents."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

HISTORY_DOCUMENT_EVENT_TYPE = "history_import.document"

_BLOCKQUOTE_RE = re.compile(r"^>")
_FENCE_OPEN_RE = re.compile(r"^(?P<fence>`{3,}|~{3,})(?P<rest>[^\r\n]*)")
_FENCE_CLOSE_RE = re.compile(r"^(?P<fence>[`~]+)[ \t]*$")
_ATX_HEADING_RE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+|$)")
_LIST_ITEM_RE = re.compile(r"^ {0,3}(?:[-+*]|\d{1,9}[.)])(?:[ \t]+|$)")
_THEMATIC_BREAK_RE = re.compile(r"^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")


@dataclass(frozen=True, slots=True)
class _CanonicalText:
    text: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]


def find_history_document_author_occurrence(
    content: str,
    evidence_text: str,
) -> tuple[int, int] | None:
    """Return the first canonical evidence occurrence in ordinary author prose."""

    needle = _canonical_text(evidence_text)
    if not needle:
        return None
    source = str(content or "")
    for start, end in _author_text_ranges(source):
        canonical = _canonical_text_with_offsets(source[start:end], base_offset=start)
        match_start = canonical.text.find(needle)
        if match_start < 0:
            continue
        match_end = match_start + len(needle)
        return canonical.starts[match_start], canonical.ends[match_end - 1]
    return None


def _author_text_ranges(content: str) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    offset = 0
    fence_char: str | None = None
    fence_length = 0
    lazy_blockquote_paragraph = False

    for line in content.splitlines(keepends=True):
        line_start = offset
        line_end = offset + len(line)
        offset = line_end
        line_body = line.rstrip("\r\n")

        if fence_char is not None:
            if _is_closing_fence(line_body, fence_char, fence_length):
                fence_char = None
                fence_length = 0
            lazy_blockquote_paragraph = False
            continue

        structural_line = _strip_markdown_container_prefixes(line_body)
        quote_match = _BLOCKQUOTE_RE.match(structural_line)
        if quote_match is not None:
            quote_body = structural_line[quote_match.end() :].lstrip(" \t")
            lazy_blockquote_paragraph = bool(quote_body)
            continue

        if lazy_blockquote_paragraph:
            if not line_body.strip():
                lazy_blockquote_paragraph = False
                _append_range(ranges, line_start, line_end)
                continue
            if not _starts_new_markdown_block(line_body):
                continue
            lazy_blockquote_paragraph = False

        opening_fence = _opening_fence(line_body)
        if opening_fence is not None:
            fence_char, fence_length = opening_fence
            continue

        _append_range(ranges, line_start, line_end)

    return tuple(ranges)


def _append_range(ranges: list[tuple[int, int]], start: int, end: int) -> None:
    if end <= start:
        return
    if ranges and ranges[-1][1] == start:
        ranges[-1] = (ranges[-1][0], end)
    else:
        ranges.append((start, end))


def _strip_markdown_container_prefixes(line: str) -> str:
    index = 0
    while True:
        while index < len(line) and line[index] in " \t":
            index += 1
        marker_end = _list_marker_end(line, index)
        if marker_end is None:
            return line[index:]
        if marker_end < len(line) and line[marker_end] not in " \t":
            return line[index:]
        index = marker_end


def _list_marker_end(line: str, start: int) -> int | None:
    if start >= len(line):
        return None
    if line[start] in "-+*":
        return start + 1
    end = start
    while end < len(line) and line[end].isdigit() and end - start < 9:
        end += 1
    if end == start or end >= len(line) or line[end] not in ".)":
        return None
    return end + 1


def _opening_fence(line: str) -> tuple[str, int] | None:
    match = _FENCE_OPEN_RE.match(_strip_markdown_container_prefixes(line))
    if match is None:
        return None
    fence = match.group("fence")
    if fence.startswith("`") and "`" in match.group("rest"):
        return None
    return fence[0], len(fence)


def _is_closing_fence(line: str, fence_char: str, fence_length: int) -> bool:
    match = _FENCE_CLOSE_RE.fullmatch(_strip_markdown_container_prefixes(line))
    if match is None:
        return False
    fence = match.group("fence")
    return all(character == fence_char for character in fence) and len(fence) >= fence_length


def _starts_new_markdown_block(line: str) -> bool:
    stripped = line.rstrip(" \t")
    return bool(
        _opening_fence(line)
        or _ATX_HEADING_RE.match(line)
        or _LIST_ITEM_RE.match(line)
        or _THEMATIC_BREAK_RE.fullmatch(stripped)
        or line.startswith("    ")
    )


def _canonical_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _canonical_text_with_offsets(value: str, *, base_offset: int) -> _CanonicalText:
    output: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    pending_space: tuple[int, int] | None = None
    index = 0

    while index < len(value):
        cluster_start = index
        index += 1
        while index < len(value) and unicodedata.category(value[index]).startswith("M"):
            index += 1
        cluster_end = index
        transformed = unicodedata.normalize(
            "NFKC",
            value[cluster_start:cluster_end],
        ).casefold()
        raw_start = base_offset + cluster_start
        raw_end = base_offset + cluster_end
        for character in transformed:
            if character.isspace():
                if pending_space is None:
                    pending_space = (raw_start, raw_end)
                else:
                    pending_space = (pending_space[0], raw_end)
                continue
            if pending_space is not None and output:
                output.append(" ")
                starts.append(pending_space[0])
                ends.append(pending_space[1])
            pending_space = None
            output.append(character)
            starts.append(raw_start)
            ends.append(raw_end)

    return _CanonicalText(
        text="".join(output),
        starts=tuple(starts),
        ends=tuple(ends),
    )


__all__ = [
    "HISTORY_DOCUMENT_EVENT_TYPE",
    "find_history_document_author_occurrence",
]
