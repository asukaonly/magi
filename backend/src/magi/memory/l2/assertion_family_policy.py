"""Central assertion-family semantics for L2 cognition."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class AssertionFamilyPolicy:
    """Policy metadata shared by prompts, validation, decay, and snapshots."""

    family: str
    description: str
    phase2_guidance: str
    default_temporal_scope: str
    default_decay_policy: str
    default_ttl_seconds: float | None
    snapshot_bucket: str
    value_i18n: str


ASSERTION_FAMILY_POLICIES: dict[str, AssertionFamilyPolicy] = {
    "stress": AssertionFamilyPolicy(
        family="stress",
        description="Short-lived stress or pressure level grounded in user-authored evidence.",
        phase2_guidance="Use for current stress signals, not durable identity or preference facts.",
        default_temporal_scope="daily",
        default_decay_policy="time_window",
        default_ttl_seconds=24 * 60 * 60,
        snapshot_bucket="state",
        value_i18n="controlled",
    ),
    "mood": AssertionFamilyPolicy(
        family="mood",
        description="Short-lived emotional state.",
        phase2_guidance="Use only when the user's own words clearly indicate mood.",
        default_temporal_scope="session",
        default_decay_policy="session_decay",
        default_ttl_seconds=12 * 60 * 60,
        snapshot_bucket="state",
        value_i18n="controlled",
    ),
    "engagement": AssertionFamilyPolicy(
        family="engagement",
        description="Current attention, participation, or task engagement state.",
        phase2_guidance="Use for temporary engagement signals, not stable work habits.",
        default_temporal_scope="session",
        default_decay_policy="session_decay",
        default_ttl_seconds=12 * 60 * 60,
        snapshot_bucket="state",
        value_i18n="controlled",
    ),
    "trigger": AssertionFamilyPolicy(
        family="trigger",
        description="A stable factor that tends to cause a user state or strong reaction.",
        phase2_guidance="Use for recurring triggers with clear evidence, not one-off annoyances.",
        default_temporal_scope="stable",
        default_decay_policy="evidence_only",
        default_ttl_seconds=None,
        snapshot_bucket="sensitive_triggers",
        value_i18n="literal",
    ),
    "relationship_shift": AssertionFamilyPolicy(
        family="relationship_shift",
        description="Short-lived change in relationship state or social dynamics.",
        phase2_guidance="Use for recent relationship changes, not stable relationship topology.",
        default_temporal_scope="session",
        default_decay_policy="session_decay",
        default_ttl_seconds=6 * 60 * 60,
        snapshot_bucket="relationship",
        value_i18n="literal",
    ),
    "group_atmosphere": AssertionFamilyPolicy(
        family="group_atmosphere",
        description="Short-lived tone of a group conversation or shared context.",
        phase2_guidance="Use only when the group context is explicit.",
        default_temporal_scope="session",
        default_decay_policy="session_decay",
        default_ttl_seconds=6 * 60 * 60,
        snapshot_bucket="context",
        value_i18n="controlled",
    ),
    "public_sentiment": AssertionFamilyPolicy(
        family="public_sentiment",
        description="External or public sentiment about an entity, not the user's own preference.",
        phase2_guidance="Do not use for the user's likes or dislikes.",
        default_temporal_scope="session",
        default_decay_policy="session_decay",
        default_ttl_seconds=6 * 60 * 60,
        snapshot_bucket="public_sentiment",
        value_i18n="controlled",
    ),
    "identity_profile": AssertionFamilyPolicy(
        family="identity_profile",
        description="Stable user identity facts such as name, birthday, age, or home location.",
        phase2_guidance="Use only for explicit profile-signal facts from current user-authored text.",
        default_temporal_scope="stable",
        default_decay_policy="evidence_only",
        default_ttl_seconds=None,
        snapshot_bucket="core_traits",
        value_i18n="literal",
    ),
    "communication_profile": AssertionFamilyPolicy(
        family="communication_profile",
        description="How the user wants the assistant to address, respond to, or interact with them.",
        phase2_guidance="Use for explicit communication preferences, preserving the user's wording.",
        default_temporal_scope="stable",
        default_decay_policy="evidence_only",
        default_ttl_seconds=None,
        snapshot_bucket="core_traits",
        value_i18n="literal",
    ),
    "preference_profile": AssertionFamilyPolicy(
        family="preference_profile",
        description="Explicit likes, dislikes, affinities, and tastes.",
        phase2_guidance=(
            "Use only for actual preference claims such as LIKES or DISLIKES; "
            "do not use it for attention, activity, or project participation."
        ),
        default_temporal_scope="stable",
        default_decay_policy="evidence_only",
        default_ttl_seconds=None,
        snapshot_bucket="preferences",
        value_i18n="literal",
    ),
    "interest_profile": AssertionFamilyPolicy(
        family="interest_profile",
        description="Topics, domains, and subjects that hold the user's attention or interest.",
        phase2_guidance=(
            "Use for INTERESTED_IN or sustained engagement evidence, not as a synonym "
            "for liking something and not for a single exposure."
        ),
        default_temporal_scope="stable",
        default_decay_policy="evidence_only",
        default_ttl_seconds=None,
        snapshot_bucket="preferences",
        value_i18n="literal",
    ),
    "project_profile": AssertionFamilyPolicy(
        family="project_profile",
        description="Projects the user is actively building, maintaining, or contributing to.",
        phase2_guidance=(
            "Use for grounded project participation, not for merely viewing, mentioning, "
            "or asking about a project."
        ),
        default_temporal_scope="stable",
        default_decay_policy="evidence_only",
        default_ttl_seconds=None,
        snapshot_bucket="core_traits",
        value_i18n="literal",
    ),
    "routine_profile": AssertionFamilyPolicy(
        family="routine_profile",
        description="Stable behavior patterns and rhythms such as recurring tools, times, or habits.",
        phase2_guidance="Use for repeated behavior patterns, not a single interaction event.",
        default_temporal_scope="stable",
        default_decay_policy="evidence_only",
        default_ttl_seconds=None,
        snapshot_bucket="core_traits",
        value_i18n="literal",
    ),
    "state_profile": AssertionFamilyPolicy(
        family="state_profile",
        description="Slowly changing user state that is more durable than mood/stress/engagement.",
        phase2_guidance="Use for stable state traits; use mood/stress/engagement for temporary states.",
        default_temporal_scope="stable",
        default_decay_policy="evidence_only",
        default_ttl_seconds=None,
        snapshot_bucket="core_traits",
        value_i18n="controlled",
    ),
}

ASSERTION_FAMILY_ALLOWLIST: frozenset[str] = frozenset(ASSERTION_FAMILY_POLICIES)


def get_assertion_family_policy(family: str | None) -> AssertionFamilyPolicy | None:
    """Return the canonical policy for an assertion family."""

    key = str(family or "").strip().casefold()
    policy = ASSERTION_FAMILY_POLICIES.get(key)
    if policy is None:
        return None
    try:
        from .assertions.settings import configured_family_ttl_seconds

        ttl_seconds = configured_family_ttl_seconds(policy.family, policy.default_ttl_seconds)
    except Exception:
        return policy
    if ttl_seconds == policy.default_ttl_seconds:
        return policy
    return replace(policy, default_ttl_seconds=ttl_seconds)


def render_assertion_family_list() -> str:
    """Render the canonical family allowlist for prompts."""

    return ", ".join(ASSERTION_FAMILY_POLICIES)


def render_assertion_family_semantics() -> str:
    """Render concise Phase 2 guidance for assertion-family selection."""

    lines = ["## Assertion Family Semantics"]
    for policy in ASSERTION_FAMILY_POLICIES.values():
        lines.append(f"- `{policy.family}`: {policy.description} {policy.phase2_guidance}")
    return "\n".join(lines)


def decorate_assertion_family_metadata(assertion: dict[str, Any]) -> dict[str, Any]:
    """Return an assertion payload enriched with family policy display metadata."""

    decorated = dict(assertion)
    policy = get_assertion_family_policy(str(decorated.get("trait_family") or ""))
    if policy is None:
        return decorated
    decorated["trait_value_i18n"] = policy.value_i18n
    decorated["assertion_family_snapshot_bucket"] = policy.snapshot_bucket
    decorated["assertion_family_description"] = policy.description
    return decorated


__all__ = [
    "ASSERTION_FAMILY_ALLOWLIST",
    "ASSERTION_FAMILY_POLICIES",
    "AssertionFamilyPolicy",
    "decorate_assertion_family_metadata",
    "get_assertion_family_policy",
    "render_assertion_family_list",
    "render_assertion_family_semantics",
]
