"""Temporal SQL clause builders for L2 retrieval."""

from __future__ import annotations

import time
from typing import Any

from ..l2.assertions.state_machine import ACTIVE_VALIDATION_STATES
from .models import TemporalContext


def build_knowledge_temporal_clause(
    tc: TemporalContext | None,
    *,
    prefix: str = "",
) -> tuple[str, list[Any]]:
    """Build SQL WHERE clause fragment for knowledge_graph temporal filtering.

    Uses columns: first_observed_at, deprecated_at, expires_at, status.
    Returns (clause_fragment, params). Fragment is empty string if no filtering needed.
    """
    if tc is None or tc.mode == "none":
        return "", []

    def col(name: str) -> str:
        return f"{prefix}{name}" if prefix else name

    clauses: list[str] = []
    params: list[Any] = []
    now = time.time()

    if tc.mode == "current":
        clauses.append(f"{col('status')} = ?")
        params.append("active")
        clauses.append(f"({col('expires_at')} IS NULL OR {col('expires_at')} > ?)")
        params.append(now)

    elif tc.mode == "as_of" and tc.anchor is not None:
        clauses.append(f"{col('first_observed_at')} <= ?")
        params.append(tc.anchor)
        clauses.append(f"({col('deprecated_at')} IS NULL OR {col('deprecated_at')} > ?)")
        params.append(tc.anchor)
        clauses.append(f"({col('expires_at')} IS NULL OR {col('expires_at')} > ?)")
        params.append(tc.anchor)

    elif tc.mode == "during" and tc.start is not None and tc.end is not None:
        clauses.append(f"{col('first_observed_at')} <= ?")
        params.append(tc.end)
        clauses.append(f"{col('last_observed_at')} >= ?")
        params.append(tc.start)

    elif tc.mode == "since" and tc.start is not None:
        clauses.append(f"{col('first_observed_at')} >= ?")
        params.append(tc.start)

    elif tc.mode == "before" and tc.end is not None:
        clauses.append(f"{col('last_observed_at')} <= ?")
        params.append(tc.end)

    elif tc.mode == "after" and tc.start is not None:
        clauses.append(f"{col('first_observed_at')} >= ?")
        params.append(tc.start)

    if not clauses:
        return "", []
    return " AND ".join(clauses), params


def build_assertion_temporal_clause(
    tc: TemporalContext | None,
    *,
    prefix: str = "",
) -> tuple[str, list[Any]]:
    """Build SQL WHERE clause for tom_trait_assertions temporal filtering.

    Uses columns: first_inferred_at, last_validated_at, superseded_at, expires_at, validation_state.
    """
    if tc is None or tc.mode == "none":
        return "", []

    def col(name: str) -> str:
        return f"{prefix}{name}" if prefix else name

    clauses: list[str] = []
    params: list[Any] = []
    now = time.time()

    active_states = ACTIVE_VALIDATION_STATES

    if tc.mode == "current":
        state_ph = ", ".join("?" for _ in active_states)
        clauses.append(f"{col('validation_state')} IN ({state_ph})")
        params.extend(active_states)
        clauses.append(f"({col('expires_at')} IS NULL OR {col('expires_at')} > ?)")
        params.append(now)

    elif tc.mode == "as_of" and tc.anchor is not None:
        clauses.append(f"{col('first_inferred_at')} <= ?")
        params.append(tc.anchor)
        clauses.append(f"({col('superseded_at')} IS NULL OR {col('superseded_at')} > ?)")
        params.append(tc.anchor)
        clauses.append(f"({col('expires_at')} IS NULL OR {col('expires_at')} > ?)")
        params.append(tc.anchor)

    elif tc.mode == "during" and tc.start is not None and tc.end is not None:
        clauses.append(f"{col('first_inferred_at')} <= ?")
        params.append(tc.end)
        clauses.append(f"{col('last_validated_at')} >= ?")
        params.append(tc.start)

    elif tc.mode == "since" and tc.start is not None:
        clauses.append(f"{col('first_inferred_at')} >= ?")
        params.append(tc.start)

    elif tc.mode == "before" and tc.end is not None:
        clauses.append(f"{col('last_validated_at')} <= ?")
        params.append(tc.end)

    elif tc.mode == "after" and tc.start is not None:
        clauses.append(f"{col('first_inferred_at')} >= ?")
        params.append(tc.start)

    if not clauses:
        return "", []
    return " AND ".join(clauses), params


def build_episode_temporal_clause(
    tc: TemporalContext | None,
) -> tuple[str, list[Any]]:
    """Build SQL WHERE clause for episodes temporal filtering.

    Uses columns: time_start, time_end.
    """
    if tc is None or tc.mode == "none":
        return "", []

    clauses: list[str] = []
    params: list[Any] = []

    if tc.mode == "current":
        now = time.time()
        clauses.append("time_end >= ?")
        params.append(now - 86400)

    elif tc.mode == "as_of" and tc.anchor is not None:
        clauses.append("time_start <= ?")
        params.append(tc.anchor)
        clauses.append("time_end >= ?")
        params.append(tc.anchor)

    elif tc.mode == "during" and tc.start is not None and tc.end is not None:
        clauses.append("time_start <= ?")
        params.append(tc.end)
        clauses.append("time_end >= ?")
        params.append(tc.start)

    elif tc.mode == "since" and tc.start is not None:
        clauses.append("time_end >= ?")
        params.append(tc.start)

    elif tc.mode == "before" and tc.end is not None:
        clauses.append("time_start <= ?")
        params.append(tc.end)

    elif tc.mode == "after" and tc.start is not None:
        clauses.append("time_start >= ?")
        params.append(tc.start)

    if not clauses:
        return "", []
    return " AND ".join(clauses), params


def compute_temporal_score(
    tc: TemporalContext | None,
    *,
    first_observed: float | None = None,
    last_observed: float | None = None,
) -> float:
    """Score how well an item matches the temporal context. Returns 0.0-1.0."""
    if tc is None or tc.mode == "none":
        return 1.0

    if tc.mode == "current":
        if last_observed is None:
            return 0.5
        now = time.time()
        age_days = (now - last_observed) / 86400
        if age_days <= 7:
            return 1.0
        if age_days <= 30:
            return 0.8
        if age_days <= 90:
            return 0.6
        return 0.3

    if tc.mode == "as_of" and tc.anchor is not None:
        if first_observed is None:
            return 0.5
        if first_observed > tc.anchor:
            return 0.0
        return 1.0

    if tc.mode == "during" and tc.start is not None and tc.end is not None:
        if first_observed is None or last_observed is None:
            return 0.5
        if first_observed > tc.end or last_observed < tc.start:
            return 0.0
        overlap_start = max(first_observed, tc.start)
        overlap_end = min(last_observed, tc.end)
        window = tc.end - tc.start
        if window <= 0:
            return 1.0
        return min(1.0, (overlap_end - overlap_start) / window)

    return 1.0


__all__ = [
    "build_knowledge_temporal_clause",
    "build_assertion_temporal_clause",
    "build_episode_temporal_clause",
    "compute_temporal_score",
]
