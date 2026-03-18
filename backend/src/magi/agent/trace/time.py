"""Millisecond-safe timing helpers for chat trace instrumentation."""

from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass(slots=True)
class TraceTiming:
    """Wall-clock timestamps plus a monotonic-derived duration."""

    started_at_ms: int
    ended_at_ms: int | None
    duration_ms: int | None


def now_wall_ms() -> int:
    """Return current wall-clock time in milliseconds."""
    return time.time_ns() // 1_000_000


def build_trace_timing(
    *,
    started_at_ms: int,
    ended_at_ms: int | None,
    started_monotonic: float | None,
    ended_monotonic: float | None,
) -> TraceTiming:
    """Build normalized timing using monotonic deltas when available."""
    duration_ms: int | None = None
    if started_monotonic is not None and ended_monotonic is not None:
        duration_ms = max(0, int(round((ended_monotonic - started_monotonic) * 1000)))
    elif ended_at_ms is not None:
        duration_ms = max(0, int(ended_at_ms) - int(started_at_ms))
    return TraceTiming(
        started_at_ms=int(started_at_ms),
        ended_at_ms=int(ended_at_ms) if ended_at_ms is not None else None,
        duration_ms=duration_ms,
    )
