"""Deterministic Claim-to-Assertion materialization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..assertion_family_policy import get_assertion_family_policy
from ..phase1_models import L2ClaimEvidenceMode, L2Phase1FactClaim, L2TemporalCue
from ..semantic_routing import ROUTE_CONTRACT_VERSION, SemanticRouteDecision
from .occurrence_stats import ClaimOccurrenceStats
from .promotion import (
    AssertionPromotionInput,
    PromotionHorizon,
    evaluate_assertion_promotion,
)
from .subdomain import classify_memory_subdomain

MaterializationAction = Literal["write", "review", "expired", "event_only", "rejected"]

_PROFILE_FAMILIES = frozenset(
    {
        "communication_profile",
        "goal_profile",
        "identity_profile",
        "interest_profile",
        "preference_profile",
        "project_profile",
        "routine_profile",
        "state_profile",
        "mood",
    }
)
_GOAL_FALLBACK_TTL_SECONDS = 90 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class MaterializationInput:
    """Complete host-owned input for one routed Assertion target."""

    route: SemanticRouteDecision
    claims: tuple[L2Phase1FactClaim, ...]
    occurrence_stats: ClaimOccurrenceStats
    self_entity_id: str
    direct_assertion_write_allowed: bool
    profile_allows_assertion: bool
    allowed_families: frozenset[str]
    allowed_traits: frozenset[str] | None
    source_domain: str
    inference_depth: str
    observed_at: float
    now: float
    natural_summary: str = ""


@dataclass(frozen=True, slots=True)
class MaterializationDecision:
    """Terminal host decision for one routed Assertion target."""

    action: MaterializationAction
    reason_code: str
    family: str | None
    trait_name: str | None
    trait_value: str | None
    slot_key: str | None
    value_fingerprint: str | None
    semantic_lineage_key: str | None
    temporal_scope: str | None
    decay_policy: str | None
    ttl_seconds: float | None
    valid_from: float | None
    valid_to: float | None
    expires_at: float | None
    target_window: dict[str, Any] | None
    evidence_event_ids: tuple[str, ...]
    natural_summary: str | None
    candidate: dict[str, Any] | None = None
    review_proposal: dict[str, Any] | None = None


def materialize_assertion(material: MaterializationInput) -> MaterializationDecision:
    """Materialize one routed Claim group without model-owned semantic decisions."""

    route = material.route
    base = _decision_base(material)
    if any(claim.polarity != "positive" for claim in material.claims):
        return _terminal(base, action="event_only", reason_code="negative_claim_requires_scoped_exclusion")
    if not route.can_project_assertion:
        return _terminal(base, action="event_only", reason_code="route_has_no_assertion_target")
    if not route.family or not route.trait_code or not route.slot_key:
        return _terminal(base, action="rejected", reason_code="invalid_assertion_route")
    if not material.direct_assertion_write_allowed:
        return _terminal(
            base,
            action="event_only",
            reason_code="direct_assertion_write_disabled",
        )
    if not material.profile_allows_assertion:
        return _terminal(base, action="event_only", reason_code="assertion_profile_disabled")
    if route.family not in material.allowed_families:
        return _terminal(base, action="event_only", reason_code="assertion_family_disabled")
    if not _trait_allowed(route.trait_code, material.allowed_traits):
        return _terminal(base, action="event_only", reason_code="assertion_trait_disabled")

    integrity_reason = _integrity_reason(material)
    if integrity_reason is not None:
        return _terminal(base, action="rejected", reason_code=integrity_reason)
    if route.family in _PROFILE_FAMILIES and route.subject_id != material.self_entity_id:
        return _terminal(base, action="event_only", reason_code="non_self_profile_subject")

    if route.family == "goal_profile":
        goal_reason = _goal_terminal_reason(material)
        if goal_reason is not None:
            action: MaterializationAction = (
                "expired" if goal_reason == "goal_target_expired" else "review"
            )
            return _terminal(base, action=action, reason_code=goal_reason)

    if _recent_time_reason(material.occurrence_stats) is not None:
        return _terminal(base, action="review", reason_code="low_time_confidence")

    promotion = _promotion_decision(material)
    if promotion.horizon is PromotionHorizon.EVENT_ONLY:
        return _terminal(base, action="event_only", reason_code=promotion.reason)
    if (
        promotion.horizon is PromotionHorizon.RECENT
        and material.occurrence_stats.last_observed_at is None
    ):
        return _terminal(base, action="review", reason_code="low_time_confidence")

    trait_value = _trait_value(material)
    if not trait_value:
        return _terminal(base, action="rejected", reason_code="missing_trait_value")

    lifecycle_anchor = (
        float(material.occurrence_stats.last_observed_at)
        if promotion.horizon is PromotionHorizon.RECENT
        and material.occurrence_stats.last_observed_at is not None
        else float(material.observed_at)
    )
    ttl_seconds = promotion.expiry.ttl_seconds
    expires_at = lifecycle_anchor + ttl_seconds if ttl_seconds is not None else None
    if route.family == "goal_profile":
        target_ends = {
            float(claim.target_to) for claim in material.claims if claim.target_to is not None
        }
        if len(target_ends) == 1:
            expires_at = next(iter(target_ends))
            ttl_seconds = max(0.0, expires_at - lifecycle_anchor)
        elif expires_at is None:
            ttl_seconds = _GOAL_FALLBACK_TTL_SECONDS
            expires_at = lifecycle_anchor + ttl_seconds

    summary = _natural_summary(material)
    target_window = _target_window(material.claims) if route.family == "goal_profile" else None
    candidate = {
        "entity_id": route.subject_id or material.self_entity_id,
        "entity_type": route.subject_type or "user",
        "trait_family": route.family,
        "trait_name": route.trait_code,
        "trait_value": trait_value,
        "confidence_score": min(float(claim.confidence or 0.0) for claim in material.claims),
        "evidence_events": list(material.occurrence_stats.supporting_event_ids),
        "volatility_index": _volatility(promotion.expiry.temporal_scope),
        "source_domain": material.source_domain,
        "inference_depth": material.inference_depth,
        "validation_state": "tentative",
        "first_inferred_at": float(
            material.occurrence_stats.first_observed_at or material.observed_at
        ),
        "last_validated_at": lifecycle_anchor,
        "target_entity_id": route.target_entity_id or "",
        "target_entity_type": route.target_entity_type or "",
        "target_scope": "entity_bound" if route.target_entity_id else "global",
        "temporal_scope": promotion.expiry.temporal_scope,
        "decay_policy": promotion.expiry.decay_policy,
        "decay_anchor_at": lifecycle_anchor,
        "context_ref_id": route.target_entity_id or "",
        "expires_at": expires_at,
        "memory_subdomain": classify_memory_subdomain(
            promotion.expiry.temporal_scope,
            promotion.expiry.decay_policy,
        ),
        "natural_summary": summary,
        "semantic_route_key": route.route_key or "",
        "semantic_route_slot_key": route.slot_key or "",
        "route_contract_version": ROUTE_CONTRACT_VERSION,
        "supporting_claim_ids": [claim.claim_id for claim in material.claims],
        "semantic_lineage_key": route.goal_lineage_key or "",
        "target_window": target_window or {},
    }
    return MaterializationDecision(
        action="write",
        reason_code=promotion.reason,
        family=route.family,
        trait_name=route.trait_code,
        trait_value=trait_value,
        slot_key=route.slot_key,
        value_fingerprint=route.value_fingerprint,
        semantic_lineage_key=route.goal_lineage_key,
        temporal_scope=promotion.expiry.temporal_scope,
        decay_policy=promotion.expiry.decay_policy,
        ttl_seconds=ttl_seconds,
        valid_from=_shared_optional_float(material.claims, "fact_valid_from"),
        valid_to=_shared_optional_float(material.claims, "fact_valid_to"),
        expires_at=expires_at,
        target_window=target_window,
        evidence_event_ids=material.occurrence_stats.supporting_event_ids,
        natural_summary=summary,
        candidate=candidate,
        review_proposal=None,
    )


def _decision_base(material: MaterializationInput) -> dict[str, Any]:
    route = material.route
    return {
        "family": route.family,
        "trait_name": route.trait_code,
        "trait_value": _trait_value(material),
        "slot_key": route.slot_key,
        "value_fingerprint": route.value_fingerprint,
        "semantic_lineage_key": route.goal_lineage_key,
        "temporal_scope": None,
        "decay_policy": None,
        "ttl_seconds": None,
        "valid_from": _shared_optional_float(material.claims, "fact_valid_from"),
        "valid_to": _shared_optional_float(material.claims, "fact_valid_to"),
        "expires_at": None,
        "target_window": _target_window(material.claims),
        "evidence_event_ids": material.occurrence_stats.supporting_event_ids,
        "natural_summary": _natural_summary(material),
        "candidate": None,
        "review_proposal": _review_proposal(material),
    }


def _terminal(
    base: dict[str, Any],
    *,
    action: MaterializationAction,
    reason_code: str,
) -> MaterializationDecision:
    return MaterializationDecision(action=action, reason_code=reason_code, **base)


def _integrity_reason(material: MaterializationInput) -> str | None:
    if not material.claims:
        return "missing_supporting_claims"
    claim_ids = [claim.claim_id for claim in material.claims]
    if any(not claim_id for claim_id in claim_ids) or len(set(claim_ids)) != len(claim_ids):
        return "invalid_supporting_claims"
    if not set(claim_ids).issubset(set(material.occurrence_stats.claim_ids)):
        return "claim_ledger_mismatch"
    if not material.occurrence_stats.supporting_event_ids:
        return "missing_grounded_support"
    return None


def _trait_allowed(trait_name: str, allowed_traits: frozenset[str] | None) -> bool:
    if allowed_traits is None:
        return True
    normalized = trait_name.casefold()
    return any(
        normalized == pattern.casefold()
        or (pattern.endswith(".*") and normalized.startswith(pattern[:-1].casefold()))
        for pattern in allowed_traits
    )


def _goal_terminal_reason(material: MaterializationInput) -> str | None:
    if any(claim.evidence_mode is not L2ClaimEvidenceMode.DIRECT for claim in material.claims):
        return "goal_requires_direct_self_report"
    supporting_ids = {
        event_id for claim in material.claims for event_id in claim.supporting_event_ids
    }
    if not supporting_ids or not supporting_ids.issubset(
        set(material.occurrence_stats.trusted_event_ids)
    ):
        return "goal_low_time_confidence"
    for claim in material.claims:
        frame = claim.raw_time_frame or {}
        resolution = str(frame.get("resolution") or "unscheduled").strip().casefold()
        if claim.raw_time_expression and resolution == "low":
            return "goal_low_time_confidence"
        if claim.raw_time_expression and resolution not in {"exact", "calendar_anchor"}:
            return "goal_ambiguous_time"
    target_ends = [
        float(claim.target_to) for claim in material.claims if claim.target_to is not None
    ]
    if target_ends and min(target_ends) <= material.now:
        return "goal_target_expired"
    if not target_ends:
        last_observed = material.occurrence_stats.last_observed_at
        if last_observed is not None and last_observed + _GOAL_FALLBACK_TTL_SECONDS <= material.now:
            return "goal_target_expired"
    return None


def _recent_time_reason(stats: ClaimOccurrenceStats) -> str | None:
    if L2TemporalCue.from_value(stats.temporal_cue) is not L2TemporalCue.RECENT:
        return None
    policy_ids = set(stats.recent_policy_event_ids)
    if policy_ids and policy_ids.issubset(set(stats.trusted_event_ids)):
        return None
    return "low_time_confidence"


def _promotion_decision(material: MaterializationInput):
    family_policy = get_assertion_family_policy(material.route.family)
    return evaluate_assertion_promotion(
        AssertionPromotionInput(
            trait_family=material.route.family or "",
            **material.occurrence_stats.promotion_fields(),
            baseline_temporal_scope=(
                family_policy.default_temporal_scope if family_policy is not None else None
            ),
            baseline_decay_policy=(
                family_policy.default_decay_policy if family_policy is not None else None
            ),
            baseline_ttl_seconds=(
                family_policy.default_ttl_seconds if family_policy is not None else None
            ),
        )
    )


def _trait_value(material: MaterializationInput) -> str:
    route = material.route
    if route.family == "goal_profile":
        return str(route.object_surface or "").strip()
    value = route.canonical_value
    return str(value if value is not None else "").strip()


def _natural_summary(material: MaterializationInput) -> str:
    supplied = " ".join(str(material.natural_summary or "").split())[:500]
    if supplied:
        return supplied
    for claim in material.claims:
        evidence = " ".join(str(claim.evidence_text or "").split())
        if evidence:
            return evidence[:500]
    return str(material.route.object_surface or _trait_value(material)).strip()[:500]


def _review_proposal(material: MaterializationInput) -> dict[str, Any] | None:
    route = material.route
    trait_value = _trait_value(material)
    if not route.family or not route.trait_code or not route.slot_key or not trait_value:
        return None
    family_policy = get_assertion_family_policy(route.family)
    observed_at = float(
        material.occurrence_stats.last_observed_at
        or material.occurrence_stats.first_observed_at
        or material.observed_at
    )
    target_window = _target_window(material.claims) if route.family == "goal_profile" else None
    expires_at = None
    if target_window and target_window.get("target_to") is not None:
        expires_at = float(target_window["target_to"])
    return {
        "entity_id": route.subject_id or material.self_entity_id,
        "entity_type": route.subject_type or "user",
        "trait_family": route.family,
        "trait_name": route.trait_code,
        "trait_value": trait_value,
        "confidence_score": min(float(claim.confidence or 0.0) for claim in material.claims),
        "evidence_events": list(material.occurrence_stats.supporting_event_ids),
        "volatility_index": 0.2,
        "source_domain": material.source_domain,
        "inference_depth": material.inference_depth,
        "validation_state": "tentative",
        "first_inferred_at": float(
            material.occurrence_stats.first_observed_at or material.observed_at
        ),
        "last_validated_at": observed_at,
        "target_entity_id": route.target_entity_id or "",
        "target_entity_type": route.target_entity_type or "",
        "target_scope": "entity_bound" if route.target_entity_id else "global",
        "temporal_scope": (
            family_policy.default_temporal_scope if family_policy is not None else "persistent"
        ),
        "decay_policy": (
            family_policy.default_decay_policy if family_policy is not None else "evidence_only"
        ),
        "decay_anchor_at": observed_at,
        "context_ref_id": route.target_entity_id or "",
        "expires_at": expires_at,
        "memory_subdomain": classify_memory_subdomain(
            family_policy.default_temporal_scope if family_policy is not None else "persistent",
            family_policy.default_decay_policy if family_policy is not None else "evidence_only",
        ),
        "natural_summary": _natural_summary(material),
        "semantic_route_key": route.route_key or "",
        "semantic_route_slot_key": route.slot_key,
        "route_contract_version": ROUTE_CONTRACT_VERSION,
        "supporting_claim_ids": [claim.claim_id for claim in material.claims],
        "semantic_lineage_key": route.goal_lineage_key or "",
        "target_window": target_window or {},
    }


def _target_window(claims: tuple[L2Phase1FactClaim, ...]) -> dict[str, Any] | None:
    windows = {
        (
            claim.target_from,
            claim.target_to,
            claim.raw_time_expression,
            str((claim.raw_time_frame or {}).get("resolution") or "unscheduled"),
        )
        for claim in claims
    }
    if len(windows) != 1:
        return None
    target_from, target_to, raw, resolution = next(iter(windows))
    frame = claims[0].raw_time_frame or {}
    return {
        "target_from": target_from,
        "target_to": target_to,
        "raw": raw,
        "resolution": resolution,
        "precision": frame.get("precision"),
        "timezone": frame.get("timezone") or frame.get("timezone_id"),
    }


def _shared_optional_float(
    claims: tuple[L2Phase1FactClaim, ...],
    field_name: str,
) -> float | None:
    values = {
        float(value)
        for claim in claims
        if (value := getattr(claim, field_name, None)) is not None
    }
    return next(iter(values)) if len(values) == 1 else None


def _volatility(temporal_scope: str) -> float:
    if temporal_scope == "momentary":
        return 0.9
    if temporal_scope in {"temporary", "recent"}:
        return 0.7
    return 0.2


__all__ = [
    "MaterializationAction",
    "MaterializationDecision",
    "MaterializationInput",
    "materialize_assertion",
]
