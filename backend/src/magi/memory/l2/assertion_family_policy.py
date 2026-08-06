"""Central assertion-family semantics for L2 cognition."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class AssertionFamilyPolicy:
    """Policy metadata shared by materialization, decay, and snapshots."""

    family: str
    description: str
    default_temporal_scope: str
    default_decay_policy: str
    default_ttl_seconds: float | None
    snapshot_bucket: str
    value_i18n: str


def _policy(
    family: str,
    description: str,
    temporal_scope: str,
    decay_policy: str,
    ttl_seconds: float | None,
    snapshot_bucket: str,
    value_i18n: str,
) -> AssertionFamilyPolicy:
    return AssertionFamilyPolicy(
        family=family,
        description=description,
        default_temporal_scope=temporal_scope,
        default_decay_policy=decay_policy,
        default_ttl_seconds=ttl_seconds,
        snapshot_bucket=snapshot_bucket,
        value_i18n=value_i18n,
    )


ASSERTION_FAMILY_POLICIES: dict[str, AssertionFamilyPolicy] = {
    "stress": _policy(
        "stress",
        "Short-lived stress or pressure level grounded in user-authored evidence.",
        "daily",
        "time_window",
        24 * 60 * 60,
        "state",
        "controlled",
    ),
    "mood": _policy(
        "mood",
        "Short-lived emotional state.",
        "session",
        "session_decay",
        12 * 60 * 60,
        "state",
        "controlled",
    ),
    "engagement": _policy(
        "engagement",
        "Current attention, participation, or task engagement state.",
        "session",
        "session_decay",
        12 * 60 * 60,
        "state",
        "controlled",
    ),
    "trigger": _policy(
        "trigger",
        "A stable factor that tends to cause a user state or strong reaction.",
        "stable",
        "evidence_only",
        None,
        "sensitive_triggers",
        "literal",
    ),
    "relationship_shift": _policy(
        "relationship_shift",
        "Short-lived change in relationship state or social dynamics.",
        "session",
        "session_decay",
        6 * 60 * 60,
        "relationship",
        "literal",
    ),
    "group_atmosphere": _policy(
        "group_atmosphere",
        "Short-lived tone of a group conversation or shared context.",
        "session",
        "session_decay",
        6 * 60 * 60,
        "context",
        "controlled",
    ),
    "public_sentiment": _policy(
        "public_sentiment",
        "External or public sentiment about an entity, not the user's own preference.",
        "session",
        "session_decay",
        6 * 60 * 60,
        "public_sentiment",
        "controlled",
    ),
    "identity_profile": _policy(
        "identity_profile",
        "Stable user identity facts such as name, birthday, age, or home location.",
        "stable",
        "evidence_only",
        None,
        "core_traits",
        "literal",
    ),
    "communication_profile": _policy(
        "communication_profile",
        "How the user wants the assistant to address, respond to, or interact with them.",
        "stable",
        "evidence_only",
        None,
        "core_traits",
        "literal",
    ),
    "preference_profile": _policy(
        "preference_profile",
        "Explicit likes, dislikes, affinities, and tastes.",
        "stable",
        "evidence_only",
        None,
        "preferences",
        "literal",
    ),
    "interest_profile": _policy(
        "interest_profile",
        "Topics, domains, and subjects that hold the user's attention or interest.",
        "stable",
        "evidence_only",
        None,
        "preferences",
        "literal",
    ),
    "project_profile": _policy(
        "project_profile",
        "Projects the user is actively building, maintaining, or contributing to.",
        "stable",
        "evidence_only",
        None,
        "core_traits",
        "literal",
    ),
    "goal_profile": _policy(
        "goal_profile",
        "A concrete near-term goal or plan explicitly stated by the user.",
        "recent",
        "time_window",
        30 * 24 * 60 * 60,
        "context",
        "literal",
    ),
    "routine_profile": _policy(
        "routine_profile",
        "Stable behavior patterns and rhythms such as recurring tools, times, or habits.",
        "stable",
        "evidence_only",
        None,
        "core_traits",
        "literal",
    ),
    "state_profile": _policy(
        "state_profile",
        "Slowly changing user state that is more durable than mood or stress.",
        "stable",
        "evidence_only",
        None,
        "core_traits",
        "controlled",
    ),
}

ASSERTION_FAMILY_ALLOWLIST: frozenset[str] = frozenset(ASSERTION_FAMILY_POLICIES)


def get_assertion_family_policy(family: str | None) -> AssertionFamilyPolicy | None:
    """Return the canonical policy for an assertion family."""

    policy = ASSERTION_FAMILY_POLICIES.get(str(family or "").strip().casefold())
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
]
