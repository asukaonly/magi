"""Strict host resolution for raw Claim time expressions."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Iterable

from ..claims.models import ClaimEvidenceInput

_CHINESE_DATE = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$")
_CHINESE_MONTH = re.compile(r"^(\d{4})年(\d{1,2})月$")
_RELATIVE_DAYS = {
    "昨天": -1,
    "今天": 0,
    "明天": 1,
    "后天": 2,
    "yesterday": -1,
    "today": 0,
    "tomorrow": 1,
    "the day after tomorrow": 2,
}
_TRUSTED_ANCHOR_QUALITIES = frozenset({"exact", "calendar_anchor"})


@dataclass(frozen=True, slots=True)
class ClaimTemporalResolution:
    """Resolved semantic window and auditable raw expression metadata."""

    fact_valid_from: float | None
    fact_valid_to: float | None
    target_from: float | None
    target_to: float | None
    raw_time_frame: dict[str, object] | None


def resolve_claim_temporal_fields(
    *,
    raw_expression: str,
    future_intent: bool,
    evidence: Iterable[ClaimEvidenceInput],
    local_timezone: tzinfo | None = None,
) -> ClaimTemporalResolution:
    """Resolve a closed set of exact or calendar-anchored time expressions."""

    raw = str(raw_expression or "").strip()
    if not raw:
        return ClaimTemporalResolution(None, None, None, None, None)

    resolved_timezone = local_timezone or datetime.now().astimezone().tzinfo or timezone.utc
    absolute = _absolute_range(raw, local_timezone=resolved_timezone)
    if absolute is not None:
        start, end = absolute
        return _result(raw, future_intent=future_intent, start=start, end=end, quality="exact")

    supporting = [item for item in evidence if item.link_role == "supporting"]
    if not supporting or any(
        item.event_time is None or item.timestamp_quality not in _TRUSTED_ANCHOR_QUALITIES
        for item in supporting
    ):
        return _unresolved(raw, future_intent=future_intent, quality="low")

    anchored_ranges = {
        resolved
        for item in supporting
        if item.event_time is not None
        for resolved in [
            _calendar_anchored_range(
                raw,
                float(item.event_time),
                local_timezone=resolved_timezone,
            )
        ]
        if resolved is not None
    }
    if len(anchored_ranges) != 1:
        return _unresolved(raw, future_intent=future_intent, quality="ambiguous")
    start, end = next(iter(anchored_ranges))
    return _result(
        raw,
        future_intent=future_intent,
        start=start,
        end=end,
        quality="calendar_anchor",
    )


def _result(
    raw: str,
    *,
    future_intent: bool,
    start: float,
    end: float,
    quality: str,
) -> ClaimTemporalResolution:
    frame = {
        "raw": raw,
        "kind": "target" if future_intent else "fact_validity",
        "resolution": quality,
        "resolved_range": [start, end],
    }
    if future_intent:
        return ClaimTemporalResolution(None, None, start, end, frame)
    return ClaimTemporalResolution(start, end, None, None, frame)


def _unresolved(
    raw: str,
    *,
    future_intent: bool,
    quality: str,
) -> ClaimTemporalResolution:
    return ClaimTemporalResolution(
        None,
        None,
        None,
        None,
        {
            "raw": raw,
            "kind": "target" if future_intent else "fact_validity",
            "resolution": quality,
            "resolved_range": None,
        },
    )


def _absolute_range(raw: str, *, local_timezone: tzinfo) -> tuple[float, float] | None:
    day = _absolute_day(raw)
    if day is not None:
        return _day_range(day, local_timezone=local_timezone)
    month = _absolute_month(raw)
    if month is not None:
        year, month_number = month
        start = datetime(year, month_number, 1, tzinfo=local_timezone)
        end = (
            datetime(year + 1, 1, 1, tzinfo=local_timezone)
            if month_number == 12
            else datetime(year, month_number + 1, 1, tzinfo=local_timezone)
        )
        return start.timestamp(), end.timestamp()
    return None


def _absolute_day(raw: str) -> date | None:
    chinese = _CHINESE_DATE.fullmatch(raw)
    if chinese is not None:
        try:
            return date(*(int(value) for value in chinese.groups()))
        except ValueError:
            return None
    try:
        return date.fromisoformat(raw.replace("/", "-"))
    except ValueError:
        return None


def _absolute_month(raw: str) -> tuple[int, int] | None:
    chinese = _CHINESE_MONTH.fullmatch(raw)
    if chinese is not None:
        year, month = (int(value) for value in chinese.groups())
    else:
        parts = raw.replace("/", "-").split("-")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            return None
        year, month = (int(value) for value in parts)
    if year < 1 or month < 1 or month > 12:
        return None
    return year, month


def _calendar_anchored_range(
    raw: str,
    anchor_timestamp: float,
    *,
    local_timezone: tzinfo,
) -> tuple[float, float] | None:
    normalized = raw.strip().casefold()
    anchor = datetime.fromtimestamp(anchor_timestamp, tz=local_timezone)
    day_offset = _RELATIVE_DAYS.get(normalized)
    if day_offset is not None:
        return _day_range(
            (anchor + timedelta(days=day_offset)).date(),
            local_timezone=local_timezone,
        )
    if normalized in {"本周", "这周", "this week"}:
        start_day = anchor.date() - timedelta(days=anchor.weekday())
        return _bounded_days(start_day, 7, local_timezone=local_timezone)
    if normalized in {"下周", "next week"}:
        start_day = anchor.date() - timedelta(days=anchor.weekday()) + timedelta(days=7)
        return _bounded_days(start_day, 7, local_timezone=local_timezone)
    if normalized in {"本月", "这个月", "this month"}:
        return _month_range(anchor.year, anchor.month, local_timezone=local_timezone)
    if normalized in {"下个月", "next month"}:
        year = anchor.year + (1 if anchor.month == 12 else 0)
        month = 1 if anchor.month == 12 else anchor.month + 1
        return _month_range(year, month, local_timezone=local_timezone)
    return None


def _day_range(value: date, *, local_timezone: tzinfo) -> tuple[float, float]:
    start = datetime(value.year, value.month, value.day, tzinfo=local_timezone)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def _bounded_days(
    start_day: date,
    count: int,
    *,
    local_timezone: tzinfo,
) -> tuple[float, float]:
    start = datetime(start_day.year, start_day.month, start_day.day, tzinfo=local_timezone)
    return start.timestamp(), (start + timedelta(days=count)).timestamp()


def _month_range(year: int, month: int, *, local_timezone: tzinfo) -> tuple[float, float]:
    start = datetime(year, month, 1, tzinfo=local_timezone)
    day_count = calendar.monthrange(year, month)[1]
    return start.timestamp(), (start + timedelta(days=day_count)).timestamp()


__all__ = ["ClaimTemporalResolution", "resolve_claim_temporal_fields"]
