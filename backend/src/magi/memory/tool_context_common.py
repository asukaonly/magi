"""Shared helpers for compacting memory tool context."""

from __future__ import annotations

from typing import Any


def coalesce_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return normalized
    return ""


def truncate_text(text: Any, *, max_text_chars: int) -> tuple[str, bool]:
    normalized = str(text or "")
    return normalized[:max_text_chars], len(normalized) > max_text_chars


__all__ = ["coalesce_text", "truncate_text"]
