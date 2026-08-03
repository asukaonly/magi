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
_FORWARDED_MARKER_RE = re.compile(
    r"^(?:[-_]{2,}[ \t]*)?(?:begin[ \t]+)?(?:forwarded|original)[ \t]+"
    r"(?:message|email)(?:[ \t]*[-_]{2,})?[ \t]*:?$",
    re.IGNORECASE,
)
_FORWARDED_MARKER_ZH_RE = re.compile(r"^(?:[-_]{2,}[ \t]*)?(?:转发|原始)(?:邮件|消息)")
_EMAIL_HEADER_RE = re.compile(
    r"^(?P<header>from|sent|to|cc|bcc|subject|reply-to|date|发件人|发送时间|收件人|抄送|主题)"
    r"[ \t]*[:：]",
    re.IGNORECASE,
)
_SPEAKER_DASH_RE = re.compile(r"^.{1,48}?[ \t]+(?:—|–|-)[ \t]+\S")
_HTML_INLINE_OPEN_RE = re.compile(r"<\s*(?P<tag>blockquote|pre|code)\b[^>]*>", re.IGNORECASE)
_REPORTING_VERB_TAIL_RE = re.compile(
    r"(?:\b(?:said|wrote|asked|replied|noted|mentioned|told[ \t]+me)\b|"
    r"(?:说|写道|问道|回答|表示|提到))[ \t]*[,，:：]?[ \t]*$",
    re.IGNORECASE,
)
_SELF_REPORT_TAIL_RE = re.compile(
    r"(?:\bI[ \t]+(?:said|wrote|asked|replied|noted|mentioned)\b|"
    r"我(?:说|写道|问|回答|表示|提到))[ \t]*[,，:：]?[ \t]*$",
    re.IGNORECASE,
)
_ATTRIBUTION_PREFIX_TAIL_RE = re.compile(
    r"(?:\b(?:according[ \t]+to|quote[ \t]+from)\b.+|"
    r".+(?:的原话|原文|转述)(?:是)?)[ \t]*[,，:：]?[ \t]*$",
    re.IGNORECASE,
)
_ATTRIBUTION_LEAD_RE = re.compile(
    r"^(?:on\b.+?,[ \t]*)?.+?\b(?:said|wrote|asked|replied|noted|mentioned)" r"[ \t]*[:：][ \t]*$",
    re.IGNORECASE,
)
_ATTRIBUTION_LEAD_ZH_RE = re.compile(
    r"^.+?(?:说|写道|问道|回答|表示|提到|的原话(?:是)?)[ \t]*[:：][ \t]*$"
)
_SELF_ATTRIBUTION_LEAD_RE = re.compile(
    r"^(?:I[ \t]+(?:said|wrote|asked|replied|noted|mentioned)|"
    r"我(?:说|写道|问|回答|表示|提到))[ \t]*[:：][ \t]*$",
    re.IGNORECASE,
)
_POST_ATTRIBUTION_RE = re.compile(
    r"^[ \t]*(?:—|–|-)[ \t]+(?:[\w@][\w@.'’-]*[ \t]*){1,6}[.!。]?[ \t]*$",
    re.UNICODE,
)
_PERSON_TITLE_RE = re.compile(
    r"^(?:dr|prof|professor|mr|mrs|ms|miss|sir|dame)[.][ \t]+\S",
    re.IGNORECASE,
)
_CALLOUT_LABELS = frozenset(
    {
        "context",
        "decision",
        "example",
        "goal",
        "my view",
        "note",
        "preference",
        "python",
        "subject",
        "summary",
        "tip",
        "title",
        "todo",
        "warning",
        "主题",
        "工作",
        "偏好",
        "我的偏好",
        "我的观点",
        "备注",
        "总结",
        "提示",
        "标题",
        "注意",
        "目标",
        "示例",
        "说明",
        "观点",
    }
)
_SPEAKER_ROLE_LABELS = frozenset(
    {
        "ai",
        "assistant",
        "bot",
        "human",
        "interviewer",
        "interviewee",
        "participant",
        "speaker",
        "system",
        "user",
        "助手",
        "发言人",
        "对方",
        "用户",
        "系统",
    }
)


class HistoryDocumentSpanKind(str, Enum):
    """Host-owned attribution class for an imported document span."""

    AUTHOR_PROSE = "author_prose"
    BLOCKQUOTE = "blockquote"
    FENCED_CODE = "fenced_code"
    INDENTED_CODE = "indented_code"
    INLINE_CODE = "inline_code"
    QUOTED_TEXT = "quoted_text"
    FRONTMATTER = "frontmatter"
    PASTED_CONTENT = "pasted_content"


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
    quote_closer: str | None = None
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
    frontmatter_delimiter: str | None = None
    first_line = True
    inline_state = _InlineScanState()

    lines = content.splitlines(keepends=True)
    for line_index, line in enumerate(lines):
        line_start = offset
        line_end = offset + len(line)
        offset = line_end
        line_body = line.rstrip("\r\n")

        if first_line:
            first_line = False
            first_body = line_body.removeprefix("\ufeff").strip()
            if first_body in {"---", "+++"}:
                frontmatter_delimiter = first_body
                _append_span(
                    spans,
                    line_start,
                    line_end,
                    HistoryDocumentSpanKind.FRONTMATTER,
                )
                continue

        if frontmatter_delimiter is not None:
            _append_span(
                spans,
                line_start,
                line_end,
                HistoryDocumentSpanKind.FRONTMATTER,
            )
            stripped_body = line_body.strip()
            if stripped_body == frontmatter_delimiter or (
                frontmatter_delimiter == "---" and stripped_body == "..."
            ):
                frontmatter_delimiter = None
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

        if _is_forwarded_content_start(structural_line) or _starts_email_header_block(
            lines,
            line_index,
        ):
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

        if _is_pasted_dialogue_line(structural_line):
            lazy_pasted_paragraph = True
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


def _is_forwarded_content_start(line: str) -> bool:
    text = line.strip()
    return bool(_FORWARDED_MARKER_RE.match(text) or _FORWARDED_MARKER_ZH_RE.match(text))


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


def _is_pasted_dialogue_line(line: str) -> bool:
    text = line.strip()
    if not text:
        return False
    if not _SELF_ATTRIBUTION_LEAD_RE.match(text) and (
        _ATTRIBUTION_LEAD_RE.match(text) or _ATTRIBUTION_LEAD_ZH_RE.match(text)
    ):
        return True
    timestamped = False
    if text.startswith("["):
        closing = text.find("]")
        if 0 < closing <= 40:
            text = text[closing + 1 :].lstrip()
            timestamped = True
    if text.startswith(("**", "__")):
        marker = text[:2]
        closing = text.find(marker, 2)
        if closing > 2:
            label = text[2:closing].rstrip()
            remainder = text[closing + 2 :].lstrip()
            normalized_label = label[:-1] if label.endswith((":", "：")) else label
            if (
                label.endswith((":", "："))
                and remainder
                and _plausible_speaker_label(normalized_label, timestamped=timestamped)
            ):
                return True
    colon_positions = [position for marker in (":", "：") if 0 < (position := text.find(marker))]
    if colon_positions:
        colon = min(colon_positions)
        label = text[:colon].strip().strip("*_`~")
        remainder = text[colon + 1 :].lstrip(" *_")
        if remainder and _plausible_speaker_label(label, timestamped=timestamped):
            return True
    if _SPEAKER_DASH_RE.match(text):
        label = re.split(r"[ \t]+(?:—|–|-)[ \t]+", text, maxsplit=1)[0]
        return _plausible_speaker_label(
            label.strip("*_`~"),
            timestamped=timestamped,
        )
    return False


def _plausible_speaker_label(value: str, *, timestamped: bool) -> bool:
    label = value.strip()
    if not 1 <= len(label) <= 48:
        return False
    if any(character in label for character in '!?。！？"“”「」『』'):
        return False
    normalized = " ".join(label.casefold().split())
    if normalized in _CALLOUT_LABELS:
        return False
    if normalized in _SPEAKER_ROLE_LABELS or timestamped:
        return any(character.isalpha() for character in label)
    if _PERSON_TITLE_RE.match(label):
        return True
    if re.fullmatch(r"[\u3400-\u9fff]{1,12}", label):
        return True
    words = label.split()
    return bool(
        1 <= len(words) <= 4
        and all(
            word
            and (
                word[0].isupper()
                or word.isupper()
                or word.startswith("@")
                or (len(words) == 1 and word.isalpha())
            )
            for word in words
        )
    )


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

        if state.quote_closer is not None:
            closing = line.find(state.quote_closer, index)
            end = len(line) if closing < 0 else closing + len(state.quote_closer)
            _append_span(
                spans,
                base_offset + index,
                base_offset + end,
                HistoryDocumentSpanKind.QUOTED_TEXT,
            )
            index = end
            if closing < 0:
                return
            state.quote_closer = None
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

        closing = line.find(delimiter.closer, delimiter.opener_end)
        end = len(line) if closing < 0 else closing + len(delimiter.closer)
        _append_span(
            spans,
            base_offset + delimiter.start,
            base_offset + end,
            HistoryDocumentSpanKind.QUOTED_TEXT,
        )
        if closing < 0:
            state.quote_closer = delimiter.closer
            return
        index = end


def _next_inline_delimiter(line: str, start: int) -> _InlineDelimiter | None:
    candidates = [
        item
        for item in (
            _next_unescaped_backtick_run(line, start),
            _next_attributed_quote(line, start),
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


def _next_attributed_quote(line: str, start: int) -> _InlineDelimiter | None:
    openers = {'"': '"', "“": "”", "「": "」", "『": "』"}
    positions: list[tuple[int, str, str]] = []
    for opener, closer in openers.items():
        position = line.find(opener, start)
        while position >= 0:
            positions.append((position, opener, closer))
            position = line.find(opener, position + len(opener))
    positions.sort()
    for position, opener, closer in positions:
        prefix = line[:position]
        directly_attributed = bool(
            _REPORTING_VERB_TAIL_RE.search(prefix) or _ATTRIBUTION_PREFIX_TAIL_RE.search(prefix)
        )
        if directly_attributed and _SELF_REPORT_TAIL_RE.search(prefix):
            continue
        closing = line.find(closer, position + len(opener))
        post_attributed = closing >= 0 and bool(
            _POST_ATTRIBUTION_RE.match(line[closing + len(closer) :])
        )
        if not directly_attributed and not post_attributed:
            continue
        return _InlineDelimiter(
            start=position,
            opener_end=position + len(opener),
            kind="quote",
            closer=closer,
        )
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
