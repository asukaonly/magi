"""Map L2 extraction candidates back to per-event entity hints."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

EVENT_ID_FIELDS = ("supporting_event_ids", "evidence_event_ids", "evidence_events")
ENTITY_ID_FIELDS = ("subject_id", "object_id", "entity_id", "target_entity_id")


def _ordered_unique(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _field_values(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, Iterable):
        return list(raw)
    return [raw]


def candidate_event_ids(candidate: Mapping[str, Any]) -> list[str]:
    """Return the event ids that directly support a candidate."""
    values: list[Any] = []
    for field in EVENT_ID_FIELDS:
        values.extend(_field_values(candidate.get(field)))
    return _ordered_unique(values)


def candidate_entity_ids(candidate: Mapping[str, Any]) -> list[str]:
    """Return entity ids touched by a candidate."""
    values: list[Any] = []
    for field in ENTITY_ID_FIELDS:
        values.extend(_field_values(candidate.get(field)))
    return sorted(_ordered_unique(values))


def build_event_entity_map(candidates: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Build event_id -> entity ids from persisted L2 candidate evidence."""
    event_entities: dict[str, set[str]] = {}
    for candidate in candidates:
        entity_ids = candidate_entity_ids(candidate)
        if not entity_ids:
            continue
        for event_id in candidate_event_ids(candidate):
            event_entities.setdefault(event_id, set()).update(entity_ids)
    return {
        event_id: sorted(entity_ids)
        for event_id, entity_ids in sorted(event_entities.items())
        if entity_ids
    }


__all__ = [
    "build_event_entity_map",
    "candidate_entity_ids",
    "candidate_event_ids",
]
