"""Timezone-aware calendar math for typed extraction judgments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from ..calendar_expression import ClaimCalendarExpression

TRUSTED_CURRENTNESS_QUALITIES = frozenset({"exact", "calendar_anchor"})


@dataclass(frozen=True, slots=True)
class CalendarRange:
    """One timezone-bound civil range and its audit descriptor."""

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
            "anchor_event_ids": sorted({str(value).strip() for value in anchor_event_ids if str(value).strip()}),
        }


def resolve_calendar_expression(
    expression: ClaimCalendarExpression | None,
    *,
    anchor_timestamp: float | None,
    anchor_quality: str,
    local_timezone: ZoneInfo,
) -> CalendarRange | None:
    """Execute one typed operation; raw language never selects calendar policy."""
    if expression is None or expression.kind == "at_observation":
        return None
    if expression.requires_anchor and (
        anchor_timestamp is None or anchor_quality not in TRUSTED_CURRENTNESS_QUALITIES
    ):
        return None
    try:
        anchor = (
            datetime.fromtimestamp(anchor_timestamp, tz=local_timezone).date()
            if anchor_timestamp is not None else None
        )
        start, end, precision = _civil_range(expression, anchor)
        return CalendarRange(
            start=datetime(start.year, start.month, start.day, tzinfo=local_timezone),
            end=datetime(end.year, end.month, end.day, tzinfo=local_timezone),
            precision=precision,
            operator=expression.kind,
        )
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def _civil_range(expression: ClaimCalendarExpression, anchor: date | None) -> tuple[date, date, str]:
    if expression.kind == "absolute":
        start = date(expression.year, expression.month or 1, expression.day or 1)
        return start, _period_end(start, expression.unit), expression.unit
    if expression.kind == "month_window":
        year = expression.year if expression.year is not None else anchor.year + expression.year_offset
        start = date(year, expression.start_month, 1)
        next_year, next_month = _add_months(year, expression.start_month, expression.month_count)
        return start, date(next_year, next_month, 1), "month"
    if expression.kind == "weekday":
        monday = anchor - timedelta(days=anchor.weekday())
        start = monday + timedelta(weeks=expression.week_offset, days=expression.weekday)
        return start, start + timedelta(days=1), "day"
    if expression.unit == "day":
        start = anchor + timedelta(days=expression.offset)
    elif expression.unit == "week":
        start = anchor - timedelta(days=anchor.weekday()) + timedelta(weeks=expression.offset)
    elif expression.unit == "month":
        year, month = _add_months(anchor.year, anchor.month, expression.offset)
        start = date(year, month, 1)
    else:
        start = date(anchor.year + expression.offset, 1, 1)
    return start, _period_end(start, expression.unit), expression.unit


def _period_end(start: date, unit: str) -> date:
    if unit == "day":
        return start + timedelta(days=1)
    if unit == "week":
        return start + timedelta(days=7)
    if unit == "month":
        year, month = _add_months(start.year, start.month, 1)
        return date(year, month, 1)
    return date(start.year + 1, 1, 1)


def _add_months(year: int, month: int, offset: int) -> tuple[int, int]:
    year, zero_based_month = divmod(year * 12 + month - 1 + offset, 12)
    return year, zero_based_month + 1


__all__ = ["CalendarRange", "TRUSTED_CURRENTNESS_QUALITIES", "resolve_calendar_expression"]
