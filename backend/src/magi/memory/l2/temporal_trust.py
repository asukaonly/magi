"""Shared clock-trust rules for L2 evidence timestamps."""

from __future__ import annotations

import math
from typing import Any

MAX_FUTURE_CLOCK_SKEW_SECONDS = 5 * 60


def normalized_event_timestamp(value: Any) -> float | None:
    """Return one finite positive evidence timestamp."""

    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(timestamp) or timestamp <= 0:
        return None
    return timestamp


def trusted_event_timestamp(value: Any, *, now: float) -> float | None:
    """Return a usable evidence timestamp inside the trusted clock window."""

    timestamp = normalized_event_timestamp(value)
    try:
        resolved_now = float(now)
    except (TypeError, ValueError):
        return None
    if timestamp is None or not math.isfinite(resolved_now):
        return None
    if timestamp > resolved_now + MAX_FUTURE_CLOCK_SKEW_SECONDS:
        return None
    return timestamp


__all__ = [
    "MAX_FUTURE_CLOCK_SKEW_SECONDS",
    "normalized_event_timestamp",
    "trusted_event_timestamp",
]
