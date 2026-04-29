"""Natural-language time parsing helpers for retrieval intent decisions."""
from __future__ import annotations

import calendar
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .models import TimeRange

logger = logging.getLogger(__name__)

_RECENTLY_KEYWORDS: list[str] = ["最近", "recently", "近期"]

_ZH_YEAR_MONTH_RE = re.compile(r"(?<!\d)(\d{4})\s*年\s*(\d{1,2})\s*月(?!\s*\d\s*[号日])")
_ZH_RELATIVE_RE = re.compile(r"\d+\s*(?:天|小时|周|个?月)前")
_ZH_DATE_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[号日]")
_ZH_LAST_WEEKDAY_RE = re.compile(r"上(?:周|星期)([一二三四五六日天])")
_ZH_THIS_WEEK_RE = re.compile(r"(?:这|本)(?:周|星期)")
_ZH_DAY_MAP: dict[str, int] = {
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
}

_HOUR_HINT_RE = re.compile(r"hour|小时", re.IGNORECASE)
_WEEK_HINT_RE = re.compile(r"week|周|星期", re.IGNORECASE)
_WEEKDAY_SPECIFIC_RE = re.compile(
    r"周[一二三四五六日天]"
    r"|星期[一二三四五六日天]"
    r"|(?:mon|tues|wednes|thurs|fri|satur|sun)day",
    re.IGNORECASE,
)
_MONTH_HINT_RE = re.compile(r"month|月", re.IGNORECASE)
_DAY_NUMBER_SUFFIX_RE = re.compile(r"\d+\s*[号日]|\d+(?:st|nd|rd|th)\b", re.IGNORECASE)
_LEADING_PREP_RE = re.compile(r"^(?:in|at|on|for|from)\s+", re.IGNORECASE)


def parse_time_range(query: str, raw_time_range: dict[str, Any] | None) -> TimeRange | None:
    if raw_time_range:
        parsed = parse_raw_time_range(raw_time_range)
        if parsed is not None:
            return parsed
    return parse_time_from_query(query)


def parse_raw_time_range(raw: dict[str, Any]) -> TimeRange | None:
    if "start" in raw or "end" in raw:
        start = float(raw["start"]) if "start" in raw else None
        end = float(raw["end"]) if "end" in raw else None
        return TimeRange(start=start, end=end)

    if "relative" in raw:
        rel = str(raw["relative"]).strip().lower()
        now = time.time()
        match = re.match(r"(\d+)\s*([dhwm])", rel)
        if match:
            amount, unit = int(match.group(1)), match.group(2)
            seconds = {"d": 86400, "h": 3600, "w": 604800, "m": 2592000}[unit]
            return TimeRange(start=now - amount * seconds, end=now)

    return None


def parse_time_from_query(query: str) -> TimeRange | None:
    query_lower = query.lower()
    now = datetime.now(tz=timezone.utc)

    if any(keyword in query_lower for keyword in _RECENTLY_KEYWORDS):
        return TimeRange(
            start=(now - timedelta(days=7)).timestamp(),
            end=now.timestamp(),
        )

    zh_result = try_chinese_temporal(query, now)
    if zh_result is not None:
        return zh_result

    try:
        from dateparser.search import search_dates
    except ImportError:
        logger.debug("dateparser not available; skipping NL time parsing")
        return None

    settings: dict[str, Any] = {
        "RELATIVE_BASE": now.replace(tzinfo=None),
        "PREFER_DATES_FROM": "past",
    }

    try:
        results = search_dates(query, settings=settings, languages=["en", "zh"])
    except Exception:
        logger.debug("dateparser.search_dates failed for query=%r", query)
        return None

    if not results:
        return None

    past: list[tuple[str, datetime]] = []
    for matched_text, resolved_dt in results:
        dt_utc = resolved_dt.replace(tzinfo=timezone.utc)
        if dt_utc <= now:
            past.append((matched_text, dt_utc))

    if not past:
        past = reparse_with_stripped_preposition(results, settings, now)

    if not past:
        return None

    if len(past) == 1:
        text, dt = past[0]
        return range_from_match(text, dt, now)

    all_ranges = [range_from_match(text, dt, now) for text, dt in past]
    return TimeRange(
        start=min(r.start for r in all_ranges if r.start is not None),
        end=max(r.end for r in all_ranges if r.end is not None),
    )


def try_chinese_temporal(query: str, now: datetime) -> TimeRange | None:
    match = _ZH_YEAR_MONTH_RE.search(query)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return month_range(year=year, month=month, now=now)

    match = _ZH_RELATIVE_RE.search(query)
    if match:
        phrase = match.group(0)
        try:
            from dateparser import parse as dp_parse
        except ImportError:
            return None
        settings: dict[str, Any] = {
            "RELATIVE_BASE": now.replace(tzinfo=None),
            "PREFER_DATES_FROM": "past",
        }
        dt = dp_parse(phrase, settings=settings, languages=["zh"])
        if dt:
            dt_utc = dt.replace(tzinfo=timezone.utc)
            return range_from_match(phrase, dt_utc, now)

    match = _ZH_LAST_WEEKDAY_RE.search(query)
    if match:
        weekday = _ZH_DAY_MAP.get(match.group(1))
        if weekday is not None:
            last_monday = now - timedelta(days=now.weekday() + 7)
            target = last_monday + timedelta(days=weekday)
            return day_range(target)

    match = _ZH_DATE_RE.search(query)
    if match:
        month, day = int(match.group(1)), int(match.group(2))
        try:
            target = datetime(now.year, month, day, tzinfo=timezone.utc)
            return day_range(target)
        except ValueError:
            pass

    if _ZH_THIS_WEEK_RE.search(query):
        monday = now - timedelta(days=now.weekday())
        return TimeRange(
            start=start_of_day(monday),
            end=now.timestamp(),
        )

    return None


def range_from_match(matched_text: str, resolved_dt: datetime, now: datetime) -> TimeRange:
    text = matched_text.strip()

    if _HOUR_HINT_RE.search(text):
        return TimeRange(
            start=resolved_dt.timestamp(),
            end=now.timestamp(),
        )

    if _WEEK_HINT_RE.search(text) and not _WEEKDAY_SPECIFIC_RE.search(text):
        monday = resolved_dt - timedelta(days=resolved_dt.weekday())
        sunday = monday + timedelta(days=6)
        return TimeRange(
            start=start_of_day(monday),
            end=min(end_of_day(sunday), now.timestamp()),
        )

    if _MONTH_HINT_RE.search(text) and not _DAY_NUMBER_SUFFIX_RE.search(text):
        first = resolved_dt.replace(day=1)
        last_day_num = calendar.monthrange(resolved_dt.year, resolved_dt.month)[1]
        end_dt = resolved_dt.replace(day=last_day_num)
        return TimeRange(
            start=start_of_day(first),
            end=min(end_of_day(end_dt), now.timestamp()),
        )

    return day_range(resolved_dt)


def day_range(dt: datetime) -> TimeRange:
    return TimeRange(
        start=start_of_day(dt),
        end=end_of_day(dt),
    )


def month_range(*, year: int, month: int, now: datetime) -> TimeRange:
    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    last_day_num = calendar.monthrange(year, month)[1]
    month_end = datetime(year, month, last_day_num, tzinfo=timezone.utc)
    return TimeRange(
        start=start_of_day(month_start),
        end=min(end_of_day(month_end), now.timestamp()),
    )


def start_of_day(dt: datetime) -> float:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def end_of_day(dt: datetime) -> float:
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp()


def reparse_with_stripped_preposition(
    results: list[tuple[str, Any]],
    settings: dict[str, Any],
    now: datetime,
) -> list[tuple[str, datetime]]:
    import dateparser

    past: list[tuple[str, datetime]] = []
    for matched_text, _ in results:
        stripped = _LEADING_PREP_RE.sub("", matched_text)
        if stripped == matched_text:
            continue
        retry_dt = dateparser.parse(stripped, settings=settings)
        if retry_dt is None:
            continue
        dt_utc = retry_dt.replace(tzinfo=timezone.utc)
        if dt_utc <= now:
            past.append((stripped, dt_utc))
            logger.debug(
                "Temporal reparse succeeded: %r -> %r -> %s",
                matched_text, stripped, retry_dt,
            )
    return past
