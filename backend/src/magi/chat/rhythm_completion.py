"""Shared validation for complete visible conversation-rhythm responses."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import TypeVar

from .contracts import ChatMessageRecord

MAX_RHYTHM_SEGMENT_COUNT = 64
_T = TypeVar("_T")


def _strict_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            parsed = int(normalized)
        except ValueError:
            return None
        if normalized not in {str(parsed), f"+{parsed}"}:
            return None
        return parsed
    return None


def _complete_rhythm_items(
    items: Iterable[tuple[_T, str]],
    *,
    expected_count: int | None,
) -> dict[int, _T] | None:
    normalized_expected_count: int | None = None
    if expected_count is not None:
        normalized_expected_count = _strict_int(expected_count)
        if normalized_expected_count is None:
            return None
        if not 1 <= normalized_expected_count <= MAX_RHYTHM_SEGMENT_COUNT:
            return None

    by_index: dict[int, _T] = {}
    declared_count: int | None = None
    item_count = 0
    for item, payload_json in items:
        item_count += 1
        try:
            payload = json.loads(payload_json or "{}")
            rhythm = payload["rhythm"]
            segment_count = _strict_int(rhythm["segment_count"])
            segment_index = _strict_int(rhythm["segment_index"])
        except (KeyError, TypeError, json.JSONDecodeError):
            return None
        if segment_count is None or segment_index is None:
            return None
        if not 1 <= segment_count <= MAX_RHYTHM_SEGMENT_COUNT:
            return None
        if declared_count is None:
            declared_count = segment_count
        elif segment_count != declared_count:
            return None
        if (
            segment_index < 0
            or segment_index >= segment_count
            or segment_index in by_index
        ):
            return None
        by_index[segment_index] = item

    if declared_count is None:
        return None
    if (
        normalized_expected_count is not None
        and declared_count != normalized_expected_count
    ):
        return None
    if item_count != declared_count:
        return None
    if set(by_index) != set(range(declared_count)):
        return None
    return by_index


def complete_rhythm_payloads(
    payload_jsons: Iterable[str],
    *,
    expected_count: int | None = None,
) -> bool:
    """Return whether final visible segment payloads form one complete rhythm."""

    return (
        _complete_rhythm_items(
            enumerate(payload_jsons),
            expected_count=expected_count,
        )
        is not None
    )


def complete_visible_rhythm_segments(
    messages: Iterable[ChatMessageRecord],
    *,
    turn_id: str,
    expected_count: int | None = None,
) -> list[ChatMessageRecord] | None:
    """Return ordered segments only when one visible rhythm is complete."""

    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_turn_id:
        return None
    segments = [
        message
        for message in messages
        if message.turn_id == normalized_turn_id
        and message.role == "assistant"
        and message.message_kind == "assistant_rhythm_segment"
        and message.is_visible
        and message.is_final
    ]
    if not segments:
        return None

    by_index = _complete_rhythm_items(
        (
            (segment, segment.payload_json)
            for segment in segments
        ),
        expected_count=expected_count,
    )
    if by_index is None:
        return None
    return [by_index[index] for index in range(len(by_index))]


__all__ = [
    "MAX_RHYTHM_SEGMENT_COUNT",
    "complete_rhythm_payloads",
    "complete_visible_rhythm_segments",
]
