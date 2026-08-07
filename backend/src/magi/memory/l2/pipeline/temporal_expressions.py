"""Ordered, timezone-aware rules for grounded Claim time expressions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

TRUSTED_CURRENTNESS_QUALITIES = frozenset({"exact", "calendar_anchor"})
_ALL_QUALITIES = frozenset(
    {
        "exact",
        "calendar_anchor",
        "approximate_recorded",
        "derived_order",
        "low",
    }
)


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
            "anchor_event_ids": sorted(
                {
                    str(event_id).strip()
                    for event_id in anchor_event_ids
                    if str(event_id).strip()
                }
            ),
        }


RuleBuilder = Callable[[str, datetime | None, ZoneInfo], CalendarRange | None]


@dataclass(frozen=True, slots=True)
class TemporalExpressionRule:
    """One ordered matcher with an explicit anchor trust boundary."""

    name: str
    matcher: re.Pattern[str]
    builder: RuleBuilder
    precision: str
    allowed_anchor_qualities: frozenset[str]
    requires_anchor: bool

    def matches(self, raw: str) -> bool:
        return self.matcher.fullmatch(raw) is not None


_RELATIVE_DAY_OFFSETS = {
    "昨天": -1,
    "今天": 0,
    "明天": 1,
    "后天": 2,
    "yesterday": -1,
    "today": 0,
    "tomorrow": 1,
    "the day after tomorrow": 2,
}
_SEASON_MONTHS = {
    "春": (3, 6),
    "春天": (3, 6),
    "spring": (3, 6),
    "夏": (6, 9),
    "夏天": (6, 9),
    "summer": (6, 9),
    "秋": (9, 12),
    "秋天": (9, 12),
    "autumn": (9, 12),
    "fall": (9, 12),
    "冬": (12, 3),
    "冬天": (12, 3),
    "winter": (12, 3),
}
_WEEKDAY_INDEX = {
    "一": 0,
    "1": 0,
    "monday": 0,
    "二": 1,
    "2": 1,
    "tuesday": 1,
    "三": 2,
    "3": 2,
    "wednesday": 2,
    "四": 3,
    "4": 3,
    "thursday": 3,
    "五": 4,
    "5": 4,
    "friday": 4,
    "六": 5,
    "6": 5,
    "saturday": 5,
    "日": 6,
    "天": 6,
    "7": 6,
    "sunday": 6,
}


def resolve_calendar_expression(
    raw: str,
    *,
    anchor_timestamp: float | None,
    anchor_quality: str,
    local_timezone: ZoneInfo,
) -> CalendarRange | None:
    """Resolve the first matching rule whose anchor policy is satisfied."""

    normalized = " ".join(str(raw or "").strip().casefold().split())
    anchor = (
        datetime.fromtimestamp(float(anchor_timestamp), tz=local_timezone)
        if anchor_timestamp is not None
        else None
    )
    for rule in TEMPORAL_EXPRESSION_RULES:
        if not rule.matches(normalized):
            continue
        if rule.requires_anchor:
            if anchor is None or anchor_quality not in rule.allowed_anchor_qualities:
                return None
        return rule.builder(normalized, anchor, local_timezone)
    return None


def _absolute_day(raw: str, _anchor: datetime | None, timezone: ZoneInfo) -> CalendarRange | None:
    chinese = re.fullmatch(r"([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日", raw)
    try:
        value = (
            date(*(int(part) for part in chinese.groups()))
            if chinese is not None
            else date.fromisoformat(raw.replace("/", "-"))
        )
    except ValueError:
        return None
    return _day_range(value, timezone=timezone, operator="absolute")


def _absolute_month(
    raw: str,
    _anchor: datetime | None,
    timezone: ZoneInfo,
) -> CalendarRange | None:
    chinese = re.fullmatch(r"([0-9]{4})年([0-9]{1,2})月", raw)
    if chinese is not None:
        year, month = (int(part) for part in chinese.groups())
    else:
        parts = raw.replace("/", "-").split("-")
        if len(parts) != 2 or not all(part.isascii() and part.isdigit() for part in parts):
            return None
        year, month = (int(part) for part in parts)
    if year < 1 or month not in range(1, 13):
        return None
    return _month_range(year, month, timezone=timezone, operator="absolute")


def _absolute_season(
    raw: str,
    _anchor: datetime | None,
    timezone: ZoneInfo,
) -> CalendarRange | None:
    match = re.fullmatch(r"([0-9]{4})年?(春天?|夏天?|秋天?|冬天?|spring|summer|autumn|fall|winter)", raw)
    if match is None:
        return None
    return _season_range(
        int(match.group(1)),
        match.group(2),
        timezone=timezone,
        operator="absolute",
    )


def _absolute_year_period(
    raw: str,
    _anchor: datetime | None,
    timezone: ZoneInfo,
) -> CalendarRange | None:
    match = re.fullmatch(r"([0-9]{4})年(年底|年中|上半年|下半年)", raw)
    if match is None:
        return None
    return _year_period_range(
        int(match.group(1)),
        match.group(2),
        timezone=timezone,
        operator="absolute",
    )


def _relative_day(raw: str, anchor: datetime | None, timezone: ZoneInfo) -> CalendarRange | None:
    if anchor is None:
        return None
    offset = _RELATIVE_DAY_OFFSETS.get(raw)
    if offset is None:
        return None
    return _day_range(
        (anchor + timedelta(days=offset)).date(),
        timezone=timezone,
        operator=raw,
    )


def _relative_week(raw: str, anchor: datetime | None, timezone: ZoneInfo) -> CalendarRange | None:
    if anchor is None:
        return None
    offset = 7 if raw in {"下周", "next week"} else 0
    monday = anchor.date() - timedelta(days=anchor.weekday()) + timedelta(days=offset)
    return _bounded_days(
        monday,
        7,
        timezone=timezone,
        operator=raw,
        precision="week",
    )


def _relative_month(raw: str, anchor: datetime | None, timezone: ZoneInfo) -> CalendarRange | None:
    if anchor is None:
        return None
    offset = 1 if raw in {"下个月", "next month"} else 0
    year, month = _add_months(anchor.year, anchor.month, offset)
    return _month_range(year, month, timezone=timezone, operator=raw)


def _next_weekday(raw: str, anchor: datetime | None, timezone: ZoneInfo) -> CalendarRange | None:
    if anchor is None:
        return None
    chinese = re.fullmatch(r"下周([一二三四五六日天1-7])", raw)
    english = re.fullmatch(
        r"next (monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
        raw,
    )
    token = chinese.group(1) if chinese is not None else english.group(1) if english else ""
    weekday = _WEEKDAY_INDEX.get(token)
    if weekday is None:
        return None
    monday = anchor.date() - timedelta(days=anchor.weekday()) + timedelta(days=7)
    return _day_range(
        monday + timedelta(days=weekday),
        timezone=timezone,
        operator=raw,
    )


def _relative_season(
    raw: str,
    anchor: datetime | None,
    timezone: ZoneInfo,
) -> CalendarRange | None:
    if anchor is None:
        return None
    chinese = re.fullmatch(r"(今年|明年)(春天?|夏天?|秋天?|冬天?)", raw)
    english = re.fullmatch(r"(this|next) (spring|summer|autumn|fall|winter)", raw)
    if chinese is not None:
        year = anchor.year + (1 if chinese.group(1) == "明年" else 0)
        season = chinese.group(2)
    elif english is not None:
        year = anchor.year + (1 if english.group(1) == "next" else 0)
        season = english.group(2)
    else:
        return None
    return _season_range(year, season, timezone=timezone, operator=raw)


def _relative_year_period(
    raw: str,
    anchor: datetime | None,
    timezone: ZoneInfo,
) -> CalendarRange | None:
    if anchor is None:
        return None
    chinese = re.fullmatch(r"(?:(今年|明年))?(年底|年中|上半年|下半年)", raw)
    english_periods = {
        "end of this year": (0, "年底"),
        "end of next year": (1, "年底"),
        "mid-year": (0, "年中"),
        "first half of this year": (0, "上半年"),
        "second half of this year": (0, "下半年"),
        "first half of next year": (1, "上半年"),
        "second half of next year": (1, "下半年"),
    }
    if chinese is not None:
        offset = 1 if chinese.group(1) == "明年" else 0
        period = chinese.group(2)
    elif raw in english_periods:
        offset, period = english_periods[raw]
    else:
        return None
    return _year_period_range(
        anchor.year + offset,
        period,
        timezone=timezone,
        operator=raw,
    )


def _relative_duration(
    raw: str,
    anchor: datetime | None,
    timezone: ZoneInfo,
) -> CalendarRange | None:
    if anchor is None:
        return None
    chinese = re.fullmatch(r"([0-9]+|[一二三四五六七八九十百]+)(天|周|个月|月|年)后", raw)
    english = re.fullmatch(r"in ([0-9]+) (day|week|month|year)s?", raw)
    if chinese is not None:
        count = _parse_positive_integer(chinese.group(1))
        unit = chinese.group(2)
    elif english is not None:
        count = int(english.group(1))
        unit = english.group(2)
    else:
        return None
    if count is None or count <= 0:
        return None
    if unit in {"天", "day"}:
        target = anchor.date() + timedelta(days=count)
        return _day_range(target, timezone=timezone, operator=raw)
    if unit in {"周", "week"}:
        target = anchor.date() + timedelta(days=7 * count)
        return _day_range(target, timezone=timezone, operator=raw)
    if unit in {"个月", "月", "month"}:
        year, month = _add_months(anchor.year, anchor.month, count)
        return _month_range(year, month, timezone=timezone, operator=raw)
    target_year = anchor.year + count
    try:
        target = anchor.date().replace(year=target_year)
    except ValueError:
        target = date(target_year, 2, 28)
    return _day_range(target, timezone=timezone, operator=raw)


def _day_range(value: date, *, timezone: ZoneInfo, operator: str) -> CalendarRange:
    start = datetime(value.year, value.month, value.day, tzinfo=timezone)
    next_day = value + timedelta(days=1)
    end = datetime(next_day.year, next_day.month, next_day.day, tzinfo=timezone)
    return CalendarRange(start=start, end=end, precision="day", operator=operator)


def _bounded_days(
    start_day: date,
    count: int,
    *,
    timezone: ZoneInfo,
    operator: str,
    precision: str,
) -> CalendarRange:
    end_day = start_day + timedelta(days=count)
    return CalendarRange(
        start=datetime(start_day.year, start_day.month, start_day.day, tzinfo=timezone),
        end=datetime(end_day.year, end_day.month, end_day.day, tzinfo=timezone),
        precision=precision,
        operator=operator,
    )


def _month_range(year: int, month: int, *, timezone: ZoneInfo, operator: str) -> CalendarRange:
    next_year, next_month = _add_months(year, month, 1)
    return CalendarRange(
        start=datetime(year, month, 1, tzinfo=timezone),
        end=datetime(next_year, next_month, 1, tzinfo=timezone),
        precision="month",
        operator=operator,
    )


def _season_range(
    year: int,
    season: str,
    *,
    timezone: ZoneInfo,
    operator: str,
) -> CalendarRange | None:
    months = _SEASON_MONTHS.get(season)
    if months is None or year < 1:
        return None
    start_month, end_month = months
    end_year = year + 1 if end_month <= start_month else year
    try:
        return CalendarRange(
            start=datetime(year, start_month, 1, tzinfo=timezone),
            end=datetime(end_year, end_month, 1, tzinfo=timezone),
            precision="season",
            operator=operator,
        )
    except ValueError:
        return None


def _year_period_range(
    year: int,
    period: str,
    *,
    timezone: ZoneInfo,
    operator: str,
) -> CalendarRange | None:
    boundaries = {
        "上半年": ((year, 1, 1), (year, 7, 1), "half_year"),
        "下半年": ((year, 7, 1), (year + 1, 1, 1), "half_year"),
        "年中": ((year, 6, 1), (year, 7, 1), "month"),
        "年底": ((year, 12, 1), (year + 1, 1, 1), "month"),
    }
    boundary = boundaries.get(period)
    if boundary is None:
        return None
    start_parts, end_parts, precision = boundary
    try:
        return CalendarRange(
            start=datetime(*start_parts, tzinfo=timezone),
            end=datetime(*end_parts, tzinfo=timezone),
            precision=precision,
            operator=operator,
        )
    except ValueError:
        return None


def _add_months(year: int, month: int, offset: int) -> tuple[int, int]:
    absolute = (year * 12) + (month - 1) + offset
    return divmod(absolute, 12)[0], divmod(absolute, 12)[1] + 1


def _parse_positive_integer(value: str) -> int | None:
    if value.isascii() and value.isdigit():
        return int(value)
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if value == "百":
        return 100
    if "百" in value:
        hundreds, remainder = value.split("百", 1)
        head = digits.get(hundreds, 1 if not hundreds else 0)
        tail = _parse_positive_integer(remainder) if remainder else 0
        return head * 100 + (tail or 0)
    if "十" in value:
        tens, ones = value.split("十", 1)
        head = digits.get(tens, 1 if not tens else 0)
        tail = digits.get(ones, 0) if ones else 0
        return head * 10 + tail
    return digits.get(value)


TEMPORAL_EXPRESSION_RULES = (
    TemporalExpressionRule(
        "absolute_day",
        re.compile(r"(?:[0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日|[0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2})"),
        _absolute_day,
        "day",
        _ALL_QUALITIES,
        False,
    ),
    TemporalExpressionRule(
        "absolute_month",
        re.compile(r"(?:[0-9]{4}年[0-9]{1,2}月|[0-9]{4}[-/][0-9]{1,2})"),
        _absolute_month,
        "month",
        _ALL_QUALITIES,
        False,
    ),
    TemporalExpressionRule(
        "absolute_season",
        re.compile(r"[0-9]{4}年?(?:春天?|夏天?|秋天?|冬天?|spring|summer|autumn|fall|winter)"),
        _absolute_season,
        "season",
        _ALL_QUALITIES,
        False,
    ),
    TemporalExpressionRule(
        "absolute_year_period",
        re.compile(r"[0-9]{4}年(?:年底|年中|上半年|下半年)"),
        _absolute_year_period,
        "year_period",
        _ALL_QUALITIES,
        False,
    ),
    TemporalExpressionRule(
        "relative_day",
        re.compile(r"(?:昨天|今天|明天|后天|yesterday|today|tomorrow|the day after tomorrow)"),
        _relative_day,
        "day",
        TRUSTED_CURRENTNESS_QUALITIES,
        True,
    ),
    TemporalExpressionRule(
        "relative_week",
        re.compile(r"(?:本周|这周|下周|this week|next week)"),
        _relative_week,
        "week",
        TRUSTED_CURRENTNESS_QUALITIES,
        True,
    ),
    TemporalExpressionRule(
        "next_weekday",
        re.compile(r"(?:下周[一二三四五六日天1-7]|next (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))"),
        _next_weekday,
        "day",
        TRUSTED_CURRENTNESS_QUALITIES,
        True,
    ),
    TemporalExpressionRule(
        "relative_month",
        re.compile(r"(?:本月|这个月|下个月|this month|next month)"),
        _relative_month,
        "month",
        TRUSTED_CURRENTNESS_QUALITIES,
        True,
    ),
    TemporalExpressionRule(
        "relative_season",
        re.compile(r"(?:(?:今年|明年)(?:春天?|夏天?|秋天?|冬天?)|(?:this|next) (?:spring|summer|autumn|fall|winter))"),
        _relative_season,
        "season",
        TRUSTED_CURRENTNESS_QUALITIES,
        True,
    ),
    TemporalExpressionRule(
        "relative_year_period",
        re.compile(r"(?:(?:(?:今年|明年))?(?:年底|年中|上半年|下半年)|end of (?:this|next) year|mid-year|(?:first|second) half of (?:this|next) year)"),
        _relative_year_period,
        "year_period",
        TRUSTED_CURRENTNESS_QUALITIES,
        True,
    ),
    TemporalExpressionRule(
        "relative_duration",
        re.compile(r"(?:[0-9]+|[一二三四五六七八九十百]+)(?:天|周|个月|月|年)后|in [0-9]+ (?:day|week|month|year)s?"),
        _relative_duration,
        "duration",
        TRUSTED_CURRENTNESS_QUALITIES,
        True,
    ),
)


__all__ = [
    "CalendarRange",
    "TEMPORAL_EXPRESSION_RULES",
    "TRUSTED_CURRENTNESS_QUALITIES",
    "TemporalExpressionRule",
    "resolve_calendar_expression",
]
