"""Canonical ontology helpers for unified L2 extraction."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from .assertion_family_policy import ASSERTION_FAMILY_ALLOWLIST

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

_ASSERTION_FAMILY_ROOTS: frozenset[str] = frozenset(
    family.split("_", 1)[0] for family in ASSERTION_FAMILY_ALLOWLIST
)
_PROFILE_ASSERTION_FAMILY_ROOTS: frozenset[str] = frozenset(
    family.split("_", 1)[0]
    for family in ASSERTION_FAMILY_ALLOWLIST
    if family.endswith("_profile")
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
        "LISTENED",
        "WORKS_AT",
        "WORKS_WITH",
        "MEMBER_OF",
        "INTERACTED_WITH",
        "KNOWS",
        "FAMILY_OF",
        "USES",
        "USED",
        "EXECUTED",
        "COMMITTED",
        "CHECKED_OUT",
        "MERGED",
        "REBASED",
        "OWNS",
        "CREATES",
        "PROFICIENT_IN",
        "HAS_METRIC",
        "ON_PLATFORM",
        "PRESENCE_OF",
        "LOCATED_IN",
        "REFERENCES",
    }
)

PROFILE_SIGNAL_PREDICATES: frozenset[str] = frozenset(
    {
        "PREFERRED_FORM_OF_ADDRESS",
        "DISALLOWED_FORM_OF_ADDRESS",
        "REAL_NAME",
        "BIRTH_DATE",
        "BIRTH_YEAR",
        "STATED_AGE",
        "PREFERRED_COMMUNICATION_STYLE",
        "AGE",
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

LOW_VALUE_OPEN_PREDICATES: frozenset[str] = frozenset(
    {
        "ASKED",
        "ASKED_ABOUT",
        "DISCUSSED",
        "INQUIRED_ABOUT",
        "LOOKED_AT",
        "MENTIONED",
        "NEEDS_HELP_WITH",
        "QUESTION_ABOUT",
        "QUESTIONED_ABOUT",
        "REFERRED_TO",
        "REFERENCED",
        "REQUESTED_INFO_ABOUT",
        "SAW",
        "TALKED_ABOUT",
        "WANTS_TO_KNOW",
    }
)

VAGUE_ENTITY_REFERENCES: frozenset[str] = frozenset(
    {
        "他",
        "她",
        "它",
        "他们",
        "她们",
        "它们",
        "这个",
        "那个",
        "这",
        "那",
        "这里",
        "那里",
        "这个东西",
        "那个东西",
        "这个文件",
        "那个文件",
        "这个文档",
        "那个文档",
        "图片",
        "图",
        "截图",
        "文件",
        "文档",
        "app",
        "application",
        "pdf",
        "file",
        "document",
        "image",
        "photo",
        "screenshot",
        "it",
        "he",
        "she",
        "they",
        "this",
        "that",
        "this one",
        "that one",
        "the one",
        "one",
    }
)

_UPPER_SNAKE_CASE_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")


def is_valid_open_predicate(predicate: str) -> bool:
    """Return whether *predicate* is a well-formed open predicate (UPPER_SNAKE_CASE)."""
    return bool(_UPPER_SNAKE_CASE_RE.match(predicate.strip()))


def is_low_value_open_predicate(predicate: str | None) -> bool:
    """Return whether an open predicate describes dialogue/query behavior, not stable knowledge."""
    if predicate is None:
        return False
    return predicate.strip().upper() in LOW_VALUE_OPEN_PREDICATES


def is_vague_entity_reference(value: Any) -> bool:
    """Return whether *value* is a pronoun or generic placeholder, not a stable entity name."""
    text = str(value or "").strip()
    if not text:
        return False
    candidate = _strip_entity_prefix_for_schema_check(text).strip()
    normalized = re.sub(r"\s+", " ", candidate.casefold()).strip(
        " '\"“”‘’「」『』（）()[]{}<>《》：:，,。.!！?？"
    )
    if normalized in VAGUE_ENTITY_REFERENCES:
        return True
    return bool(
        re.fullmatch(
            r"(?:this|that|the)\s+(?:one|file|document|image|photo|screenshot|app|application|pdf)",
            normalized,
        )
    )


def is_reserved_assertion_graph_predicate(predicate: str | None) -> bool:
    """Return whether *predicate* is an assertion-family name, not a graph relation."""
    if predicate is None:
        return False
    return predicate.strip().casefold() in ASSERTION_FAMILY_ALLOWLIST


def is_profile_signal_predicate(predicate: str | None) -> bool:
    """Return whether *predicate* is a Phase 1 profile signal, not a graph relation."""
    if predicate is None:
        return False
    return predicate.strip().upper() in PROFILE_SIGNAL_PREDICATES


def is_reserved_assertion_graph_identifier(value: Any) -> bool:
    """Return whether *value* looks like an internal assertion schema identifier.

    Graph edges should point at user-world entities, not trait-family names or
    trait keys such as ``preference.address.preferred``. This guard is based on
    assertion-family namespaces instead of a list of individual leaked keys.
    """

    text = str(value or "").strip()
    if not text:
        return False
    candidate = _strip_entity_prefix_for_schema_check(text)
    first_path_segment = re.split(r"[^a-z0-9]+", candidate.casefold(), maxsplit=1)[0]
    if "." in candidate and first_path_segment in _ASSERTION_FAMILY_ROOTS:
        return True
    normalized = re.sub(r"[^a-z0-9]+", "_", candidate.casefold()).strip("_")
    if not normalized:
        return False
    if normalized in ASSERTION_FAMILY_ALLOWLIST:
        return True
    tokens = [token for token in normalized.split("_") if token]
    if len(tokens) < 2:
        return False
    if "_".join(tokens[:2]) in ASSERTION_FAMILY_ALLOWLIST:
        return True
    return len(tokens) >= 3 and tokens[0] in _PROFILE_ASSERTION_FAMILY_ROOTS


def _strip_entity_prefix_for_schema_check(value: str) -> str:
    prefix, separator, suffix = value.partition(":")
    if not separator:
        return value
    normalized_prefix = normalize_entity_type(prefix)
    if normalized_prefix in ENTITY_TYPE_REGISTRY or prefix.strip().casefold() == "user":
        return suffix
    return value


_PREDICATE_SYNONYM_GROUPS: dict[str, str] = {
    "LIKES": "affinity",
    "INTERESTED_IN": "affinity",
    "FOLLOWS": "follow",
    "DISLIKES": "aversion",
    "USES": "usage",
    "USED": "usage",
    "WORKS_WITH": "usage",
    "EXECUTED": "usage",
    "VISITED": "visit",
    "ATTENDED": "visit",
    "VIEWED": "view",
    "LISTENED": "view",
    "COMMITTED": "code_activity",
    "CHECKED_OUT": "code_activity",
    "MERGED": "code_activity",
    "REBASED": "code_activity",
    "WORKS_AT": "membership",
    "MEMBER_OF": "membership",
    "KNOWS": "acquaintance",
    "FAMILY_OF": "family",
    "PROFICIENT_IN": "skill_level",
}

FAMILY_TO_PREDICATES: dict[str, list[str]] = {
    "preference": ["LIKES", "DISLIKES", "INTERESTED_IN", "FOLLOWS"],
    "relationship": ["KNOWS", "FAMILY_OF", "INTERACTED_WITH", "MEMBER_OF"],
    "activity": [
        "VISITED",
        "ATTENDED",
        "VIEWED",
        "LISTENED",
        "USES",
        "USED",
        "EXECUTED",
        "WORKS_WITH",
        "COMMITTED",
        "CHECKED_OUT",
        "MERGED",
        "REBASED",
    ],
    "profile_fact": ["LIVES_IN", "WORKS_AT", "MEMBER_OF", "OWNS", "PROFICIENT_IN"],
    # Source-declared reference edges (e.g. Obsidian wikilinks). Own family so
    # recall expansion does not pull in unrelated activity predicates.
    "reference": ["REFERENCES"],
}


@lru_cache(maxsize=512)
def get_predicate_synonym_group(predicate: str) -> str | None:
    """Return the synonym group for a predicate, or ``None`` if ungrouped.

    Cached because reranker and validation paths call this thousands of
    times per retrieval with a tiny set of unique inputs (the predicate
    vocabulary is bounded).
    """
    return _PREDICATE_SYNONYM_GROUPS.get(predicate.strip().upper())


def expand_predicate_group(predicates: list[str]) -> list[str]:
    """Expand predicates to include all synonyms from the same synonym group."""
    expanded: set[str] = {p.strip().upper() for p in predicates}
    groups: set[str] = set()
    for pred in list(expanded):
        group = _PREDICATE_SYNONYM_GROUPS.get(pred)
        if group:
            groups.add(group)
    for other_pred, other_group in _PREDICATE_SYNONYM_GROUPS.items():
        if other_group in groups:
            expanded.add(other_pred)
    return sorted(expanded)


def predicates_for_family(family: str) -> list[str] | None:
    """Return the canonical predicate list for a retrieval family."""
    base = FAMILY_TO_PREDICATES.get(family)
    if base is None:
        return None
    return expand_predicate_group(base)


def are_predicates_synonymous(a: str, b: str) -> bool:
    """Return whether two predicates belong to the same synonym group."""
    ga = get_predicate_synonym_group(a)
    gb = get_predicate_synonym_group(b)
    return ga is not None and ga == gb


@lru_cache(maxsize=256)
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


@lru_cache(maxsize=512)
def is_valid_predicate(predicate: str) -> bool:
    """Return whether a predicate is part of the canonical graph ontology."""

    return predicate.strip().upper() in PREDICATE_REGISTRY


@lru_cache(maxsize=2048)
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
    if is_profile_signal_predicate(predicate):
        return False, "profile_signal_predicate"
    if is_reserved_assertion_graph_predicate(predicate):
        return False, "reserved_assertion_predicate"
    if is_low_value_open_predicate(predicate):
        return False, "low_value_predicate"
    for key in ("object_ref", "object_id"):
        if is_reserved_assertion_graph_identifier(candidate.get(key)):
            return False, "reserved_assertion_identifier"
        if is_vague_entity_reference(candidate.get(key)):
            return False, "vague_entity_reference"
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


__all__ = [
    "ASSERTION_FAMILY_ALLOWLIST",
    "ENTITY_TYPE_ALIASES",
    "ENTITY_TYPE_REGISTRY",
    "FAMILY_TO_PREDICATES",
    "OPEN_PREDICATE_CONFIDENCE_PENALTY",
    "PROFILE_SIGNAL_PREDICATES",
    "PREDICATE_REGISTRY",
    "are_predicates_synonymous",
    "coerce_unknown_entity_type",
    "expand_predicate_group",
    "get_predicate_synonym_group",
    "is_reserved_assertion_graph_identifier",
    "is_reserved_assertion_graph_predicate",
    "is_profile_signal_predicate",
    "is_predicate_compatible",
    "is_valid_entity_type",
    "is_valid_open_predicate",
    "is_valid_predicate",
    "normalize_entity_type",
    "predicates_for_family",
    "validate_assertion_candidate",
    "validate_graph_candidate",
]
