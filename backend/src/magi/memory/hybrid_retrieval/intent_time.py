"""Parse explicit caller-owned time range data without inspecting query prose."""

from __future__ import annotations

import math
import re
import time
from datetime import datetime, timezone
from typing import Any

from .models import TimeRange

_DATE_ONLY_BOUNDARY_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")
_COMMON_BOUNDARY_FORMATS = ("%Y/%m/%d", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S")


def _coerce_time_boundary(value: Any, *, boundary: str) -> float:
    if isinstance(value, bool):
        raise ValueError("Boolean values are not valid time boundaries")
    if isinstance(value, (int, float)):
        return _finite_boundary(float(value))

    text = str(value).strip()
    if not text:
        raise ValueError("Empty string is not a valid time boundary")

    try:
        number = float(text)
    except ValueError:
        pass
    else:
        return _finite_boundary(number)

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


def _finite_boundary(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("Time boundaries must be finite")
    return value


def parse_raw_time_range(raw: dict[str, Any]) -> TimeRange | None:
    """Validate an explicit range; invalid data never falls back to query prose."""
    if "as_of" in raw:
        if len(raw) != 1:
            raise ValueError("Point-in-time constraints cannot be combined with a range")
        return TimeRange(as_of=_coerce_time_boundary(raw["as_of"], boundary="end"))

    if "start" in raw or "end" in raw:
        if not set(raw) <= {"start", "end"}:
            raise ValueError("Absolute and relative time ranges cannot be combined")
        start = _coerce_time_boundary(raw["start"], boundary="start") if "start" in raw else None
        end = _coerce_time_boundary(raw["end"], boundary="end") if "end" in raw else None
        if start is not None and end is not None and start > end:
            raise ValueError("Time range start must not be after its end")
        return TimeRange(start=start, end=end)

    if set(raw) == {"relative"}:
        rel = str(raw["relative"]).strip().lower()
        match = re.fullmatch(r"(\d+)\s*([dhwm])", rel)
        if match:
            amount, unit = int(match.group(1)), match.group(2)
            if not 1 <= amount <= 10000:
                raise ValueError("Relative time range amount is out of bounds")
            seconds = {"d": 86400, "h": 3600, "w": 604800, "m": 2592000}[unit]
            now = _finite_boundary(time.time())
            return TimeRange(start=now - amount * seconds, end=now)

    return None


def start_of_day(dt: datetime) -> float:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def end_of_day(dt: datetime) -> float:
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp()
