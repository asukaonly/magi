"""Trace normalization helpers for eval-support memory queries."""

from __future__ import annotations

from typing import Any

from .contracts import EvalMemoryHit, EvalMemoryQueryResult


def build_eval_hits_from_payload(payload: Any) -> list[EvalMemoryHit]:
    """Convert retrieval payload data into normalized eval hits."""
    hits: list[EvalMemoryHit] = []
    for event in getattr(payload, "l1_events", []) or []:
        metadata = dict(event.get("metadata") or {})
        hits.append(
            EvalMemoryHit(
                event_id=str(event.get("event_id") or ""),
                session_id=_normalize_optional_text(event.get("session_id")),
                turn_id=_normalize_optional_text(metadata.get("turn_id")),
                score=_normalize_optional_float(
                    event.get("score", event.get("importance_score"))
                ),
                content=str(event.get("raw_content") or ""),
                metadata=metadata,
            )
        )
    return hits


def build_eval_query_result(payload: Any) -> EvalMemoryQueryResult:
    """Build a normalized eval query result from retrieval payload data."""
    trace = dict(getattr(payload, "trace", {}) or {})
    trace.setdefault("l1_hit_count", len(getattr(payload, "l1_events", []) or []))
    return EvalMemoryQueryResult(
        hits=build_eval_hits_from_payload(payload),
        trace=trace,
    )


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
