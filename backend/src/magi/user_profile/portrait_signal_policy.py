"""Shared qualification rules for user portrait projection signals."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

PortraitAssertionRole = Literal["world", "review", "recent", "skip"]

PORTRAIT_WORLD_STATES = frozenset({"stable", "confirmed", "corroborated", "validated"})
PORTRAIT_REVIEW_STATES = frozenset({"tentative", "contradicted"})
PORTRAIT_RECENT_FAMILIES = frozenset({"state_profile", "mood", "stress", "engagement"})

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
    "PORTRAIT_RECENT_FAMILIES",
    "PORTRAIT_REVIEW_STATES",
    "PORTRAIT_WORLD_STATES",
    "PortraitAssertionRole",
    "assertion_is_portrait_world_ready",
    "assertion_portrait_role",
]
