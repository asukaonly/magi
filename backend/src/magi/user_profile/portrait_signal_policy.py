"""Shared qualification rules for user portrait projection signals."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

PortraitAssertionRole = Literal["world", "review", "recent", "skip"]

PORTRAIT_WORLD_STATES = frozenset({"stable", "confirmed", "corroborated", "validated"})
PORTRAIT_REVIEW_STATES = frozenset({"tentative", "contradicted"})
PORTRAIT_RECENT_FAMILIES = frozenset({"state_profile", "mood", "stress", "engagement"})

# Single source of truth for portrait signal strength ordering. Both the
# materialized projection builder and the API fallback path rank portrait items
# by these tables, so they must never define their own competing scales.
PORTRAIT_SOURCE_STRENGTH = {
    "user_authored": 5,
    "settings_profile": 5,
    "user_profile_projection": 5,
    "user_feedback": 5,
    "conversation": 4,
    "chat": 4,
    "tom": 3,
    "knowledge_graph": 2,
    "external_activity": 1,
}
PORTRAIT_VALIDATION_STRENGTH = {
    "stable": 5,
    "confirmed": 5,
    "corroborated": 4,
    "validated": 4,
    "tentative": 1,
    "contradicted": 0,
}

# Admission rules for promoting safe L2 graph relationships into the portrait
# worldview. Keyed by predicate; an edge qualifies only when its object type is
# allowed and it has been observed at least ``min_observations`` times.
PORTRAIT_GRAPH_WORLD_RULES: dict[str, dict[str, Any]] = {
    "VISITED": {
        "group": "invariants",
        "object_types": frozenset({"place"}),
        "min_observations": 2,
    },
    "OWNS": {
        "group": "work_style",
        "object_types": frozenset({"hardware", "product"}),
        "min_observations": 2,
    },
    "USES": {
        "group": "work_style",
        "object_types": frozenset({"software", "hardware", "technology", "product"}),
        "min_observations": 3,
    },
}

_EXPLICIT_PROFILE_SOURCES = frozenset({
    "settings_profile",
    "user_feedback",
    "user_authored",
    "conversation",
    "chat",
})
_SEMANTIC_PROFILE_SOURCES = frozenset({"tom", "knowledge_graph"})
_PASSIVE_PROFILE_SOURCES = frozenset({"external_activity"})
_WORLD_FAMILY_TRAIT_PREFIXES = {
    "identity_profile": ("identity.",),
    "communication_profile": ("communication.",),
    "preference_profile": (
        "interest.",
        "preference.",
        "taste.",
        "music.",
        "game.",
    ),
    "routine_profile": (
        "routine.",
        "habit.",
        "tool.",
        "app.",
        "project.",
        "workflow.",
        "hardware.",
        "environment.",
    ),
}
_WORLD_FAMILY_EXACT_TRAITS = {
    "preference_profile": frozenset({"preference", "taste_preference"}),
    "routine_profile": frozenset({"routine", "habit", "tool", "app", "project", "workflow"}),
}
_PASSIVE_MIN_EVIDENCE_BY_FAMILY = {
    "preference_profile": 3,
    "routine_profile": 3,
}
_SEMANTIC_MIN_EVIDENCE_BY_FAMILY = {
    "identity_profile": 1,
    "communication_profile": 1,
    "preference_profile": 2,
    "routine_profile": 2,
}
_MIN_PASSIVE_CONFIDENCE = 0.5


def assertion_portrait_role(assertion: Mapping[str, Any]) -> PortraitAssertionRole:
    """Return how an assertion may participate in the product-facing portrait."""
    family = _text(assertion.get("trait_family")).casefold()
    state = _assertion_state(assertion)
    if state in PORTRAIT_REVIEW_STATES:
        return "review"
    if family in PORTRAIT_RECENT_FAMILIES:
        return "recent"
    if assertion_is_portrait_world_ready(assertion):
        return "world"
    return "skip"


def assertion_is_portrait_world_ready(assertion: Mapping[str, Any]) -> bool:
    """Decide whether an assertion is strong enough to become portrait worldview."""
    family = _text(assertion.get("trait_family")).casefold()
    state = _assertion_state(assertion)
    if state not in PORTRAIT_WORLD_STATES:
        return False
    if family not in _WORLD_FAMILY_TRAIT_PREFIXES:
        return False
    if not _trait_matches_family(
        family=family,
        trait_name=_text(assertion.get("trait_name")).casefold(),
    ):
        return False

    source = _normalize_source(_text(assertion.get("source_domain")))
    feedback = _text(assertion.get("user_feedback")).casefold()
    evidence_count = _evidence_count(assertion)
    confidence = _optional_confidence(assertion)
    if feedback == "confirmed":
        return True
    if source in _EXPLICIT_PROFILE_SOURCES:
        return True
    if source in _SEMANTIC_PROFILE_SOURCES:
        return evidence_count >= _SEMANTIC_MIN_EVIDENCE_BY_FAMILY.get(family, 2)
    if source in _PASSIVE_PROFILE_SOURCES or not source:
        if confidence is not None and confidence < _MIN_PASSIVE_CONFIDENCE:
            return False
        return evidence_count >= _PASSIVE_MIN_EVIDENCE_BY_FAMILY.get(family, 999)
    return evidence_count >= _SEMANTIC_MIN_EVIDENCE_BY_FAMILY.get(family, 2)


def graph_relation_portrait_world_group(
    *,
    predicate: str,
    object_type: str,
    observation_count: int,
) -> str | None:
    """Return the portrait world group a graph relationship qualifies for, or None.

    Centralizes the graph-to-portrait admission policy so the materialized
    projection and the API fallback path apply the same predicate, object-type,
    and observation-count gates.
    """
    rule = PORTRAIT_GRAPH_WORLD_RULES.get(_text(predicate).upper())
    if rule is None:
        return None
    if observation_count < int(rule["min_observations"]):
        return None
    if _text(object_type).casefold() not in rule["object_types"]:
        return None
    return str(rule["group"])


def _trait_matches_family(*, family: str, trait_name: str) -> bool:
    if not trait_name:
        return False
    exact = _WORLD_FAMILY_EXACT_TRAITS.get(family, frozenset())
    if trait_name in exact:
        return True
    return any(trait_name.startswith(prefix) for prefix in _WORLD_FAMILY_TRAIT_PREFIXES[family])


def _assertion_state(assertion: Mapping[str, Any]) -> str:
    return _text(assertion.get("validation_state") or assertion.get("status")).casefold()


def _evidence_count(assertion: Mapping[str, Any]) -> int:
    if "evidence_count" in assertion:
        try:
            return max(0, int(assertion["evidence_count"]))
        except (TypeError, ValueError):
            return 0
    evidence = assertion.get("evidence_events")
    if isinstance(evidence, list):
        return len(set(str(item) for item in evidence if str(item).strip()))
    return 0


def _optional_confidence(assertion: Mapping[str, Any]) -> float | None:
    value = assertion.get("confidence_score")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_source(value: str) -> str:
    return value.strip().casefold().replace("-", "_").replace(" ", "_")


def _text(value: Any) -> str:
    return str(value or "").strip()


__all__ = [
    "PORTRAIT_GRAPH_WORLD_RULES",
    "PORTRAIT_RECENT_FAMILIES",
    "PORTRAIT_REVIEW_STATES",
    "PORTRAIT_SOURCE_STRENGTH",
    "PORTRAIT_VALIDATION_STRENGTH",
    "PORTRAIT_WORLD_STATES",
    "PortraitAssertionRole",
    "assertion_is_portrait_world_ready",
    "assertion_portrait_role",
    "graph_relation_portrait_world_group",
]
