"""Shared qualification rules for user portrait projection signals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ..memory.l2.semantic_routing import ROUTE_CONTRACT_VERSION
from .portrait_values import display_value

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


@dataclass(frozen=True, slots=True)
class TentativePortraitClaimDecision:
    """A routed self-report that may enter the portrait prompt tentatively."""

    family: str
    trait_code: str
    slot_key: str
    value_fingerprint: str
    statement: str


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

TENTATIVE_PORTRAIT_CLAIM_FAMILIES = frozenset(
    {
        "communication_profile",
        "identity_profile",
        "interest_profile",
        "preference_profile",
    }
)

_IDENTITY_CLAIM_LABELS = {
    "identity.real_name": "真实姓名是",
    "identity.birth_date": "生日是",
    "identity.birth_year": "出生年份是",
    "identity.age.stated": "年龄是",
}
_COMMUNICATION_CLAIM_LABELS = {
    "communication.address.preferred": "希望被称呼为",
    "communication.address.disallowed": "不希望被称呼为",
    "communication.response_style.preferred": "偏好的沟通方式是",
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


def classify_tentative_portrait_claim(
    claim: Mapping[str, Any],
    route_outcome: Mapping[str, Any],
) -> TentativePortraitClaimDecision | None:
    """Admit and render one Claim using only typed Claim and host route fields."""

    if _text(claim.get("availability")).casefold() != "active":
        return None
    if _text(route_outcome.get("target_kind")).casefold() != "route":
        return None
    if _text(route_outcome.get("outcome")).casefold() != "routed":
        return None
    try:
        route_contract_version = int(route_outcome.get("route_contract_version") or 0)
    except (TypeError, ValueError):
        return None
    if route_contract_version != ROUTE_CONTRACT_VERSION:
        return None

    details = route_outcome.get("details")
    if not isinstance(details, Mapping):
        return None
    family = _text(details.get("family")).casefold()
    if family not in TENTATIVE_PORTRAIT_CLAIM_FAMILIES:
        return None
    trait_code = _text(details.get("trait_code")).casefold()
    slot_key = _text(route_outcome.get("target_slot_key"))
    value_fingerprint = _text(details.get("value_fingerprint"))
    if not slot_key.startswith("slt_") or not value_fingerprint.startswith("val_"):
        return None

    statement = _tentative_claim_statement(
        claim,
        family=family,
        trait_code=trait_code,
    )
    if not statement:
        return None
    return TentativePortraitClaimDecision(
        family=family,
        trait_code=trait_code,
        slot_key=slot_key,
        value_fingerprint=value_fingerprint,
        statement=statement,
    )


def tentative_portrait_prompt_line(statement: str) -> str:
    """Wrap one deterministic statement in the product uncertainty contract."""

    clean = " ".join(_text(statement).split())
    return f"用户曾自述：{clean}（尚未形成长期结论）" if clean else ""


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


def _tentative_claim_statement(
    claim: Mapping[str, Any],
    *,
    family: str,
    trait_code: str,
) -> str:
    predicate = _text(claim.get("canonical_predicate")).upper()
    value = _claim_display_value(claim)
    if not value:
        return ""
    quoted = f"「{value}」"

    if family == "preference_profile" and trait_code == "preference.affinity":
        if predicate == "LIKES":
            return f"喜欢{quoted}"
        if predicate == "DISLIKES":
            return f"不喜欢{quoted}"
        return ""
    if family == "interest_profile" and trait_code == "interest.attention":
        return f"对{quoted}感兴趣" if predicate == "INTERESTED_IN" else ""
    if family == "identity_profile":
        label = _IDENTITY_CLAIM_LABELS.get(trait_code)
        return f"{label}{quoted}" if label else ""
    if family == "communication_profile":
        label = _COMMUNICATION_CLAIM_LABELS.get(trait_code)
        return f"{label}{quoted}" if label else ""
    return ""


def _claim_display_value(claim: Mapping[str, Any]) -> str:
    value = display_value(claim.get("object_value"))
    if not value:
        value = display_value(claim.get("object_surface"))
    return " ".join(value.split())[:200]


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
    "TENTATIVE_PORTRAIT_CLAIM_FAMILIES",
    "PortraitAssertionRole",
    "PortraitClaimKind",
    "PortraitSignalDecision",
    "PortraitWorldGroup",
    "TentativePortraitClaimDecision",
    "assertion_is_portrait_world_ready",
    "assertion_portrait_role",
    "classify_tentative_portrait_claim",
    "classify_assertion_portrait",
    "tentative_portrait_prompt_line",
]
