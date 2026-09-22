"""Typed query-time meaning with host-owned evidence checks and calendar math."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from magi.memory.l2.calendar_expression import ClaimCalendarExpression
from magi.memory.l2.pipeline.temporal_expressions import resolve_calendar_expression

from .models import TimeRange

_CALENDAR_MODES = frozenset({"during", "as_of", "since", "before", "after"})
_ROLLING_SECONDS = {"minute": 60, "hour": 3600, "day": 86400, "week": 604800}


@dataclass(frozen=True, slots=True)
class QueryTemporalJudgment:
    """A semantic restriction, not permission to choose host time or timezone."""

    kind: Literal["none", "calendar", "rolling_window"]
    raw_expression: str | None = None
    expression: ClaimCalendarExpression | None = None
    mode: str | None = None
    boundary: str | None = None
    unit: str | None = None
    count: int | None = None

    @classmethod
    def from_dict(cls, value: object) -> QueryTemporalJudgment | None:
        """Reject malformed or unsupported judgments without a language fallback."""
        if not isinstance(value, dict):
            return None
        if value == {"kind": "none"}:
            return cls(kind="none")
        raw = value.get("raw_expression")
        if not isinstance(raw, str) or not raw.strip():
            return None
        if value.get("kind") == "rolling_window":
            unit, count = value.get("unit"), value.get("count")
            if set(value) != {"kind", "raw_expression", "unit", "count"}:
                return None
            if not isinstance(unit, str) or unit not in _ROLLING_SECONDS:
                return None
            if type(count) is not int or not 1 <= count <= 10000:
                return None
            return cls(kind="rolling_window", raw_expression=raw, unit=unit, count=count)
        mode, boundary = value.get("mode"), value.get("boundary")
        if (
            value.get("kind") != "calendar"
            or not isinstance(mode, str)
            or mode not in _CALENDAR_MODES
        ):
            return None
        expected = {"kind", "raw_expression", "expression", "mode"}
        if mode != "during":
            expected.add("boundary")
            if boundary not in ("start", "end"):
                return None
        if set(value) != expected:
            return None
        expression = ClaimCalendarExpression.from_dict(value.get("expression"))
        if expression is None or expression.kind == "at_observation":
            return None
        return cls(
            kind="calendar", raw_expression=raw, expression=expression, mode=mode, boundary=boundary
        )


def resolve_query_temporal(
    judgment: QueryTemporalJudgment | None,
    *,
    query: str,
    anchor_timestamp: float,
    timezone_id: str | None,
) -> TimeRange | None:
    """Execute an exact-span judgment against the request's frozen host context."""
    if judgment is None or judgment.kind == "none" or not math.isfinite(anchor_timestamp):
        return None
    if not judgment.raw_expression or judgment.raw_expression not in query:
        return None
    if judgment.kind == "rolling_window":
        return TimeRange(
            start=anchor_timestamp - _ROLLING_SECONDS[judgment.unit] * judgment.count,
            end=anchor_timestamp,
        )
    if not timezone_id:
        return None
    try:
        zone = ZoneInfo(timezone_id)
    except (ValueError, ZoneInfoNotFoundError):
        return None
    resolved = resolve_calendar_expression(
        judgment.expression,
        anchor_timestamp=anchor_timestamp,
        anchor_quality="exact",
        local_timezone=zone,
    )
    if resolved is None:
        return None
    start, exclusive_end = resolved.epochs
    if not math.isfinite(start) or not math.isfinite(exclusive_end) or start >= exclusive_end:
        return None
    # Retrieval APIs use inclusive bounds; preserve exclusive civil endpoints.
    inclusive_end = math.nextafter(exclusive_end, -math.inf)
    if judgment.mode == "during":
        return TimeRange(start=start, end=inclusive_end)
    if judgment.mode == "as_of":
        return TimeRange(as_of=start if judgment.boundary == "start" else inclusive_end)
    endpoint = start if judgment.boundary == "start" else exclusive_end
    if judgment.mode == "before":
        return TimeRange(end=math.nextafter(endpoint, -math.inf))
    if judgment.mode == "after":
        return TimeRange(
            start=math.nextafter(endpoint, math.inf) if judgment.boundary == "start" else endpoint
        )
    return TimeRange(start=endpoint)
