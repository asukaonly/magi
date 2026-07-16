"""Shared helpers and protocol for L2 cognition retrieval mixins."""

from __future__ import annotations

import math
from collections.abc import Mapping
from itertools import combinations
from typing import Any, Dict, Protocol

import aiosqlite

from ...context_scope.models import context_conditions
from ..corrections.fingerprints import scope_specificity
from ..corrections.fingerprints import scope_key as correction_scope_key

SCOPED_QUERY_OVERFETCH_FACTOR = 8
SCOPED_QUERY_MIN_CANDIDATES = 32
SCOPED_QUERY_MAX_CANDIDATES = 512


def bounded_scoped_candidate_limit(limit: int) -> int:
    """Bound scope-aware SQL candidates while leaving room for slot de-dup."""
    requested = max(1, int(limit))
    if requested >= SCOPED_QUERY_MAX_CANDIDATES:
        return requested
    return min(
        SCOPED_QUERY_MAX_CANDIDATES,
        max(
            SCOPED_QUERY_MIN_CANDIDATES,
            requested * SCOPED_QUERY_OVERFETCH_FACTOR,
        ),
    )


def matching_scope_keys(context_scope: Mapping[str, Any]) -> list[str]:
    """Return indexed scope identities for every subset of a query context."""
    conditions = context_conditions(context_scope)
    keys = ["global"]
    for size in range(1, len(conditions) + 1):
        for subset in combinations(conditions, size):
            keys.append(
                correction_scope_key({"all_of": [condition.to_dict() for condition in subset]})
            )
    return keys


def select_governed_range_rows(
    rows: list[Dict[str, Any]],
    *,
    identity_field: str,
    range_start: float | None,
    range_end: float | None,
    include_expired: bool = False,
    limit: int,
) -> list[Dict[str, Any]]:
    """Select every claim version that wins for some part of a time range.

    A more specific matching scope masks a broader scope only while the more
    specific row is valid. This preserves the broader historical version before
    a scoped override starts, while preventing two concurrent scope variants
    from leaking into the same range answer.
    """

    def priority(row: Dict[str, Any]) -> tuple[int, float, str]:
        return (
            scope_specificity(row.get("scope")),
            float(row.get("updated_at") or 0.0),
            str(row.get(identity_field) or ""),
        )

    ordered = sorted(rows, key=priority, reverse=True)
    rows_by_slot: dict[str, list[Dict[str, Any]]] = {}
    for row in ordered:
        slot = str(row.get("slot_key") or row.get(identity_field) or "")
        rows_by_slot.setdefault(slot, []).append(row)

    selected: list[Dict[str, Any]] = []
    for slot_rows in rows_by_slot.values():
        covered: list[tuple[float, float]] = []
        for row in slot_rows:
            interval = _claim_range_interval(
                row,
                range_start=range_start,
                range_end=range_end,
                include_expired=include_expired,
            )
            if interval is None:
                continue
            uncovered = _subtract_covered_interval(interval, covered)
            if not uncovered:
                continue
            selected_row = dict(row)
            selected_row["_governed_range_segments"] = [
                {
                    "start": None if math.isinf(start) and start < 0 else start,
                    "end": None if math.isinf(end) and end > 0 else end,
                }
                for start, end in uncovered
            ]
            selected.append(selected_row)
            covered = _merge_intervals([*covered, interval])

    selected.sort(key=priority, reverse=True)
    return selected[: max(1, int(limit))]


def _claim_range_interval(
    row: Dict[str, Any],
    *,
    range_start: float | None,
    range_end: float | None,
    include_expired: bool,
) -> tuple[float, float] | None:
    start = float(row["valid_from"]) if row.get("valid_from") is not None else -math.inf
    end_values = [
        float(value)
        for value in (
            row.get("valid_to"),
            None if include_expired else row.get("expires_at"),
        )
        if value is not None
    ]
    end = min(end_values, default=math.inf)
    if range_start is not None:
        start = max(start, float(range_start))
    if range_end is not None:
        end = min(end, float(range_end))
    return (start, end) if start < end else None


def _subtract_covered_interval(
    interval: tuple[float, float],
    covered: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    remaining = [interval]
    for covered_start, covered_end in covered:
        next_remaining: list[tuple[float, float]] = []
        for start, end in remaining:
            if covered_end <= start or covered_start >= end:
                next_remaining.append((start, end))
                continue
            if covered_start > start:
                next_remaining.append((start, covered_start))
            if covered_end < end:
                next_remaining.append((covered_end, end))
        remaining = next_remaining
        if not remaining:
            break
    return remaining


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return merged


class L2RetrievalQueryHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...

    def _assertion_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...

    def _snapshot_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...

    def _relation_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...
