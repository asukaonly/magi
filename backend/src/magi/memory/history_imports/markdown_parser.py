"""Deterministic personal-writing parser for first-party Markdown imports."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ...utils.calendar_timezone import canonical_timezone_id, local_calendar_timezone_id
from .models import ParsedHistoryFile

DOCUMENT_AUTHOR = "__document_author__"

_SOURCE_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>20\d{2})[-_.年](?P<month>\d{1,2})[-_.月]" r"(?P<day>\d{1,2})(?:日)?(?!\d)"
)
_COMPACT_SOURCE_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>20\d{2})(?P<month>\d{2})(?P<day>\d{2})(?!\d)"
)
_FRONTMATTER_FIELD_RE = re.compile(
    r"^\s*(?P<key>date|created|created_at|createdat|timestamp)\s*:\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
_LOW_SIGNAL_RE = re.compile(r"^[\W_]+$", re.UNICODE)
_LOW_SIGNAL_TEXT = {
    "ok",
    "okay",
    "嗯",
    "哦",
    "啊",
    "哈哈",
    "哈哈哈",
    "好的",
    "收到",
    "行",
    "可以",
    "谢谢",
}


def parse_markdown_path(path: Path) -> ParsedHistoryFile:
    """Read and parse one Markdown file."""

    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("markdown_not_utf8") from exc
    calendar_timezone_id = local_calendar_timezone_id()
    if calendar_timezone_id is None:
        raise ValueError("history_import_timezone_unavailable")
    return parse_markdown(
        source_name=path.name,
        text=text,
        file_mtime=float(path.stat().st_mtime),
        calendar_timezone_id=calendar_timezone_id,
    )


def parse_markdown(
    *,
    source_name: str,
    text: str,
    file_mtime: float,
    calendar_timezone_id: str,
) -> ParsedHistoryFile:
    """Parse one Markdown file as one authored personal document.

    Generic Markdown import deliberately does not infer message boundaries or
    speaker identity. Conversation archives require a source-specific importer
    with an explicit format contract.
    """

    normalized_timezone_id = canonical_timezone_id(calendar_timezone_id)
    if normalized_timezone_id is None:
        raise ValueError("history_import_timezone_invalid")
    local_timezone = ZoneInfo(normalized_timezone_id)
    frontmatter, body = _extract_frontmatter(str(text or ""))
    clean_text = body.strip()
    if not clean_text:
        raise ValueError("markdown_empty")
    document_timestamp, document_timestamp_confidence = _document_timestamp(
        source_name=source_name,
        frontmatter=frontmatter,
        file_mtime=file_mtime,
        local_timezone=local_timezone,
    )
    warnings = ["document_author_confirmation_required"]
    if document_timestamp_confidence == "file_mtime":
        warnings.append("timestamps_from_file_mtime")
    return ParsedHistoryFile(
        source_name=source_name,
        session_key=_session_key(source_name),
        detected_kind="document",
        records=[
            {
                "speaker_name": DOCUMENT_AUTHOR,
                "content": clean_text,
                "event_at": document_timestamp,
                "timestamp_confidence": document_timestamp_confidence,
                "timestamp_anchor_source": _timestamp_anchor_source(
                    document_timestamp_confidence
                ),
                "calendar_timezone_id": normalized_timezone_id,
                "meaningful": is_meaningful_content(clean_text),
            }
        ],
        warnings=warnings,
    )


def _extract_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    first_content_index = next(
        (index for index, line in enumerate(lines) if line.strip()),
        None,
    )
    if first_content_index is None or lines[first_content_index].strip() != "---":
        return {}, text
    for index in range(first_content_index + 1, min(len(lines), 200)):
        if lines[index].strip() == "---":
            metadata: dict[str, str] = {}
            for line in lines[first_content_index + 1 : index]:
                match = _FRONTMATTER_FIELD_RE.match(line)
                if match:
                    metadata[match.group("key").casefold()] = (
                        match.group("value").strip().strip("\"'")
                    )
            return metadata, "\n".join(lines[index + 1 :])
    return {}, text


def _document_timestamp(
    *,
    source_name: str,
    frontmatter: dict[str, str],
    file_mtime: float,
    local_timezone: ZoneInfo,
) -> tuple[float, str]:
    """Resolve document-level time without interpreting body headings."""

    for key in ("date", "created", "created_at", "createdat", "timestamp"):
        parsed = _parse_timestamp(frontmatter.get(key), local_timezone=local_timezone)
        if parsed is not None:
            return parsed, "frontmatter"

    filename_timestamp = _parse_source_date(
        Path(source_name).stem,
        local_timezone=local_timezone,
    )
    if filename_timestamp is not None:
        return filename_timestamp, "source_name"
    return float(file_mtime), "file_mtime"


def _parse_source_date(value: str, *, local_timezone: ZoneInfo) -> float | None:
    for pattern in (_SOURCE_DATE_RE, _COMPACT_SOURCE_DATE_RE):
        match = pattern.search(value)
        if not match:
            continue
        return _parse_timestamp(
            f"{match.group('year')}-{match.group('month')}-{match.group('day')}",
            local_timezone=local_timezone,
        )
    return None


def _parse_timestamp(value: object, *, local_timezone: ZoneInfo) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = (
        text.replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("/", "-")
        .replace(".", "-")
        .replace("T", " ")
        .strip()
    )
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    candidates = (
        normalized,
        re.sub(r"\s+", " ", normalized),
    )
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=local_timezone)
        return float(parsed.timestamp())
    return None


def _timestamp_anchor_source(timestamp_confidence: str) -> str:
    anchors = {
        "frontmatter": "frontmatter",
        "source_name": "source_name",
        "file_mtime": "file_mtime",
    }
    try:
        return anchors[timestamp_confidence]
    except KeyError as exc:
        raise ValueError("history_import_timestamp_confidence_invalid") from exc


def _session_key(source_name: str) -> str:
    normalized = str(source_name or "").replace("\\", "/").strip()
    return normalized or "markdown"


def is_meaningful_content(content: str) -> bool:
    """Return whether one imported document carries more than acknowledgement noise."""

    normalized = re.sub(r"\s+", " ", str(content or "")).strip()
    if len(normalized) < 2 or _LOW_SIGNAL_RE.fullmatch(normalized):
        return False
    if normalized.casefold() in _LOW_SIGNAL_TEXT:
        return False
    return bool(re.search(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", normalized))


__all__ = [
    "DOCUMENT_AUTHOR",
    "is_meaningful_content",
    "parse_markdown",
    "parse_markdown_path",
]
