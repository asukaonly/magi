"""Pure helper functions for L2 hybrid retrieval handling."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .models import L2Conditions, L2SemanticFrame, TimeRange


def filter_items_by_time_range(
    items: list[dict[str, Any]],
    time_range: TimeRange,
    *,
    timestamp_keys: tuple[str, ...] = ("observed_at", "first_observed_at"),
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        timestamp: float | None = None
        for key in timestamp_keys:
            raw = item.get(key)
            if raw is not None:
                try:
                    timestamp = float(raw)
                except (TypeError, ValueError):
                    continue
                break
        if timestamp is None:
            result.append(item)
            continue
        if time_range.start and timestamp < time_range.start:
            continue
        if time_range.end and timestamp > time_range.end:
            continue
        result.append(item)
    return result


def has_global_query_constraints(
    *,
    conditions: L2Conditions,
    resolved_entities: list[dict[str, str]],
    semantic_frame: L2SemanticFrame | None,
    predicate_family: str,
    query_frame: dict[str, Any],
    time_range: TimeRange | None,
    user_id: str | None,
) -> bool:
    if resolved_entities or conditions.entities:
        return True
    if conditions.predicates or conditions.trait_families or conditions.entity_types:
        return True
    if predicate_family and predicate_family != "unknown":
        return True
    if conditions.subject_hint == "self" and user_id and predicate_family != "unknown":
        return True
    if semantic_frame is not None:
        if semantic_frame.subject_scope != "none":
            return True
        if semantic_frame.query_family != "lookup":
            return True
        if semantic_frame.entity_mentions or semantic_frame.constraints:
            return True
    if query_frame.get("relationship_object_id") or query_frame.get("relationship_object_types"):
        return True
    if time_range is not None and (time_range.start is not None or time_range.end is not None):
        return True
    return False


def build_l2_trace(
    *,
    conditions: L2Conditions,
    resolved_entities: list[dict[str, str]],
    query_frame: dict[str, Any],
    predicate_family: str,
    predicates: list[str] | None,
    status_filters: list[str] | None,
    relation_direction: str,
    semantic_frame: L2SemanticFrame | None,
    target_entity_id: str | None,
    allow_global_scan: bool,
    entity_card_count: int,
    relationship_count: int,
    assertion_count: int,
    edge_vector_supplement_count: int,
) -> dict[str, Any]:
    return {
        "content_query": conditions.content_query,
        "requested_entities": [
            entity["entity_id"] for entity in resolved_entities
        ] if resolved_entities else list(conditions.entities or []),
        "subject_hint": conditions.subject_hint or "none",
        "predicate_family": predicate_family,
        "requested_entity_types": list(conditions.entity_types or []),
        "trait_families": list(conditions.trait_families or []),
        "semantic_frame": asdict(semantic_frame) if semantic_frame is not None else None,
        "include_tom_snapshot": conditions.include_tom_snapshot,
        "include_relationships": conditions.include_relationships,
        "include_assertions": conditions.include_assertions,
        "limit": conditions.limit,
        "resolved_entities": resolved_entities,
        "query_frame": query_frame,
        "predicates": predicates or [],
        "status_filters": status_filters or [],
        "relation_direction": relation_direction,
        "target_entity_id": target_entity_id,
        "relationship_object_id": query_frame["relationship_object_id"],
        "relationship_object_types": query_frame["relationship_object_types"],
        "allow_global_scan": allow_global_scan,
        "entity_card_count": entity_card_count,
        "relationship_count": relationship_count,
        "assertion_count": assertion_count,
        "edge_vector_supplement_count": edge_vector_supplement_count,
    }
