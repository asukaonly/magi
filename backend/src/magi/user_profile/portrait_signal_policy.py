"""Shared qualification rules for user portrait projection signals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

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
PORTRAIT_RECENT_TEMPORAL_SCOPES = frozenset(
    {"momentary", "session", "daily", "weekly", "recent"}
)
PORTRAIT_WORLD_TEMPORAL_SCOPES = frozenset({"stable", "persistent"})
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

_WORLD_FAMILY_TRAIT_PREFIXES = {
    "identity_profile": ("identity.",),
    "communication_profile": ("communication.",),
    "preference_profile": ("preference.", "taste."),
    "interest_profile": ("interest.",),
    "project_profile": ("project.", "focus."),
    "routine_profile": (
        "routine.",
        "habit.",
        "workflow.",
    ),
}
_WORLD_FAMILY_EXACT_TRAITS = {
    "preference_profile": frozenset({"preference", "taste_preference"}),
    "interest_profile": frozenset({"interest"}),
    "project_profile": frozenset({"project", "current_project", "focus_project"}),
    "routine_profile": frozenset({"routine", "habit", "workflow"}),
}


def assertion_portrait_role(assertion: Mapping[str, Any]) -> PortraitAssertionRole:
    """Return how an assertion may participate in the product-facing portrait."""
    return classify_assertion_portrait(assertion).role


def classify_assertion_portrait(assertion: Mapping[str, Any]) -> PortraitSignalDecision:
    """Classify an L2 assertion into a portrait role and optional world group."""
    family = _text(assertion.get("trait_family")).casefold()
    trait_name = _text(assertion.get("trait_name")).casefold()
    claim_kind = _claim_kind_for_assertion(family=family, trait_name=trait_name)
    state = _assertion_state(assertion)
    temporal_scope = _text(assertion.get("temporal_scope")).casefold()
    if state == "contradicted":
        return PortraitSignalDecision(role="review", claim_kind=claim_kind)
    if family in PORTRAIT_RECENT_FAMILIES or temporal_scope in PORTRAIT_RECENT_TEMPORAL_SCOPES:
        return PortraitSignalDecision(role="recent", claim_kind=claim_kind)
    if state in PORTRAIT_REVIEW_STATES:
        return PortraitSignalDecision(role="review", claim_kind=claim_kind)
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
    temporal_scope = _text(assertion.get("temporal_scope")).casefold()
    if temporal_scope not in PORTRAIT_WORLD_TEMPORAL_SCOPES:
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

    return True


def _claim_kind_for_assertion(*, family: str, trait_name: str) -> PortraitClaimKind:
    if family == "identity_profile" and trait_name.startswith("identity."):
        return "identity_fact"
    if family == "communication_profile" and trait_name.startswith("communication."):
        return "collaboration_style"
    if family == "preference_profile" and trait_name.startswith(("preference.", "taste.")):
        return "preference_interest"
    if family == "interest_profile" and trait_name.startswith("interest."):
        return "preference_interest"
    if family == "project_profile" and trait_name.startswith(
        ("project.", "current_project", "focus_project", "focus.")
    ):
        return "active_work"
    if family == "routine_profile":
        if trait_name.startswith(("routine.tool.", "routine.app.")):
            return "inventory_signal"
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


def _text(value: Any) -> str:
    return str(value or "").strip()


__all__ = [
    "PORTRAIT_RECENT_FAMILIES",
    "PORTRAIT_RECENT_TEMPORAL_SCOPES",
    "PORTRAIT_REVIEW_STATES",
    "PORTRAIT_SOURCE_STRENGTH",
    "PORTRAIT_VALIDATION_STRENGTH",
    "PORTRAIT_WORLD_STATES",
    "PORTRAIT_WORLD_TEMPORAL_SCOPES",
    "PORTRAIT_WORLD_GROUP_IDS",
    "PortraitAssertionRole",
    "PortraitClaimKind",
    "PortraitSignalDecision",
    "PortraitWorldGroup",
    "assertion_is_portrait_world_ready",
    "assertion_portrait_role",
    "classify_assertion_portrait",
]
