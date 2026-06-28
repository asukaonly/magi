"""Trace helpers for grounding-filter outcomes."""

from __future__ import annotations

from typing import Any


def degraded_trace(input_count: int, *, reason: str, elapsed_ms: float) -> dict[str, Any]:
    return {
        "applied": False,
        "degraded_reason": reason,
        "input_count": input_count,
        "elapsed_ms": round(elapsed_ms, 1),
    }


def compat_l2_trace(main_trace: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal grounding_filter_l2 alias from the main degraded trace."""
    result: dict[str, Any] = {"applied": False}
    if "input_count" in main_trace:
        result["input_count"] = main_trace["input_count"]
    if "degraded_reason" in main_trace:
        result["degraded_reason"] = main_trace["degraded_reason"]
    if "elapsed_ms" in main_trace:
        result["elapsed_ms"] = main_trace["elapsed_ms"]
    return result


__all__ = ["compat_l2_trace", "degraded_trace"]
