"""Natural-language time parsing helpers for retrieval intent decisions."""
from __future__ import annotations

import calendar
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from magi.utils.diagnostic_logging import full_content_logging_enabled

from .models import TimeRange

logger = logging.getLogger(__name__)

_RECENTLY_KEYWORDS: list[str] = ["最近", "recently", "近期"]

# Precise "最近 N 单位 / past N units" patterns. They take priority over the
# bare "最近 → 7 days" fallback so "最近 1 小时" stops collapsing to a week.
_ZH_RECENT_QUANTITY_RE = re.compile(
    r"最近\s*(\d+)\s*(分钟|小时|天|周|个月|月)"
)
_EN_RECENT_QUANTITY_RE = re.compile(
    r"(?:in\s+the\s+)?(?:past|last|recent(?:ly)?)\s+(\d+)\s+(minute|hour|day|week|month)s?",
    re.IGNORECASE,
)
_RECENT_QUANTITY_UNIT_SECONDS: dict[str, int] = {
    "分钟": 60,
    "小时": 3600,
    "天": 86400,
    "周": 604800,
    "月": 2592000,
    "个月": 2592000,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2592000,
}

_ZH_YEAR_MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{2}|\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[号日]")
_ZH_YEAR_MONTH_RE = re.compile(r"(?<!\d)(\d{2}|\d{4})\s*年\s*(\d{1,2})\s*月(?!\s*\d\s*[号日])")
_ZH_YEAR_RE = re.compile(r"(?<!\d)(\d{2}|\d{4})\s*年(?!\s*(?:前|后|\d{1,2}\s*月))")
_ZH_RELATIVE_RE = re.compile(r"\d+\s*(?:天|小时|周|个?月|年)前")
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
_DATE_ONLY_BOUNDARY_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")
_EN_YEAR_MONTH_NUMERIC_RE = re.compile(r"(?<!\d)(\d{4})[-/](\d{1,2})(?![-/]\d)")
_EN_MONTH_NAME_RE = re.compile(
    r"\b("
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?"
    r")\.?\s+(\d{4})\b"
    r"|\b(\d{4})\s+("
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?"
    r")\.?\b",
    re.IGNORECASE,
)
_EN_PREPOSITIONAL_YEAR_RE = re.compile(
    r"\b(?:in|from|during|since|year)\s+'?(\d{2}|\d{4})\b(?!\s*(?:years?|yrs?)\b)",
    re.IGNORECASE,
)
_EN_STANDALONE_FOUR_DIGIT_YEAR_RE = re.compile(r"(?<![-/\d])((?:19|20)\d{2})(?![-/\d])")
_MONTH_NAME_TO_NUMBER: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_COMMON_BOUNDARY_FORMATS: tuple[str, ...] = (
    "%Y/%m/%d",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)


def parse_time_range(query: str, raw_time_range: dict[str, Any] | None) -> TimeRange | None:
    if raw_time_range:
        parsed = parse_raw_time_range(raw_time_range)
        if parsed is not None:
            return parsed
    return parse_time_from_query(query)


def _coerce_time_boundary(value: Any, *, boundary: str) -> float:
    if isinstance(value, bool):
        raise ValueError("Boolean values are not valid time boundaries")
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        raise ValueError("Empty string is not a valid time boundary")

    try:
        return float(text)
    except ValueError:
        pass

    normalized = f"{text[:-1]}+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
        for fmt in _COMMON_BOUNDARY_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            try:
                from dateparser import parse as dp_parse
            except ImportError as exc:
                raise ValueError(
                    f"Invalid time boundary {value!r}; expected unix seconds, ISO8601, or common date/time text"
                ) from exc

            parsed = dp_parse(text, languages=["en", "zh"])
            if parsed is None:
                raise ValueError(
                    f"Invalid time boundary {value!r}; expected unix seconds, ISO8601, or common date/time text"
                )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if _DATE_ONLY_BOUNDARY_RE.fullmatch(text):
        if boundary == "end":
            return end_of_day(parsed)
        return start_of_day(parsed)
    return parsed.timestamp()


def parse_raw_time_range(raw: dict[str, Any]) -> TimeRange | None:
    if "as_of" in raw:
        return TimeRange(as_of=_coerce_time_boundary(raw["as_of"], boundary="end"))

    if "start" in raw or "end" in raw:
        start = _coerce_time_boundary(raw["start"], boundary="start") if "start" in raw else None
        end = _coerce_time_boundary(raw["end"], boundary="end") if "end" in raw else None
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

    explicit_recent = _parse_recent_quantity(query, now)
    if explicit_recent is not None:
        return explicit_recent

    if any(keyword in query_lower for keyword in _RECENTLY_KEYWORDS):
        return TimeRange(
            start=(now - timedelta(days=7)).timestamp(),
            end=now.timestamp(),
        )

    zh_result = try_chinese_temporal(query, now)
    if zh_result is not None:
        return zh_result

    en_result = try_english_explicit_temporal(query, now)
    if en_result is not None:
        return en_result

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
        logger.debug(
            "dateparser.search_dates failed for query=%r",
            query if full_content_logging_enabled() else "[content omitted]",
        )
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


def _parse_recent_quantity(query: str, now: datetime) -> TimeRange | None:
    """Resolve "最近 N 单位" / "in the past N units" into a TimeRange.

    Returns None when no precise quantity is found so callers can fall
    back to broader keyword rules. Only digit quantities are recognized;
    spellings like "最近一周" intentionally fall through to the bare
    "最近" → 7-day default to keep the rule surface narrow.
    """
    for pattern in (_ZH_RECENT_QUANTITY_RE, _EN_RECENT_QUANTITY_RE):
        match = pattern.search(query)
        if match is None:
            continue
        try:
            amount = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        unit_key = match.group(2).lower()
        seconds = _RECENT_QUANTITY_UNIT_SECONDS.get(unit_key)
        if seconds is None:
            continue
        end_ts = now.timestamp()
        return TimeRange(start=end_ts - amount * seconds, end=end_ts)
    return None


def try_chinese_temporal(query: str, now: datetime) -> TimeRange | None:
    match = _ZH_YEAR_MONTH_DAY_RE.search(query)
    if match:
        year = _resolve_numeric_year(match.group(1), now)
        month, day = int(match.group(2)), int(match.group(3))
        if year is not None:
            try:
                return day_range(datetime(year, month, day, tzinfo=timezone.utc))
            except ValueError:
                pass

    match = _ZH_YEAR_MONTH_RE.search(query)
    if match:
        year = _resolve_numeric_year(match.group(1), now)
        month = int(match.group(2))
        if year is not None and 1 <= month <= 12:
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

    match = _ZH_YEAR_RE.search(query)
    if match:
        year = _resolve_numeric_year(match.group(1), now)
        if year is not None:
            return year_range(year=year, now=now)

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


def try_english_explicit_temporal(query: str, now: datetime) -> TimeRange | None:
    match = _EN_YEAR_MONTH_NUMERIC_RE.search(query)
    if match:
        year = _resolve_numeric_year(match.group(1), now)
        month = int(match.group(2))
        if year is not None and 1 <= month <= 12:
            return month_range(year=year, month=month, now=now)

    match = _EN_MONTH_NAME_RE.search(query)
    if match:
        month_text = (match.group(1) or match.group(4) or "").lower().rstrip(".")
        year_text = match.group(2) or match.group(3)
        year = _resolve_numeric_year(year_text, now)
        month = _MONTH_NAME_TO_NUMBER.get(month_text)
        if year is not None and month is not None:
            return month_range(year=year, month=month, now=now)

    match = _EN_PREPOSITIONAL_YEAR_RE.search(query)
    if match:
        year = _resolve_numeric_year(match.group(1), now)
        if year is not None:
            return year_range(year=year, now=now)

    match = _EN_STANDALONE_FOUR_DIGIT_YEAR_RE.search(query)
    if match:
        year = _resolve_numeric_year(match.group(1), now)
        if year is not None:
            return year_range(year=year, now=now)

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


def year_range(*, year: int, now: datetime) -> TimeRange:
    year_start = datetime(year, 1, 1, tzinfo=timezone.utc)
    year_end = datetime(year, 12, 31, tzinfo=timezone.utc)
    return TimeRange(
        start=start_of_day(year_start),
        end=min(end_of_day(year_end), now.timestamp()),
    )


def _resolve_numeric_year(text: str | None, now: datetime) -> int | None:
    if text is None:
        return None
    stripped = str(text).strip()
    if not stripped.isdigit() or len(stripped) not in {2, 4}:
        return None

    value = int(stripped)
    if len(stripped) == 4:
        year = value
    else:
        century = (now.year // 100) * 100
        year = century + value
        if year > now.year:
            year -= 100

    if year < 1900 or year > now.year:
        return None
    return year


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
