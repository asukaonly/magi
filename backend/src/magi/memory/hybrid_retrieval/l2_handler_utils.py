"""Pure helper functions for L2 hybrid retrieval handling."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .models import L2Conditions, L2SemanticFrame, SemanticConstraint, TimeRange


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


def allows_object_id_filter(*, entity_type: str, direction: str) -> bool:
    return direction == "outgoing" and entity_type == "user"


def allows_object_type_filter(*, entity_type: str, direction: str) -> bool:
    return direction == "outgoing" and entity_type == "user"


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
