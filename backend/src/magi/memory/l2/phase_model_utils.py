"""Shared normalization helpers for L2 phase model contracts."""

from __future__ import annotations


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["_optional_text"]
