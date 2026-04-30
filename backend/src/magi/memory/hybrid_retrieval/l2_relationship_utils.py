"""Relationship and assertion inference helpers for L2 retrieval."""

from __future__ import annotations

from typing import Any


def infer_status_filters(query: str) -> list[str]:
    query_lower = query.lower()
    if "冲突" in query_lower or "conflict" in query_lower:
        return ["conflicted"]
    return ["active", "conflicted"]


def infer_relation_direction(query: str) -> str:
    query_lower = query.lower()
    if "谁认识我" in query or "who knows me" in query_lower:
        return "incoming"
    if "关系" in query or "relationship" in query_lower:
        return "both"
    return "outgoing"


def infer_assertion_states(status_filters: list[str] | None) -> list[str] | None:
    if not status_filters:
        return ["stable", "corroborated", "tentative"]
    if status_filters == ["conflicted"]:
        return ["contradicted"]
    return ["stable", "corroborated", "tentative"]


def infer_trait_families(predicate_family: str) -> list[str] | None:
    if predicate_family == "preference":
        return ["preference_profile"]
    return None


def allows_object_id_filter(*, entity_type: str, direction: str) -> bool:
    return direction == "outgoing" and entity_type == "user"


def allows_object_type_filter(*, entity_type: str, direction: str) -> bool:
    return direction == "outgoing" and entity_type == "user"


def collect_candidate_subject_ids(relationships: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []
    for relationship in relationships:
        subject_id = str(relationship.get("subject_id") or "").strip()
        if subject_id and subject_id not in seen:
            seen.add(subject_id)
            candidates.append(subject_id)
    return candidates


def collect_candidate_object_ids(relationships: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []
    for relationship in relationships:
        object_id = str(relationship.get("object_id") or "").strip()
        if object_id and object_id not in seen:
            seen.add(object_id)
            candidates.append(object_id)
    return candidates


def dedupe_relationships(relationships: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for relationship in relationships:
        triple_id = str(relationship.get("triple_id") or "").strip()
        key = triple_id or (
            f"{relationship.get('subject_id')}:"
            f"{relationship.get('predicate')}:"
            f"{relationship.get('object_id')}"
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(relationship)
    return deduped


__all__ = [
    "infer_status_filters",
    "infer_relation_direction",
    "infer_assertion_states",
    "infer_trait_families",
    "allows_object_id_filter",
    "allows_object_type_filter",
    "collect_candidate_subject_ids",
    "collect_candidate_object_ids",
    "dedupe_relationships",
]
