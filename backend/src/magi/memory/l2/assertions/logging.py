"""Bounded logging helpers for assertion values."""

from __future__ import annotations

from typing import Any


def assertion_value_log_preview(value: Any, *, max_chars: int = 80) -> str:
    """Return a bounded single-line assertion value for operational logs."""

    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1]}…"


__all__ = ["assertion_value_log_preview"]
