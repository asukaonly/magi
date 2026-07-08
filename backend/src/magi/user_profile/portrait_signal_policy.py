"""Shared qualification rules for user portrait projection signals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

PortraitAssertionRole = Literal["world", "review", "recent", "skip"]
PortraitClaimKind = Literal[
    "identity_fact",
    "active_work",
    "preference_interest",
    "collaboration_style",
    "recent_context",
    "inventory_signal",
]
PortraitWorldGroup = Literal["identity", "projects", "preferences", "work_style"]


@dataclass(frozen=True)
class PortraitSignalDecision:
    """Decision for how a memory signal can appear in the user portrait."""

    role: PortraitAssertionRole
    claim_kind: PortraitClaimKind
    world_group: PortraitWorldGroup | None = None

PORTRAIT_WORLD_STATES = frozenset({"stable", "confirmed", "corroborated", "validated"})
PORTRAIT_REVIEW_STATES = frozenset({"tentative", "contradicted"})
PORTRAIT_RECENT_FAMILIES = frozenset({"state_profile", "mood", "stress", "engagement"})
PORTRAIT_WORLD_GROUP_IDS: tuple[PortraitWorldGroup, ...] = (
    "identity",
    "projects",
    "preferences",
    "work_style",
)

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

# Admission rules for graph relationships. Passive graph edges are recent clues,
# not stable portrait worldview. Durable portrait items must come from qualified
# assertions or explicit user profile fields.
PORTRAIT_GRAPH_SIGNAL_RULES: dict[str, dict[str, Any]] = {
    "INTERESTED_IN": {
        "role": "recent",
        "claim_kind": "preference_interest",
        "object_types": frozenset({
            "activity",
            "group",
            "media",
            "organization",
            "person",
            "product",
            "technology",
            "topic",
        }),
        "min_observations": 3,
    },
    "LIKES": {
        "role": "recent",
        "claim_kind": "preference_interest",
        "object_types": frozenset({
            "activity",
            "group",
            "media",
            "organization",
            "person",
            "product",
            "technology",
            "topic",
        }),
        "min_observations": 2,
    },
    "LISTENED": {
        "role": "recent",
        "claim_kind": "preference_interest",
        "object_types": frozenset({"group", "media", "person"}),
        "min_observations": 3,
    },
    "WORKS_WITH": {
        "role": "recent",
        "claim_kind": "active_work",
        "object_types": frozenset({"organization", "product", "software", "technology", "topic"}),
        "min_observations": 2,
    },
    "COMMITTED": {
        "role": "recent",
        "claim_kind": "active_work",
        "object_types": frozenset({"organization", "product", "software", "technology", "topic"}),
        "min_observations": 2,
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
        "project.",
        "focus.",
    ),
    "routine_profile": (
        "routine.",
        "habit.",
        "project.",
        "workflow.",
        "focus.",
    ),
}
_WORLD_FAMILY_EXACT_TRAITS = {
    "preference_profile": frozenset({"preference", "taste_preference"}),
    "routine_profile": frozenset({"routine", "habit", "project", "workflow"}),
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
    return classify_assertion_portrait(assertion).role


def classify_assertion_portrait(assertion: Mapping[str, Any]) -> PortraitSignalDecision:
    """Classify an L2 assertion into a portrait role and optional world group."""
    family = _text(assertion.get("trait_family")).casefold()
    trait_name = _text(assertion.get("trait_name")).casefold()
    claim_kind = _claim_kind_for_assertion(family=family, trait_name=trait_name)
    state = _assertion_state(assertion)
    if state in PORTRAIT_REVIEW_STATES:
        return PortraitSignalDecision(role="review", claim_kind=claim_kind)
    if family in PORTRAIT_RECENT_FAMILIES:
        return PortraitSignalDecision(role="recent", claim_kind="recent_context")
    if _assertion_is_portrait_world_ready(
        assertion,
        family=family,
        trait_name=trait_name,
        claim_kind=claim_kind,
    ):
        return PortraitSignalDecision(
            role="world",
            claim_kind=claim_kind,
            world_group=_world_group_for_claim_kind(claim_kind),
        )
    return PortraitSignalDecision(role="skip", claim_kind=claim_kind)


def assertion_is_portrait_world_ready(assertion: Mapping[str, Any]) -> bool:
    """Decide whether an assertion is strong enough to become portrait worldview."""
    return classify_assertion_portrait(assertion).role == "world"


def _assertion_is_portrait_world_ready(
    assertion: Mapping[str, Any],
    *,
    family: str,
    trait_name: str,
    claim_kind: PortraitClaimKind,
) -> bool:
    family = _text(assertion.get("trait_family")).casefold()
    state = _assertion_state(assertion)
    if state not in PORTRAIT_WORLD_STATES:
        return False
    if _world_group_for_claim_kind(claim_kind) is None:
        return False
    if family not in _WORLD_FAMILY_TRAIT_PREFIXES:
        return False
    if not _trait_matches_family(
        family=family,
        trait_name=trait_name,
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


def classify_graph_portrait_signal(
    *,
    predicate: str,
    object_type: str,
    observation_count: int,
) -> PortraitSignalDecision | None:
    """Return how a graph relationship may appear in the portrait, or None.

    Graph relationships only become recent clues here. Promotion to stable
    world items happens through assertions after the L2 pipeline has made a
    qualified judgement.
    """
    rule = PORTRAIT_GRAPH_SIGNAL_RULES.get(_text(predicate).upper())
    if rule is None:
        return None
    if observation_count < int(rule["min_observations"]):
        return None
    if _text(object_type).casefold() not in rule["object_types"]:
        return None
    return PortraitSignalDecision(
        role=cast(PortraitAssertionRole, str(rule["role"])),
        claim_kind=cast(PortraitClaimKind, str(rule["claim_kind"])),
        world_group=None,
    )


def _claim_kind_for_assertion(*, family: str, trait_name: str) -> PortraitClaimKind:
    if family == "identity_profile" and trait_name.startswith("identity."):
        return "identity_fact"
    if family == "communication_profile" and trait_name.startswith("communication."):
        return "collaboration_style"
    if family == "preference_profile":
        if trait_name.startswith(("project.", "current_project", "focus_project", "focus.")):
            return "active_work"
        if trait_name.startswith(("interest.", "preference.", "taste.", "music.", "game.")):
            return "preference_interest"
    if family == "routine_profile":
        if trait_name.startswith(("project.", "current_project", "focus_project", "focus.")):
            return "active_work"
        if trait_name.startswith(("routine.", "habit.", "workflow.")) or trait_name in {
            "routine",
            "habit",
            "workflow",
        }:
            return "collaboration_style"
    if family in PORTRAIT_RECENT_FAMILIES:
        return "recent_context"
    return "inventory_signal"


def _world_group_for_claim_kind(claim_kind: PortraitClaimKind) -> PortraitWorldGroup | None:
    if claim_kind == "identity_fact":
        return "identity"
    if claim_kind == "active_work":
        return "projects"
    if claim_kind == "preference_interest":
        return "preferences"
    if claim_kind == "collaboration_style":
        return "work_style"
    return None


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
    "PORTRAIT_GRAPH_SIGNAL_RULES",
    "PORTRAIT_RECENT_FAMILIES",
    "PORTRAIT_REVIEW_STATES",
    "PORTRAIT_SOURCE_STRENGTH",
    "PORTRAIT_VALIDATION_STRENGTH",
    "PORTRAIT_WORLD_STATES",
    "PORTRAIT_WORLD_GROUP_IDS",
    "PortraitAssertionRole",
    "PortraitClaimKind",
    "PortraitSignalDecision",
    "PortraitWorldGroup",
    "assertion_is_portrait_world_ready",
    "assertion_portrait_role",
    "classify_assertion_portrait",
    "classify_graph_portrait_signal",
]
