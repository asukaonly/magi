"""Deterministic Markdown parser for first-party history imports."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import ParsedHistoryFile

DOCUMENT_AUTHOR = "__document_author__"

_DATE_HEADING_RE = re.compile(r"^#{1,6}\s+(?P<value>\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?)\s*$")
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
_HEADING_RE = re.compile(r"^#{2,4}\s+(?P<value>[^#].{0,80}?)\s*$")
_INLINE_MESSAGE_RE = re.compile(
    r"^\s*(?:[-*]\s+)?"
    r"(?:\[(?P<timestamp>[^\]]{2,48})\]\s*)?"
    r"(?P<speaker>[^:：\n]{1,48})\s*[:：]\s*"
    r"(?P<content>\S.*)\s*$"
)
_ROLE_WITH_TIMESTAMP_RE = re.compile(
    r"^(?P<speaker>.+?)"
    r"(?:\s+[-—]\s+|\s+\()"
    r"(?P<timestamp>\d{4}[-/.]\d{1,2}[-/.]\d{1,2}[^)]*)\)?$"
)
_LOW_SIGNAL_RE = re.compile(r"^[\W_]+$", re.UNICODE)
_KNOWN_ROLE_NAMES = {
    "user",
    "assistant",
    "human",
    "ai",
    "me",
    "用户",
    "助手",
    "我",
    "本人",
    "自己",
}
_NON_SPEAKER_LABELS = {
    "title",
    "date",
    "time",
    "tags",
    "tag",
    "source",
    "author",
    "created",
    "updated",
    "标题",
    "日期",
    "时间",
    "标签",
    "来源",
    "作者",
}
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
    return parse_markdown(
        source_name=path.name,
        text=text,
        file_mtime=float(path.stat().st_mtime),
    )


def parse_markdown(
    *,
    source_name: str,
    text: str,
    file_mtime: float,
) -> ParsedHistoryFile:
    """Parse chat-shaped Markdown, falling back to one authored document."""

    frontmatter, body = _extract_frontmatter(str(text or ""))
    clean_text = body.strip()
    if not clean_text:
        raise ValueError("markdown_empty")
    source_timestamp, source_timestamp_confidence = _source_timestamp(
        source_name=source_name,
        text=clean_text,
        frontmatter=frontmatter,
        file_mtime=file_mtime,
    )

    inline_records = _parse_inline_chat(clean_text)
    heading_records = _parse_heading_chat(clean_text)
    chat_records = heading_records if len(heading_records) > len(inline_records) else inline_records
    if _is_confident_chat(chat_records):
        records, used_fallback_time = _finalize_chat_timestamps(
            chat_records,
            fallback_timestamp=source_timestamp,
        )
        warnings = ["timestamps_from_file_order"] if used_fallback_time else []
        return ParsedHistoryFile(
            source_name=source_name,
            session_key=_session_key(source_name),
            detected_kind="chat",
            records=records,
            warnings=warnings,
        )

    document_timestamp, document_timestamp_confidence = _document_timestamp(
        source_name=source_name,
        frontmatter=frontmatter,
        file_mtime=file_mtime,
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


def _source_timestamp(
    *,
    source_name: str,
    text: str,
    frontmatter: dict[str, str],
    file_mtime: float,
) -> tuple[float, str]:
    for key in ("date", "created", "created_at", "createdat", "timestamp"):
        parsed = _parse_timestamp(frontmatter.get(key))
        if parsed is not None:
            return parsed, "frontmatter"

    filename_timestamp = _parse_source_date(Path(source_name).stem)
    if filename_timestamp is not None:
        return filename_timestamp, "source_name"

    for line in text.splitlines()[:20]:
        match = _DATE_HEADING_RE.match(line.strip())
        if not match:
            continue
        parsed = _parse_timestamp(match.group("value"))
        if parsed is not None:
            return parsed, "document_heading"
    return float(file_mtime), "file_mtime"


def _document_timestamp(
    *,
    source_name: str,
    frontmatter: dict[str, str],
    file_mtime: float,
) -> tuple[float, str]:
    """Resolve document-level time without interpreting body headings."""

    for key in ("date", "created", "created_at", "createdat", "timestamp"):
        parsed = _parse_timestamp(frontmatter.get(key))
        if parsed is not None:
            return parsed, "frontmatter"

    filename_timestamp = _parse_source_date(Path(source_name).stem)
    if filename_timestamp is not None:
        return filename_timestamp, "source_name"
    return float(file_mtime), "file_mtime"


def _parse_source_date(value: str) -> float | None:
    for pattern in (_SOURCE_DATE_RE, _COMPACT_SOURCE_DATE_RE):
        match = pattern.search(value)
        if not match:
            continue
        return _parse_timestamp(
            f"{match.group('year')}-{match.group('month')}-{match.group('day')}"
        )
    return None


def _parse_inline_chat(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    current_date: str | None = None
    in_code_fence = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            if records and line.strip():
                records[-1]["content"] += f"\n{line.strip()}"
            continue
        date_match = _DATE_HEADING_RE.match(line.strip())
        if date_match:
            current_date = date_match.group("value")
            continue
        match = _INLINE_MESSAGE_RE.match(line)
        if match and _speaker_candidate_allowed(match.group("speaker")):
            timestamp_text = str(match.group("timestamp") or "").strip()
            if timestamp_text and current_date and _looks_time_only(timestamp_text):
                timestamp_text = f"{current_date} {timestamp_text}"
            records.append(
                {
                    "speaker_name": _clean_speaker(match.group("speaker")),
                    "content": match.group("content").strip(),
                    "timestamp_text": timestamp_text or None,
                }
            )
            continue
        stripped = line.strip()
        if records and stripped and not stripped.startswith("#"):
            records[-1]["content"] += f"\n{stripped}"
    return records


def _parse_heading_chat(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_code_fence = False
    for raw_line in lines:
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            in_code_fence = not in_code_fence
            if current is not None:
                current["content_lines"].append(line)
            continue
        if not in_code_fence:
            heading = _HEADING_RE.match(line.strip())
            if heading and not _DATE_HEADING_RE.match(line.strip()):
                speaker, timestamp_text = _split_heading_identity(heading.group("value").strip())
                if _speaker_candidate_allowed(speaker):
                    if current is not None:
                        _append_heading_record(records, current)
                    current = {
                        "speaker_name": speaker,
                        "timestamp_text": timestamp_text,
                        "content_lines": [],
                    }
                    continue
        if current is not None:
            current["content_lines"].append(line)
    if current is not None:
        _append_heading_record(records, current)
    return records


def _append_heading_record(
    records: list[dict[str, Any]],
    current: dict[str, Any],
) -> None:
    content = "\n".join(current["content_lines"]).strip()
    if not content:
        return
    records.append(
        {
            "speaker_name": _clean_speaker(current["speaker_name"]),
            "content": content,
            "timestamp_text": current["timestamp_text"],
        }
    )


def _split_heading_identity(value: str) -> tuple[str, str | None]:
    match = _ROLE_WITH_TIMESTAMP_RE.match(value)
    if match:
        return (
            _clean_speaker(match.group("speaker")),
            match.group("timestamp").strip(),
        )
    return _clean_speaker(value), None


def _speaker_candidate_allowed(value: str) -> bool:
    candidate = _clean_speaker(value)
    normalized = candidate.casefold()
    if not candidate or normalized in _NON_SPEAKER_LABELS:
        return False
    if candidate.startswith(("#", "[", "|")):
        return False
    if len(candidate) > 48 or len(candidate.split()) > 8:
        return False
    return True


def _clean_speaker(value: str) -> str:
    return str(value or "").strip().strip("*_` ")


def _is_confident_chat(records: list[dict[str, Any]]) -> bool:
    if len(records) < 2:
        return False
    speakers = {
        str(record.get("speaker_name") or "").strip().casefold()
        for record in records
        if str(record.get("speaker_name") or "").strip()
    }
    known_role_present = any(speaker in _KNOWN_ROLE_NAMES for speaker in speakers)
    repeated_speaker = len(speakers) < len(records)
    return (len(records) >= 3 and len(speakers) >= 2 and repeated_speaker) or (
        len(records) >= 2 and known_role_present
    )


def _finalize_chat_timestamps(
    records: list[dict[str, Any]],
    *,
    fallback_timestamp: float,
) -> tuple[list[dict[str, Any]], bool]:
    parsed: list[dict[str, Any]] = []
    parsed_timestamps = [_parse_timestamp(record.get("timestamp_text")) for record in records]
    used_fallback = any(value is None for value in parsed_timestamps)
    first_known = next((value for value in parsed_timestamps if value is not None), None)
    fallback_anchor = float(first_known if first_known is not None else fallback_timestamp)
    last_timestamp: float | None = None
    for index, record in enumerate(records):
        timestamp = parsed_timestamps[index]
        confidence = "explicit"
        if timestamp is None:
            confidence = "file_order"
            if last_timestamp is not None:
                timestamp = last_timestamp + 1.0
            elif first_known is None:
                timestamp = fallback_anchor + float(index)
            else:
                timestamp = fallback_anchor - float(len(records) - index)
        if last_timestamp is not None and timestamp < last_timestamp:
            timestamp = last_timestamp + 0.001
            confidence = "source_order"
        last_timestamp = float(timestamp)
        parsed.append(
            {
                "speaker_name": record["speaker_name"],
                "content": str(record["content"]).strip(),
                "event_at": float(timestamp),
                "timestamp_confidence": confidence,
                "meaningful": is_meaningful_content(str(record["content"])),
            }
        )
    return parsed, used_fallback


def _parse_timestamp(value: object) -> float | None:
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
            parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return float(parsed.timestamp())
    return None


def _looks_time_only(value: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", value.strip()))


def _session_key(source_name: str) -> str:
    normalized = str(source_name or "").replace("\\", "/").strip()
    return normalized or "markdown"


def is_meaningful_content(content: str) -> bool:
    """Return whether one message carries more than acknowledgement noise."""

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
