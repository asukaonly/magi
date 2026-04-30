"""Trace payload builders for L2 hybrid retrieval."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .models import L2Conditions, L2SemanticFrame


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


__all__ = ["build_l2_trace"]
