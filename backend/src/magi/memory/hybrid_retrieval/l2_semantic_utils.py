"""Semantic-frame helper functions for L2 hybrid retrieval."""

from __future__ import annotations

from .models import L2SemanticFrame, SemanticConstraint


def predicates_for_semantic_frame(semantic_frame: L2SemanticFrame) -> list[str]:
    if semantic_frame.query_family == "affinity" and semantic_frame.answer_kind == "creator":
        return ["FOLLOWS", "LIKES", "DISLIKES", "INTERESTED_IN"]
    if semantic_frame.query_family == "affinity" and semantic_frame.answer_kind == "place":
        return ["VISITED", "LIKES", "DISLIKES"]
    if semantic_frame.query_family == "affinity" and semantic_frame.answer_kind == "software":
        return ["USES", "LIKES", "DISLIKES"]
    if semantic_frame.query_family == "affinity" and semantic_frame.answer_kind == "topic":
        return ["INTERESTED_IN", "LIKES", "DISLIKES"]
    return []


def find_constraint(
    constraints: list[SemanticConstraint],
    *,
    scope: str,
    facet: str,
) -> SemanticConstraint | None:
    for constraint in constraints:
        if constraint.scope == scope and constraint.facet == facet:
            return constraint
    return None


def select_semantic_target_entity_id(
    *,
    semantic_frame: L2SemanticFrame,
    resolved_entities: list[dict[str, str]],
) -> str | None:
    expected_type = semantic_frame.answer_kind
    for entity in resolved_entities:
        entity_type = str(entity.get("entity_type") or "").strip()
        if entity_type != expected_type:
            continue
        if str(entity.get("match_source") or "") == "vector":
            continue
        entity_id = str(entity.get("entity_id") or "").strip()
        if entity_id:
            return entity_id
    return None


__all__ = [
    "predicates_for_semantic_frame",
    "find_constraint",
    "select_semantic_target_entity_id",
]
