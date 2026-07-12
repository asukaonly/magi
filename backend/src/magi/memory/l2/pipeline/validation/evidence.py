"""Shared evidence-reference validation for L2 candidates."""

from __future__ import annotations

from ...storage.utils import normalize_event_ids


def validate_supporting_event_ids(
    candidate_event_ids: list[str] | None,
    allowed_event_ids: list[str] | None,
) -> list[str]:
    """Return exact candidate evidence only when every reference is allowed."""
    normalized = normalize_event_ids(candidate_event_ids or [])
    if not normalized:
        return []
    allowed = set(normalize_event_ids(allowed_event_ids or []))
    if not allowed or any(event_id not in allowed for event_id in normalized):
        return []
    return normalized


__all__ = ["validate_supporting_event_ids"]
