"""Time filtering helpers for L2 hybrid retrieval."""

from __future__ import annotations

from typing import Any

from .models import TimeRange


def filter_items_by_time_range(
    items: list[dict[str, Any]],
    time_range: TimeRange,
    *,
    timestamp_keys: tuple[str, ...] = ("observed_at", "first_observed_at"),
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        timestamp: float | None = None
        for key in timestamp_keys:
            raw = item.get(key)
            if raw is not None:
                try:
                    timestamp = float(raw)
                except (TypeError, ValueError):
                    continue
                break
        if timestamp is None:
            result.append(item)
            continue
        if time_range.start and timestamp < time_range.start:
            continue
        if time_range.end and timestamp > time_range.end:
            continue
        result.append(item)
    return result


__all__ = ["filter_items_by_time_range"]
