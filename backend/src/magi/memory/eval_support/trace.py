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
                turn_id=_normalize_optional_text(event.get("turn_id", metadata.get("turn_id"))),
                score=_normalize_optional_float(event.get("score", event.get("importance_score"))),
                content=str(event.get("content") or ""),
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
        evidence_bundles=[
            dict(bundle) for bundle in (getattr(payload, "l1_evidence_bundles", []) or [])
        ],
        timeline_summary=[
            dict(item) for item in (getattr(payload, "l1_timeline_summary", []) or [])
        ],
        l2_entity_cards=[dict(card) for card in (getattr(payload, "l2_entity_cards", []) or [])],
        l2_relationships=[dict(rel) for rel in (getattr(payload, "l2_relationships", []) or [])],
        l2_assertions=[dict(a) for a in (getattr(payload, "l2_assertions", []) or [])],
        l2_episodes=[dict(ep) for ep in (getattr(payload, "l2_episodes", []) or [])],
        l2_experiences=[dict(exp) for exp in (getattr(payload, "l2_experiences", []) or [])],
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
