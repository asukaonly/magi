"""Strict host resolution for raw Claim time expressions."""

from __future__ import annotations

import calendar
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from ....utils.calendar_timezone import canonical_timezone_id
from ..claims.models import ClaimEvidenceInput
from ..temporal_trust import normalized_event_timestamp, trusted_event_timestamp

_CHINESE_DATE = re.compile(r"^([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日$")
_CHINESE_MONTH = re.compile(r"^([0-9]{4})年([0-9]{1,2})月$")
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


@dataclass(frozen=True, slots=True)
class _CalendarRange:
    """One timezone-bound civil range and its stable calendar descriptor."""

    start: datetime
    end: datetime
    precision: str
    operator: str

    @property
    def epochs(self) -> tuple[float, float]:
        return self.start.timestamp(), self.end.timestamp()

    def descriptor(
        self,
        *,
        timezone_id: str,
        anchor_event_ids: Iterable[str] = (),
    ) -> dict[str, object]:
        return {
            "timezone_id": timezone_id,
            "precision": self.precision,
            "civil_start": self.start.date().isoformat(),
            "civil_end_exclusive": self.end.date().isoformat(),
            "operator": self.operator,
            "anchor_event_ids": sorted(
                {str(event_id).strip() for event_id in anchor_event_ids if str(event_id).strip()}
            ),
        }


def resolve_claim_temporal_fields(
    *,
    raw_expression: str,
    future_intent: bool,
    evidence: Iterable[ClaimEvidenceInput],
    now: float | None = None,
) -> ClaimTemporalResolution:
    """Resolve a closed set of exact or calendar-anchored time expressions."""

    raw = str(raw_expression or "").strip()
    if not raw:
        return ClaimTemporalResolution(None, None, None, None, None)

    supporting = [item for item in evidence if item.link_role == "supporting"]
    timezone_evidence = tuple(
        (item, canonical_timezone_id(item.calendar_timezone_id)) for item in supporting
    )
    if not supporting or any(timezone_id is None for _item, timezone_id in timezone_evidence):
        return _unresolved(
            raw,
            future_intent=future_intent,
            quality="low",
        )
    timezone_ids = {str(timezone_id) for _item, timezone_id in timezone_evidence}
    timezone_id = sorted(timezone_ids)[0]

    absolute_ranges = {
        resolved
        for candidate_timezone_id in timezone_ids
        for resolved in [_absolute_range(raw, local_timezone=ZoneInfo(candidate_timezone_id))]
        if resolved is not None
    }
    if absolute_ranges:
        if len(absolute_ranges) != 1:
            return _unresolved(raw, future_intent=future_intent, quality="ambiguous")
        return _result(
            raw,
            future_intent=future_intent,
            calendar_range=next(iter(absolute_ranges)),
            timezone_id=timezone_id,
            quality="calendar_anchor",
        )

    if any(
        item.event_time is None or item.timestamp_quality not in _TRUSTED_ANCHOR_QUALITIES
        for item in supporting
    ):
        return _unresolved(raw, future_intent=future_intent, quality="low")

    anchor_times = [normalized_event_timestamp(item.event_time) for item in supporting]
    if any(anchor_time is None for anchor_time in anchor_times):
        return _unresolved(raw, future_intent=future_intent, quality="low")

    resolved_now = float(time.time() if now is None else now)
    if any(
        trusted_event_timestamp(anchor_time, now=resolved_now) is None
        for anchor_time in anchor_times
    ):
        return _unresolved(
            raw,
            future_intent=future_intent,
            quality="low",
        )

    anchored_ranges: set[_CalendarRange] = {
        resolved
        for item, item_timezone_id in timezone_evidence
        if item.event_time is not None
        for resolved in [
            _calendar_anchored_range(
                raw,
                float(item.event_time),
                local_timezone=ZoneInfo(str(item_timezone_id)),
            )
        ]
        if resolved is not None
    }
    if len(anchored_ranges) != 1:
        return _unresolved(raw, future_intent=future_intent, quality="ambiguous")
    return _result(
        raw,
        future_intent=future_intent,
        calendar_range=next(iter(anchored_ranges)),
        timezone_id=timezone_id,
        anchor_event_ids=(item.event_id for item in supporting),
        quality="calendar_anchor",
    )


def _result(
    raw: str,
    *,
    future_intent: bool,
    calendar_range: _CalendarRange,
    timezone_id: str,
    quality: str,
    anchor_event_ids: Iterable[str] = (),
) -> ClaimTemporalResolution:
    try:
        start, end = calendar_range.epochs
    except (OSError, OverflowError, ValueError):
        return _unresolved(raw, future_intent=future_intent, quality="ambiguous")
    if end <= start:
        return _unresolved(raw, future_intent=future_intent, quality="ambiguous")
    frame = {
        "raw": raw,
        "kind": "target" if future_intent else "fact_validity",
        "resolution": quality,
        "resolved_range": [start, end],
        "calendar": calendar_range.descriptor(
            timezone_id=timezone_id,
            anchor_event_ids=anchor_event_ids,
        ),
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


def _absolute_range(raw: str, *, local_timezone: ZoneInfo) -> _CalendarRange | None:
    day = _absolute_day(raw)
    if day is not None:
        return _day_range(day, local_timezone=local_timezone, operator="absolute")
    month = _absolute_month(raw)
    if month is not None:
        year, month_number = month
        start = datetime(year, month_number, 1, tzinfo=local_timezone)
        end = (
            datetime(year + 1, 1, 1, tzinfo=local_timezone)
            if month_number == 12
            else datetime(year, month_number + 1, 1, tzinfo=local_timezone)
        )
        return _CalendarRange(
            start=start,
            end=end,
            precision="month",
            operator="absolute",
        )
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
        if len(parts) != 2 or not all(part.isascii() and part.isdigit() for part in parts):
            return None
        year, month = (int(value) for value in parts)
    if year < 1 or month < 1 or month > 12:
        return None
    return year, month


def _calendar_anchored_range(
    raw: str,
    anchor_timestamp: float,
    *,
    local_timezone: ZoneInfo,
) -> _CalendarRange | None:
    normalized = raw.strip().casefold()
    anchor = datetime.fromtimestamp(anchor_timestamp, tz=local_timezone)
    day_offset = _RELATIVE_DAYS.get(normalized)
    if day_offset is not None:
        return _day_range(
            (anchor + timedelta(days=day_offset)).date(),
            local_timezone=local_timezone,
            operator=normalized,
        )
    if normalized in {"本周", "这周", "this week"}:
        start_day = anchor.date() - timedelta(days=anchor.weekday())
        return _bounded_days(
            start_day,
            7,
            local_timezone=local_timezone,
            operator=normalized,
            precision="week",
        )
    if normalized in {"下周", "next week"}:
        start_day = anchor.date() - timedelta(days=anchor.weekday()) + timedelta(days=7)
        return _bounded_days(
            start_day,
            7,
            local_timezone=local_timezone,
            operator=normalized,
            precision="week",
        )
    if normalized in {"本月", "这个月", "this month"}:
        return _month_range(
            anchor.year,
            anchor.month,
            local_timezone=local_timezone,
            operator=normalized,
        )
    if normalized in {"下个月", "next month"}:
        year = anchor.year + (1 if anchor.month == 12 else 0)
        month = 1 if anchor.month == 12 else anchor.month + 1
        return _month_range(
            year,
            month,
            local_timezone=local_timezone,
            operator=normalized,
        )
    return None


def _day_range(
    value: date,
    *,
    local_timezone: ZoneInfo,
    operator: str,
) -> _CalendarRange:
    start = datetime(value.year, value.month, value.day, tzinfo=local_timezone)
    return _CalendarRange(
        start=start,
        end=start + timedelta(days=1),
        precision="day",
        operator=operator,
    )


def _bounded_days(
    start_day: date,
    count: int,
    *,
    local_timezone: ZoneInfo,
    operator: str,
    precision: str,
) -> _CalendarRange:
    start = datetime(start_day.year, start_day.month, start_day.day, tzinfo=local_timezone)
    return _CalendarRange(
        start=start,
        end=start + timedelta(days=count),
        precision=precision,
        operator=operator,
    )


def _month_range(
    year: int,
    month: int,
    *,
    local_timezone: ZoneInfo,
    operator: str,
) -> _CalendarRange:
    start = datetime(year, month, 1, tzinfo=local_timezone)
    day_count = calendar.monthrange(year, month)[1]
    return _CalendarRange(
        start=start,
        end=start + timedelta(days=day_count),
        precision="month",
        operator=operator,
    )


__all__ = ["ClaimTemporalResolution", "resolve_claim_temporal_fields"]
