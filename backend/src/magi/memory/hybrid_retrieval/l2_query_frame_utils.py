"""L2 query frame and entity target selection helpers."""

from __future__ import annotations

from typing import Any

from .models import L2Conditions, L2SemanticFrame, TimeRange


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


def infer_target_entity_id(
    *,
    query_frame: dict[str, Any],
    predicate_family: str,
) -> str | None:
    if predicate_family != "preference":
        return None
    if query_frame["target_entity_id_exact"]:
        return str(query_frame["target_entity_id_exact"])
    return None


def make_self_entity(user_id: str) -> dict[str, str]:
    return {"entity_id": f"user:{user_id}", "entity_type": "user"}


def build_query_frame(
    *,
    conditions: L2Conditions,
    resolved_entities: list[dict[str, str]],
    predicates: list[str] | None,
    predicate_family: str,
    user_id: str | None,
    relation_direction: str,
) -> dict[str, Any]:
    explicit_entities = [dict(entity) for entity in resolved_entities]
    subject_entities: list[dict[str, str]] = []
    target_entities: list[dict[str, str]] = []
    subject_binding_source = "none"

    if conditions.subject_hint == "self" and user_id:
        subject_entities = [make_self_entity(user_id)]
        target_entities = filter_target_entities_for_family(
            entities=explicit_entities,
            predicate_family=predicate_family,
        )
        subject_binding_source = "self_anchor"
    elif conditions.subject_hint == "explicit" and explicit_entities:
        subject_entities = [dict(explicit_entities[0])]
        target_entities = filter_target_entities_for_family(
            entities=[dict(entity) for entity in explicit_entities[1:]],
            predicate_family=predicate_family,
        )
        subject_binding_source = "explicit_entity"
    elif explicit_entities:
        subject_entities = [dict(entity) for entity in explicit_entities]
        subject_binding_source = "resolved_entity"

    if relation_direction == "incoming" and user_id:
        subject_entities = [make_self_entity(user_id)]
        target_entities = explicit_entities
        subject_binding_source = "self_anchor"

    relationship_entities = subject_entities or explicit_entities
    snapshot_entities = subject_entities or explicit_entities
    assertion_entities = subject_entities or explicit_entities

    target_entity_id_exact = select_exact_target_entity_id(
        conditions=conditions,
        predicate_family=predicate_family,
        target_entities=target_entities,
    )
    relationship_object_types = select_target_entity_types(
        conditions=conditions,
        predicate_family=predicate_family,
        target_entities=target_entities,
    )
    relationship_object_id = target_entity_id_exact
    if relationship_object_id is not None and relationship_object_types:
        relationship_object_types = None

    chosen_subject_entity_id = subject_entities[0]["entity_id"] if subject_entities else None
    chosen_target_entity_id = target_entities[0]["entity_id"] if target_entities else None
    return {
        "subject_entities": subject_entities,
        "target_entities": target_entities,
        "relationship_entities": relationship_entities,
        "snapshot_entities": snapshot_entities,
        "assertion_entities": assertion_entities,
        "chosen_subject_entity_id": chosen_subject_entity_id,
        "chosen_target_entity_id": chosen_target_entity_id,
        "subject_binding_source": subject_binding_source,
        "target_entity_id_exact": target_entity_id_exact,
        "relationship_object_id": relationship_object_id,
        "relationship_object_types": relationship_object_types,
    }


def filter_target_entities_for_family(
    *,
    entities: list[dict[str, str]],
    predicate_family: str,
) -> list[dict[str, str]]:
    if predicate_family != "preference":
        return [dict(entity) for entity in entities]
    filtered = [
        dict(entity)
        for entity in entities
        if str(entity.get("entity_type") or "").strip() not in {"person", "user"}
    ]
    return filtered or [dict(entity) for entity in entities]


def select_exact_target_entity_id(
    *,
    conditions: L2Conditions,
    predicate_family: str,
    target_entities: list[dict[str, str]],
) -> str | None:
    if not target_entities:
        return None
    if predicate_family != "preference":
        return str(target_entities[0]["entity_id"])
    for entity in target_entities:
        if str(entity.get("match_source") or "") == "vector":
            continue
        if not is_generic_entity_ref(entity):
            return str(entity["entity_id"])
    return None


def select_target_entity_types(
    *,
    conditions: L2Conditions,
    predicate_family: str,
    target_entities: list[dict[str, str]],
) -> list[str] | None:
    if predicate_family != "preference" or not target_entities:
        return None
    if all(str(e.get("match_source") or "") == "vector" for e in target_entities):
        return None
    types: list[str] = []
    for entity in target_entities:
        entity_type = str(entity.get("entity_type") or "").strip()
        if entity_type and entity_type not in types:
            types.append(entity_type)
    return types or None


def is_generic_entity_ref(entity: dict[str, str]) -> bool:
    entity_id = str(entity.get("entity_id") or "")
    entity_type = str(entity.get("entity_type") or "")
    if not entity_id or not entity_type:
        return False
    _, _, suffix = entity_id.partition(":")
    if not suffix:
        return False
    normalized_suffix = suffix.replace("_", "-").casefold()
    normalized_type = entity_type.replace("_", "-").casefold()
    return normalized_suffix in normalized_type or normalized_type in normalized_suffix


__all__ = [
    "has_global_query_constraints",
    "infer_target_entity_id",
    "make_self_entity",
    "build_query_frame",
    "filter_target_entities_for_family",
    "select_exact_target_entity_id",
    "select_target_entity_types",
    "is_generic_entity_ref",
]
