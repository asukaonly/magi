"""Deterministic authorship spans for imported Markdown documents."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

HISTORY_DOCUMENT_EVENT_TYPE = "history_import.document"

_BLOCKQUOTE_RE = re.compile(r"^>")
_FENCE_OPEN_RE = re.compile(r"^(?P<fence>`{3,}|~{3,})(?P<rest>[^\r\n]*)")
_FENCE_CLOSE_RE = re.compile(r"^(?P<fence>[`~]+)[ \t]*$")
_ATX_HEADING_RE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+|$)")
_LIST_ITEM_RE = re.compile(r"^ {0,3}(?:[-+*]|\d{1,9}[.)])(?:[ \t]+|$)")
_THEMATIC_BREAK_RE = re.compile(r"^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")
_EMAIL_HEADER_RE = re.compile(
    r"^(?P<header>from|sent|to|cc|bcc|subject|reply-to|date|发件人|发送时间|收件人|抄送|主题)"
    r"[ \t]*[:：]",
    re.IGNORECASE,
)
_HTML_INLINE_OPEN_RE = re.compile(r"<\s*(?P<tag>blockquote|pre|code)\b[^>]*>", re.IGNORECASE)
_LEADING_TIMESTAMP_RE = re.compile(r"^\[[0-9][0-9./: +\-T年月日时分秒]{1,38}\][ \t]*")
_TRAILING_TIMESTAMP_SPEAKER_RE = re.compile(
    r"^(?P<label>.+?)[ \t]*(?:"
    r"\((?P<paren>[0-9][0-9./: +\-T年月日时分秒]{1,38})\)|"
    r"\[(?P<bracket>[0-9][0-9./: +\-T年月日时分秒]{1,38})\]"
    r")[ \t]*[:：][ \t]*(?P<message>\S.*)$"
)
_FRONTMATTER_FIELD_RE = re.compile(
    r"^(?:[A-Za-z_][\w.-]*|[\u3400-\u9fff][^:：=]{0,40})[ \t]*(?:[:：]|=)" r"(?:[ \t]+.*)?$"
)
# These are explicit transcript protocol roles, not guessed speaker names.
_TRANSCRIPT_ROLES = frozenset({"assistant", "user", "system", "developer", "tool", "助手", "用户", "系统"})


class HistoryDocumentSpanKind(str, Enum):
    """Host-owned attribution class for an imported document span."""

    AUTHOR_PROSE = "author_prose"
    BLOCKQUOTE = "blockquote"
    FENCED_CODE = "fenced_code"
    INDENTED_CODE = "indented_code"
    INLINE_CODE = "inline_code"
    FRONTMATTER = "frontmatter"
    PASTED_CONTENT = "pasted_content"


class _PastedDialogueKind(str, Enum):
    NONE = "none"
    PARAGRAPH = "paragraph"


@dataclass(frozen=True, slots=True)
class HistoryDocumentSpan:
    """One exact source range with a deterministic attribution class."""

    start: int
    end: int
    kind: HistoryDocumentSpanKind


@dataclass(frozen=True, slots=True)
class _CanonicalText:
    text: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]


@dataclass(slots=True)
class _InlineScanState:
    code_fence_length: int = 0
    html_closer: str | None = None


@dataclass(frozen=True, slots=True)
class _InlineDelimiter:
    start: int
    opener_end: int
    kind: str
    closer: str = ""
    fence_length: int = 0


def find_history_document_author_occurrence(
    content: str,
    evidence_text: str,
) -> tuple[int, int] | None:
    """Return the first canonical evidence occurrence in ordinary author prose."""

    needle = _canonical_text(evidence_text)
    if not needle:
        return None
    source = str(content or "")
    for span in classify_history_document_spans(source):
        if span.kind is not HistoryDocumentSpanKind.AUTHOR_PROSE:
            continue
        canonical = _canonical_text_with_offsets(
            source[span.start : span.end],
            base_offset=span.start,
        )
        match_start = canonical.text.find(needle)
        if match_start < 0:
            continue
        match_end = match_start + len(needle)
        return canonical.starts[match_start], canonical.ends[match_end - 1]
    return None


def classify_history_document_spans(content: str) -> tuple[HistoryDocumentSpan, ...]:
    """Classify source spans without trusting document-level authorship wholesale."""

    spans: list[HistoryDocumentSpan] = []
    offset = 0
    fence_char: str | None = None
    fence_length = 0
    lazy_blockquote_paragraph = False
    lazy_pasted_paragraph = False
    forwarded_content = False
    inline_state = _InlineScanState()

    lines = content.splitlines(keepends=True)
    frontmatter_end_line = _frontmatter_end_line(lines)
    for line_index, line in enumerate(lines):
        line_start = offset
        line_end = offset + len(line)
        offset = line_end
        line_body = line.rstrip("\r\n")

        if frontmatter_end_line is not None and line_index <= frontmatter_end_line:
            _append_span(
                spans,
                line_start,
                line_end,
                HistoryDocumentSpanKind.FRONTMATTER,
            )
            continue

        if forwarded_content:
            _append_span(
                spans,
                line_start,
                line_end,
                HistoryDocumentSpanKind.PASTED_CONTENT,
            )
            continue

        if fence_char is not None:
            _append_span(
                spans,
                line_start,
                line_end,
                HistoryDocumentSpanKind.FENCED_CODE,
            )
            if _is_closing_fence(line_body, fence_char, fence_length):
                fence_char = None
                fence_length = 0
            lazy_blockquote_paragraph = False
            lazy_pasted_paragraph = False
            continue

        structural_line = _strip_markdown_container_prefixes(line_body)
        quote_match = _BLOCKQUOTE_RE.match(structural_line)
        if quote_match is not None:
            quote_body = structural_line[quote_match.end() :].lstrip(" \t")
            lazy_blockquote_paragraph = bool(quote_body)
            lazy_pasted_paragraph = False
            _append_span(
                spans,
                line_start,
                line_end,
                HistoryDocumentSpanKind.BLOCKQUOTE,
            )
            continue

        if lazy_blockquote_paragraph:
            if not line_body.strip():
                lazy_blockquote_paragraph = False
                _append_span(
                    spans,
                    line_start,
                    line_end,
                    HistoryDocumentSpanKind.AUTHOR_PROSE,
                )
                continue
            if not _starts_new_markdown_block(line_body):
                _append_span(
                    spans,
                    line_start,
                    line_end,
                    HistoryDocumentSpanKind.BLOCKQUOTE,
                )
                continue
            lazy_blockquote_paragraph = False

        opening_fence = _opening_fence(line_body)
        if opening_fence is not None:
            fence_char, fence_length = opening_fence
            inline_state = _InlineScanState()
            _append_span(
                spans,
                line_start,
                line_end,
                HistoryDocumentSpanKind.FENCED_CODE,
            )
            continue

        if _is_indented_code(line_body):
            inline_state = _InlineScanState()
            _append_span(
                spans,
                line_start,
                line_end,
                HistoryDocumentSpanKind.INDENTED_CODE,
            )
            continue

        if _starts_email_header_block(lines, line_index):
            forwarded_content = True
            inline_state = _InlineScanState()
            _append_span(
                spans,
                line_start,
                line_end,
                HistoryDocumentSpanKind.PASTED_CONTENT,
            )
            continue

        if lazy_pasted_paragraph:
            if not line_body.strip():
                lazy_pasted_paragraph = False
                _append_span(
                    spans,
                    line_start,
                    line_end,
                    HistoryDocumentSpanKind.AUTHOR_PROSE,
                )
                continue
            if not _starts_new_markdown_block(line_body):
                _append_span(
                    spans,
                    line_start,
                    line_end,
                    HistoryDocumentSpanKind.PASTED_CONTENT,
                )
                continue
            lazy_pasted_paragraph = False

        pasted_dialogue_kind = _classify_pasted_dialogue_line(structural_line)
        if pasted_dialogue_kind is not _PastedDialogueKind.NONE:
            lazy_pasted_paragraph = pasted_dialogue_kind is _PastedDialogueKind.PARAGRAPH
            inline_state = _InlineScanState()
            _append_span(
                spans,
                line_start,
                line_end,
                HistoryDocumentSpanKind.PASTED_CONTENT,
            )
            continue

        _append_inline_spans(
            spans,
            line,
            base_offset=line_start,
            state=inline_state,
        )

    if offset < len(content):
        _append_inline_spans(
            spans,
            content[offset:],
            base_offset=offset,
            state=inline_state,
        )
    return tuple(spans)


def _append_span(
    spans: list[HistoryDocumentSpan],
    start: int,
    end: int,
    kind: HistoryDocumentSpanKind,
) -> None:
    if end <= start:
        return
    if spans and spans[-1].end == start and spans[-1].kind is kind:
        spans[-1] = HistoryDocumentSpan(start=spans[-1].start, end=end, kind=kind)
    else:
        spans.append(HistoryDocumentSpan(start=start, end=end, kind=kind))


def _is_indented_code(line: str) -> bool:
    if line.startswith("\t") or line.startswith("    "):
        return True
    index = 0
    while index < len(line):
        marker_start = index
        while index < len(line) and line[index] == " ":
            index += 1
        if index - marker_start > 3:
            return True
        marker_end = _list_marker_end(line, index)
        if marker_end is None:
            return False
        whitespace_end = marker_end
        while whitespace_end < len(line) and line[whitespace_end] in " \t":
            whitespace_end += 1
        indentation = line[marker_end:whitespace_end]
        if "\t" in indentation or len(indentation) >= 4:
            return True
        index = whitespace_end
    return False


def _frontmatter_end_line(lines: list[str]) -> int | None:
    if not lines:
        return None
    delimiter = lines[0].rstrip("\r\n").removeprefix("\ufeff").strip()
    if delimiter not in {"---", "+++"}:
        return None
    has_metadata_field = False
    for index, line in enumerate(lines[1:], start=1):
        text = line.rstrip("\r\n").strip()
        if text == delimiter or (delimiter == "---" and text == "..."):
            return index if has_metadata_field else None
        if _FRONTMATTER_FIELD_RE.match(text):
            has_metadata_field = True
    return None


def _starts_email_header_block(lines: list[str], start: int) -> bool:
    first = _EMAIL_HEADER_RE.match(
        _strip_markdown_container_prefixes(lines[start].rstrip("\r\n")).strip()
    )
    if first is None:
        return False
    headers: set[str] = set()
    for line in lines[start : start + 8]:
        body = _strip_markdown_container_prefixes(line.rstrip("\r\n")).strip()
        if not body:
            break
        match = _EMAIL_HEADER_RE.match(body)
        if match is not None:
            headers.add(match.group("header").casefold())
    from_headers = {"from", "发件人"}
    supporting_headers = {
        "sent",
        "to",
        "cc",
        "bcc",
        "subject",
        "date",
        "发送时间",
        "收件人",
        "抄送",
        "主题",
    }
    return bool(headers & from_headers) and bool(headers & supporting_headers)


def _classify_pasted_dialogue_line(line: str) -> _PastedDialogueKind:
    """Recognize explicit transcript role syntax without interpreting prose."""
    text = _LEADING_TIMESTAMP_RE.sub("", line.strip(), count=1)
    trailing_timestamp = _TRAILING_TIMESTAMP_SPEAKER_RE.match(text)
    if trailing_timestamp is not None:
        label = trailing_timestamp.group("label")
    else:
        colon_positions = [position for marker in (":", "：") if 0 < (position := text.find(marker))]
        if not colon_positions:
            return _PastedDialogueKind.NONE
        colon = min(colon_positions)
        label = text[:colon]
        if not text[colon + 1 :].strip(" *_"):
            return _PastedDialogueKind.NONE
    if label.strip(" *_`~").casefold() in _TRANSCRIPT_ROLES:
        return _PastedDialogueKind.PARAGRAPH
    return _PastedDialogueKind.NONE


def _append_inline_spans(
    spans: list[HistoryDocumentSpan],
    line: str,
    *,
    base_offset: int,
    state: _InlineScanState,
) -> None:
    index = 0
    while index < len(line):
        if state.code_fence_length:
            closing = _find_backtick_run(line, index, state.code_fence_length)
            end = len(line) if closing is None else closing + state.code_fence_length
            _append_span(
                spans,
                base_offset + index,
                base_offset + end,
                HistoryDocumentSpanKind.INLINE_CODE,
            )
            index = end
            if closing is None:
                return
            state.code_fence_length = 0
            continue

        if state.html_closer is not None:
            closing = _find_case_insensitive(line, state.html_closer, index)
            end = len(line) if closing is None else closing + len(state.html_closer)
            _append_span(
                spans,
                base_offset + index,
                base_offset + end,
                HistoryDocumentSpanKind.PASTED_CONTENT,
            )
            index = end
            if closing is None:
                return
            state.html_closer = None
            continue

        delimiter = _next_inline_delimiter(line, index)
        if delimiter is None:
            _append_span(
                spans,
                base_offset + index,
                base_offset + len(line),
                HistoryDocumentSpanKind.AUTHOR_PROSE,
            )
            return
        _append_span(
            spans,
            base_offset + index,
            base_offset + delimiter.start,
            HistoryDocumentSpanKind.AUTHOR_PROSE,
        )
        if delimiter.kind == "code":
            fence_length = delimiter.fence_length
            closing = _find_backtick_run(
                line,
                delimiter.opener_end,
                fence_length,
            )
            end = len(line) if closing is None else closing + fence_length
            _append_span(
                spans,
                base_offset + delimiter.start,
                base_offset + end,
                HistoryDocumentSpanKind.INLINE_CODE,
            )
            if closing is None:
                state.code_fence_length = fence_length
                return
            index = end
            continue

        if delimiter.kind == "html":
            closing = _find_case_insensitive(line, delimiter.closer, delimiter.opener_end)
            end = len(line) if closing is None else closing + len(delimiter.closer)
            _append_span(
                spans,
                base_offset + delimiter.start,
                base_offset + end,
                HistoryDocumentSpanKind.PASTED_CONTENT,
            )
            if closing is None:
                state.html_closer = delimiter.closer
                return
            index = end
            continue



def _next_inline_delimiter(line: str, start: int) -> _InlineDelimiter | None:
    candidates = [
        item
        for item in (
            _next_unescaped_backtick_run(line, start),
            _next_html_delimiter(line, start),
        )
        if item is not None
    ]
    return min(candidates, key=lambda item: item.start) if candidates else None


def _next_unescaped_backtick_run(
    line: str,
    start: int,
) -> _InlineDelimiter | None:
    index = line.find("`", start)
    while index >= 0:
        preceding_slashes = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            preceding_slashes += 1
            cursor -= 1
        run_end = index
        while run_end < len(line) and line[run_end] == "`":
            run_end += 1
        if preceding_slashes % 2 == 0:
            return _InlineDelimiter(
                start=index,
                opener_end=run_end,
                kind="code",
                fence_length=run_end - index,
            )
        index = line.find("`", run_end)
    return None


def _find_backtick_run(line: str, start: int, length: int) -> int | None:
    index = line.find("`" * length, start)
    while index >= 0:
        before_is_tick = index > 0 and line[index - 1] == "`"
        after_index = index + length
        after_is_tick = after_index < len(line) and line[after_index] == "`"
        if not before_is_tick and not after_is_tick:
            return index
        index = line.find("`" * length, index + length)
    return None


def _next_html_delimiter(line: str, start: int) -> _InlineDelimiter | None:
    candidates: list[_InlineDelimiter] = []
    comment_start = line.find("<!--", start)
    if comment_start >= 0:
        candidates.append(
            _InlineDelimiter(
                start=comment_start,
                opener_end=comment_start + len("<!--"),
                kind="html",
                closer="-->",
            )
        )
    html_match = _HTML_INLINE_OPEN_RE.search(line, start)
    if html_match is not None:
        tag = html_match.group("tag").casefold()
        candidates.append(
            _InlineDelimiter(
                start=html_match.start(),
                opener_end=html_match.end(),
                kind="html",
                closer=f"</{tag}>",
            )
        )
    return min(candidates, key=lambda item: item.start) if candidates else None


def _find_case_insensitive(line: str, needle: str, start: int) -> int | None:
    position = line.casefold().find(needle.casefold(), start)
    return position if position >= 0 else None


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
    "HistoryDocumentSpan",
    "HistoryDocumentSpanKind",
    "classify_history_document_spans",
    "find_history_document_author_occurrence",
]
