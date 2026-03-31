"""Canonical ontology helpers for unified L2 extraction."""

from __future__ import annotations

import re
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

_STRICT_PREDICATE_COMPATIBILITY: dict[str, frozenset[str]] = {
    "HAS_METRIC": frozenset({"health_metric"}),
    "LIVES_IN": frozenset({"place"}),
    "LOCATED_IN": frozenset({"place"}),
    "ON_PLATFORM": frozenset({"software"}),
    "PRESENCE_OF": frozenset({"person", "organization", "group"}),
}

OPEN_PREDICATE_CONFIDENCE_PENALTY: float = 0.7

_UPPER_SNAKE_CASE_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")


def is_valid_open_predicate(predicate: str) -> bool:
    """Return whether *predicate* is a well-formed open predicate (UPPER_SNAKE_CASE)."""
    return bool(_UPPER_SNAKE_CASE_RE.match(predicate.strip()))


_PREDICATE_SYNONYM_GROUPS: dict[str, str] = {
    "LIKES": "affinity",
    "INTERESTED_IN": "affinity",
    "FOLLOWS": "follow",
    "DISLIKES": "aversion",
    "USES": "usage",
    "WORKS_WITH": "usage",
    "VISITED": "visit",
    "ATTENDED": "visit",
    "WORKS_AT": "membership",
    "MEMBER_OF": "membership",
    "KNOWS": "acquaintance",
    "FAMILY_OF": "family",
    "PROFICIENT_IN": "skill_level",
}


def get_predicate_synonym_group(predicate: str) -> str | None:
    """Return the synonym group for a predicate, or ``None`` if ungrouped."""
    return _PREDICATE_SYNONYM_GROUPS.get(predicate.strip().upper())


def are_predicates_synonymous(a: str, b: str) -> bool:
    """Return whether two predicates belong to the same synonym group."""
    ga = get_predicate_synonym_group(a)
    gb = get_predicate_synonym_group(b)
    return ga is not None and ga == gb


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
    strict = _STRICT_PREDICATE_COMPATIBILITY.get(canonical_predicate)
    if strict is not None:
        return canonical_object_type in strict
    return canonical_object_type in ENTITY_TYPE_REGISTRY


def validate_graph_candidate(candidate: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate one graph candidate against the ontology registry.

    Core predicates are validated against the strict compatibility matrix.
    Non-core predicates are accepted if they match UPPER_SNAKE_CASE format;
    callers should apply the confidence penalty themselves.
    """

    predicate = str(candidate.get("predicate", "")).strip().upper()
    is_core = predicate in PREDICATE_REGISTRY
    if not is_core and not is_valid_open_predicate(predicate):
        return False, "invalid_predicate"
    object_type = coerce_unknown_entity_type(candidate.get("object_type"))
    if is_core and not is_predicate_compatible(predicate, object_type):
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
    "OPEN_PREDICATE_CONFIDENCE_PENALTY",
    "PREDICATE_REGISTRY",
    "are_predicates_synonymous",
    "coerce_unknown_entity_type",
    "get_predicate_synonym_group",
    "is_leaf_fact_duplicate",
    "is_predicate_compatible",
    "is_valid_entity_type",
    "is_valid_open_predicate",
    "is_valid_predicate",
    "normalize_entity_type",
    "validate_assertion_candidate",
    "validate_graph_candidate",
]
