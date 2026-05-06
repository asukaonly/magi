"""Shared runtime trace identifier helpers."""

from __future__ import annotations

from typing import Any


def normalize_turn_id(turn_id: object) -> str:
    return str(turn_id or "").strip()


def build_trace_id(turn_id: object) -> str:
    normalized_turn_id = normalize_turn_id(turn_id)
    return f"trace:{normalized_turn_id}" if normalized_turn_id else ""


def build_root_span_id(turn_id: object) -> str:
    normalized_turn_id = normalize_turn_id(turn_id)
    return f"{normalized_turn_id}:turn" if normalized_turn_id else ""


def enrich_event_context_with_turn_trace(
    event_context: dict[str, Any] | None,
    *,
    turn_id: object | None = None,
) -> dict[str, Any]:
    """Add deterministic turn trace identifiers to an LLM event context."""
    context = dict(event_context or {})
    normalized_turn_id = normalize_turn_id(
        turn_id if turn_id is not None else context.get("turn_id")
    )
    if not normalized_turn_id:
        return context
    context["turn_id"] = normalized_turn_id
    context.setdefault("trace_id", build_trace_id(normalized_turn_id))
    context.setdefault("parent_span_id", build_root_span_id(normalized_turn_id))
    return context


__all__ = [
    "normalize_turn_id",
    "build_trace_id",
    "build_root_span_id",
    "enrich_event_context_with_turn_trace",
]
