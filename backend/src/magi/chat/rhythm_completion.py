"""Shared validation for complete visible conversation-rhythm responses."""

from __future__ import annotations

from magi_plugin_sdk.storage_models.chat_rhythm import (
    MAX_RHYTHM_SEGMENT_COUNT,
    _T as _T,
    _strict_int as _strict_int,
    _complete_rhythm_items as _complete_rhythm_items,
    complete_rhythm_payloads,
    complete_visible_rhythm_segments,
)

__all__ = [
    "MAX_RHYTHM_SEGMENT_COUNT",
    "complete_rhythm_payloads",
    "complete_visible_rhythm_segments",
]
