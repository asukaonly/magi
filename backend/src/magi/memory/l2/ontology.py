"""Canonical ontology helpers for unified L2 extraction."""

from __future__ import annotations

from typing import Any

ENTITY_TYPE_REGISTRY: frozenset[str] = frozenset(
    {
        "person",
        "place",
        "organization",
        "group",
        "product",
        "food",
        "software",
        "technology",
        "hardware",
        "virtual_object",
        "project",
        "activity",
        "event",
        "animal",
        "pet",
        "health_metric",
        "concept",
        "skill",
        "media",
        "topic",
        "weather_state",
        "location_state",
        "time_point",
        "session_topic",
        "presence",
        "other",
    }
)

ENTITY_TYPE_ALIASES: dict[str, str] = {
    "dish": "food",
    "drink": "food",
    "snack": "food",
    "ingredient": "food",
    "app": "software",
    "application": "software",
    "service": "software",
    "platform": "software",
    "os": "software",
    "database": "software",
    "language": "technology",
    "framework": "technology",
    "algorithm": "technology",
    "model": "technology",
    "device": "hardware",
    "console": "hardware",
    "phone": "hardware",
    "idea": "concept",
    "principle": "concept",
    "theory": "concept",
}

ASSERTION_FAMILY_ALLOWLIST: frozenset[str] = frozenset(
    {
        "stress",
        "mood",
        "engagement",
        "trigger",
        "relationship_shift",
        "group_atmosphere",
        "public_sentiment",
        "preference_profile",
        "taste_profile",
    }
)

PREDICATE_REGISTRY: frozenset[str] = frozenset(
    {
        "LIKES",
        "DISLIKES",
        "INTERESTED_IN",
        "VISITED",
        "VIEWED",
        "FOLLOWS",
        "LIVES_IN",
        "PLANS_TO",
        "ATTENDED",
        "WORKS_AT",
        "WORKS_WITH",
        "MEMBER_OF",
        "INTERACTED_WITH",
        "KNOWS",
        "FAMILY_OF",
        "USES",
        "OWNS",
        "CREATES",
        "PROFICIENT_IN",
        "HAS_METRIC",
        "ON_PLATFORM",
        "PRESENCE_OF",
        "LOCATED_IN",
    }
)

_PREDICATE_COMPATIBILITY: dict[str, frozenset[str]] = {
    "LIKES": frozenset(ENTITY_TYPE_REGISTRY - {"health_metric", "other"}),
    "DISLIKES": frozenset(ENTITY_TYPE_REGISTRY - {"health_metric", "other"}),
    "INTERESTED_IN": frozenset({"topic", "technology", "concept", "skill", "project", "activity", "media"}),
    "VISITED": frozenset({"place", "product", "event", "organization", "location_state"}),
    "VIEWED": frozenset({"media", "software", "product", "topic", "concept", "project"}),
    "FOLLOWS": frozenset({"person", "organization", "group", "topic", "media"}),
    "LIVES_IN": frozenset({"place"}),
    "PLANS_TO": frozenset({"activity", "event", "project", "place"}),
    "ATTENDED": frozenset({"activity", "event", "group", "organization"}),
    "WORKS_AT": frozenset({"organization", "group", "project"}),
    "WORKS_WITH": frozenset({"software", "technology", "hardware", "product", "person"}),
    "MEMBER_OF": frozenset({"organization", "group", "project"}),
    "INTERACTED_WITH": frozenset({"person", "group", "organization", "animal", "pet"}),
    "KNOWS": frozenset({"person"}),
    "FAMILY_OF": frozenset({"person", "pet"}),
    "USES": frozenset({"software", "hardware", "product", "technology"}),
    "OWNS": frozenset({"product", "hardware", "software", "virtual_object", "animal", "pet"}),
    "CREATES": frozenset({"project", "media", "software", "virtual_object", "concept"}),
    "PROFICIENT_IN": frozenset({"skill", "technology"}),
    "HAS_METRIC": frozenset({"health_metric"}),
    "ON_PLATFORM": frozenset({"software"}),
    "PRESENCE_OF": frozenset({"person", "organization", "group"}),
    "LOCATED_IN": frozenset({"place"}),
}


def normalize_entity_type(raw_type: str | None) -> str | None:
    """Normalize a raw entity type into the canonical ontology."""

    if raw_type is None:
        return None
    normalized = raw_type.strip().lower()
    if not normalized:
        return None
    if normalized == "none":
        return "none"
    return ENTITY_TYPE_ALIASES.get(normalized, normalized)


def coerce_unknown_entity_type(raw_type: str | None) -> str:
    """Return a canonical entity type or the fallback ``other``."""

    normalized = normalize_entity_type(raw_type)
    if normalized is None or normalized == "none":
        return "other"
    if normalized in ENTITY_TYPE_REGISTRY:
        return normalized
    return "other"


def is_valid_entity_type(entity_type: str) -> bool:
    """Return whether an entity type is one of the canonical ontology values."""

    return normalize_entity_type(entity_type) in ENTITY_TYPE_REGISTRY


def is_valid_predicate(predicate: str) -> bool:
    """Return whether a predicate is part of the canonical graph ontology."""

    return predicate.strip().upper() in PREDICATE_REGISTRY


def is_predicate_compatible(predicate: str, object_type: str) -> bool:
    """Return whether the predicate may point at the supplied object type."""

    canonical_predicate = predicate.strip().upper()
    canonical_object_type = coerce_unknown_entity_type(object_type)
    compatible_types = _PREDICATE_COMPATIBILITY.get(canonical_predicate)
    if compatible_types is None:
        return False
    return canonical_object_type in compatible_types


def validate_graph_candidate(candidate: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate one graph candidate against the ontology registry."""

    predicate = str(candidate.get("predicate", "")).strip().upper()
    if predicate not in PREDICATE_REGISTRY:
        return False, "invalid_predicate"
    object_type = coerce_unknown_entity_type(candidate.get("object_type"))
    if not is_predicate_compatible(predicate, object_type):
        return False, "invalid_object_type"
    return True, None


def validate_assertion_candidate(candidate: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate one assertion candidate against the ontology registry."""

    trait_family = str(candidate.get("trait_family", "")).strip().lower()
    if trait_family not in ASSERTION_FAMILY_ALLOWLIST:
        return False, "invalid_trait_family"
    return True, None


def is_leaf_fact_duplicate(
    graph_candidates: list[dict[str, Any]],
    assertion_candidate: dict[str, Any],
) -> bool:
    """Return whether an assertion only restates a concrete graph preference fact."""

    trait_name = str(assertion_candidate.get("trait_name", "")).strip().lower()
    trait_value = str(assertion_candidate.get("trait_value", "")).strip().lower()
    if trait_name not in {"taste_preference", "preference", "preference.food"}:
        return False
    for candidate in graph_candidates:
        predicate = str(candidate.get("predicate", "")).strip().upper()
        object_ref = str(candidate.get("object_ref", "")).strip().lower()
        object_type, _, _ = object_ref.partition(":")
        if predicate == "DISLIKES" and trait_value in {
            f"dislikes_food:{object_ref}",
            f"dislikes_{object_type}:{object_ref}" if object_type else "",
            f"dislikes:{object_ref}",
        }:
            return True
        if predicate == "LIKES" and trait_value in {
            f"likes_food:{object_ref}",
            f"likes_{object_type}:{object_ref}" if object_type else "",
            f"likes:{object_ref}",
        }:
            return True
    return False


__all__ = [
    "ASSERTION_FAMILY_ALLOWLIST",
    "ENTITY_TYPE_ALIASES",
    "ENTITY_TYPE_REGISTRY",
    "PREDICATE_REGISTRY",
    "coerce_unknown_entity_type",
    "is_leaf_fact_duplicate",
    "is_predicate_compatible",
    "is_valid_entity_type",
    "is_valid_predicate",
    "normalize_entity_type",
    "validate_assertion_candidate",
    "validate_graph_candidate",
]
