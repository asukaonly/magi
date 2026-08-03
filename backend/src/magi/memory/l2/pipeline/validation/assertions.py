"""Assertion candidate helpers for the L2 cognition pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from ....event_contracts import MemoryEvent
from ...context_bundle import ResolvedContextRef
from ...extraction_profiles import ExtractionProfile
from ...models import L2AssertionCandidate, L2Phase1FactClaim, L2Phase1Result
from ...assertion_family_policy import get_assertion_family_policy
from ...assertions.promotion import (
    AssertionPromotionDecision,
    AssertionPromotionInput,
    PromotionHorizon,
    SourceStrengthPreset,
    evaluate_assertion_promotion,
)
from ...assertions.settings import momentary_ttl_seconds
from ...ontology import is_leaf_fact_duplicate, validate_assertion_candidate
from ...ontology_aliases import canonicalize_predicate
from ...phase1_models import L2TemporalCue
from ...semantic_routing import (
    ROUTE_CONTRACT_VERSION,
    ObjectRole,
    SemanticRouteDecision,
)
from .evidence import validate_supporting_event_ids
from ..extraction_contracts import ClaimProjectionOutcomeDraft

_TOPOLOGY_ONLY_TRAIT_FAMILIES = {"public_sentiment", "group_atmosphere", "relationship_shift"}
_SEMANTIC_TEMPORAL_SCOPES = {"persistent", "stable", ""}
_SEMANTIC_DECAY_POLICIES = {"none", "evidence_only", ""}
_PROFILE_FAMILIES = frozenset(
    {
        "communication_profile",
        "identity_profile",
        "interest_profile",
        "preference_profile",
        "project_profile",
        "routine_profile",
        "state_profile",
    }
)
_PROJECT_ENGAGEMENT_PREDICATES = frozenset(
    {"CONTRIBUTES_TO", "CREATES", "DEVELOPS", "MAINTAINS", "WORKS_ON"}
)
_SUSTAINED_ENGAGEMENT_PREDICATES = frozenset(
    {*_PROJECT_ENGAGEMENT_PREDICATES, "ATTENDED", "MEMBER_OF", "OWNS", "USES"}
)


def classify_memory_subdomain(temporal_scope: str, decay_policy: str) -> str:
    """Classify an assertion as 'semantic' or 'state' based on scope and decay."""
    if temporal_scope in _SEMANTIC_TEMPORAL_SCOPES and (
        decay_policy in _SEMANTIC_DECAY_POLICIES or not decay_policy
    ):
        return "semantic"
    return "state"


def _claims_by_id(phase1_result: L2Phase1Result | None) -> dict[str, L2Phase1FactClaim]:
    if phase1_result is None:
        return {}
    return {
        claim.claim_id: claim
        for claim in phase1_result.fact_claims
        if str(claim.claim_id or "").strip()
    }


def _resolve_supporting_claims(
    assertion: Any,
    claims_by_id: dict[str, L2Phase1FactClaim],
) -> list[L2Phase1FactClaim]:
    claim_ids = [
        str(value or "").strip()
        for value in getattr(assertion, "supporting_claim_ids", [])
        if str(value or "").strip()
    ]
    if not claim_ids or len(set(claim_ids)) != len(claim_ids):
        return []
    if any(claim_id not in claims_by_id for claim_id in claim_ids):
        return []
    return [claims_by_id[claim_id] for claim_id in claim_ids]


def _known_supporting_claims(
    assertion: Any,
    claims_by_id: dict[str, L2Phase1FactClaim],
) -> list[L2Phase1FactClaim]:
    seen: set[str] = set()
    known: list[L2Phase1FactClaim] = []
    for raw_claim_id in getattr(assertion, "supporting_claim_ids", []):
        claim_id = str(raw_claim_id or "").strip()
        if not claim_id or claim_id in seen or claim_id not in claims_by_id:
            continue
        seen.add(claim_id)
        known.append(claims_by_id[claim_id])
    return known


def _append_assertion_rejection_outcomes(
    outcomes: list[ClaimProjectionOutcomeDraft],
    *,
    assertion: Any,
    claims_by_id: dict[str, L2Phase1FactClaim],
    semantic_routes: dict[str, SemanticRouteDecision],
    reason_code: str,
    supporting_claims: list[L2Phase1FactClaim] | None = None,
    route: SemanticRouteDecision | None = None,
) -> None:
    claims = supporting_claims or _known_supporting_claims(assertion, claims_by_id)
    for claim in claims:
        claim_route = route or semantic_routes.get(claim.claim_id)
        slot_key = str(claim_route.slot_key or "").strip() if claim_route is not None else ""
        route_key = str(claim_route.route_key or "").strip() if claim_route is not None else ""
        predicate = canonicalize_predicate(str(claim.predicate or "")) or str(
            claim.predicate or ""
        ).strip().upper()
        target_id = (
            f"slot:{slot_key}"
            if slot_key
            else f"route:{route_key}"
            if route_key
            else f"predicate:{predicate}"
            if predicate
            else f"claim:{claim.claim_id}"
        )
        outcomes.append(
            ClaimProjectionOutcomeDraft(
                claim_id=claim.claim_id,
                target_kind="assertion",
                target_id=target_id,
                target_slot_key=slot_key or None,
                outcome="rejected",
                reason_code=reason_code,
            )
        )


def _supporting_event_ids(claims: list[L2Phase1FactClaim]) -> list[str]:
    event_ids: list[str] = []
    seen: set[str] = set()
    for claim in claims:
        for event_id in claim.supporting_event_ids:
            if event_id in seen:
                continue
            seen.add(event_id)
            event_ids.append(event_id)
    return event_ids


def _supporting_claim_subject(claims: list[L2Phase1FactClaim]) -> str | None:
    subjects = {
        str(claim.subject_ref or "").strip()
        for claim in claims
        if str(claim.subject_ref or "").strip()
    }
    if len(subjects) != 1:
        return None
    return next(iter(subjects))


def _supporting_claim_confidence(claims: list[L2Phase1FactClaim]) -> float:
    if not claims:
        return 0.0
    return min(max(0.0, min(1.0, float(claim.confidence or 0.0))) for claim in claims)


def _volatility_for_temporal_scope(temporal_scope: str) -> float:
    normalized = str(temporal_scope or "").strip().casefold()
    if normalized == "momentary":
        return 0.9
    if normalized in {"temporary", "recent"}:
        return 0.7
    return 0.2


def _profile_accepts_phase2_assertions(profile: ExtractionProfile) -> bool:
    mode = str(getattr(profile, "assertion_mode", "phase2_candidate") or "").strip().casefold()
    return mode in {"", "phase2_candidate"}


def _profile_allows_assertion_trait(profile: ExtractionProfile, trait_name: str) -> bool:
    allowed_traits = getattr(profile, "allowed_assertion_traits", None)
    if allowed_traits is None or allowed_traits == "all":
        return True
    allowed_iterable = [allowed_traits] if isinstance(allowed_traits, str) else allowed_traits
    normalized_trait = str(trait_name or "").strip().casefold()
    for item in allowed_iterable:
        pattern = str(item).strip().casefold()
        if not pattern:
            continue
        if pattern.endswith(".*") and normalized_trait.startswith(pattern[:-1]):
            return True
        if normalized_trait == pattern:
            return True
    return False


def _shared_semantic_route(
    claims: list[L2Phase1FactClaim],
    routes_by_claim_id: dict[str, SemanticRouteDecision],
) -> SemanticRouteDecision | None:
    routes = [routes_by_claim_id.get(claim.claim_id) for claim in claims]
    if any(route is None or not route.can_project_assertion for route in routes):
        return None
    typed_routes = [route for route in routes if route is not None]
    route_identities = {
        (
            route.slot_key,
            route.value_fingerprint,
            route.family,
            route.trait_code,
            route.subject_id,
            route.subject_type,
            route.target_entity_id,
            route.target_entity_type,
            route.scope_key,
        )
        for route in typed_routes
    }
    if len(route_identities) != 1:
        return None
    return typed_routes[0]


def _promotion_fact_kind(claims: list[L2Phase1FactClaim]) -> str:
    fact_kinds = {str(claim.fact_kind or "").strip().casefold() for claim in claims}
    if len(fact_kinds) == 1:
        return next(iter(fact_kinds))
    if "interaction_evidence" in fact_kinds:
        return "interaction_evidence"
    return "explicit_fact"


def _promotion_predicate(claims: list[L2Phase1FactClaim]) -> str:
    predicates = {canonicalize_predicate(str(claim.predicate or "")) or "" for claim in claims}
    return next(iter(predicates)) if len(predicates) == 1 else ""


def _promotion_temporal_cue(claims: list[L2Phase1FactClaim]) -> L2TemporalCue:
    cues = {L2TemporalCue.from_value(getattr(claim, "temporal_cue", None)) for claim in claims}
    if len(cues) == 1:
        return next(iter(cues))
    if L2TemporalCue.RECENT in cues:
        return L2TemporalCue.RECENT
    if L2TemporalCue.UNSPECIFIED in cues:
        return L2TemporalCue.UNSPECIFIED
    if L2TemporalCue.RECURRING in cues:
        return L2TemporalCue.RECURRING
    return L2TemporalCue.UNSPECIFIED


def _event_evidence_class(event: MemoryEvent) -> str:
    metadata = getattr(event, "metadata_json", None)
    if isinstance(metadata, dict):
        annotated = str(metadata.get("evidence_class") or "").strip().casefold()
        if annotated:
            return annotated
    memory_domain = getattr(event, "memory_domain", None)
    domain = str(getattr(memory_domain, "label", memory_domain) or "").strip().casefold()
    if domain == "user_authored":
        return "user_self_report"
    if domain == "external_activity":
        return "external_observation"
    if domain == "runtime_telemetry":
        return "system_runtime"
    return "unknown"


def _source_strength_for_claims(
    event: MemoryEvent,
    claims: list[L2Phase1FactClaim],
) -> SourceStrengthPreset:
    if _event_evidence_class(event) == "user_self_report":
        return SourceStrengthPreset.DIRECT_USER
    predicates = {canonicalize_predicate(str(claim.predicate or "")) or "" for claim in claims}
    if predicates & _SUSTAINED_ENGAGEMENT_PREDICATES:
        return SourceStrengthPreset.SUSTAINED_ENGAGEMENT
    if _event_evidence_class(event) == "external_observation":
        return SourceStrengthPreset.PASSIVE_EXPOSURE
    return SourceStrengthPreset.STRUCTURED_SOURCE


def _profile_permits_durable(
    event: MemoryEvent,
    profile: ExtractionProfile,
    trait_family: str,
) -> bool:
    if _event_evidence_class(event) == "user_self_report":
        return True
    allowed = getattr(profile, "durable_assertion_families", None)
    if allowed == "all":
        return True
    if allowed is None:
        return False
    values = [allowed] if isinstance(allowed, str) else allowed
    return trait_family in {str(value or "").strip().casefold() for value in values}


class _L2AssertionHostProtocol(Protocol):
    def _resolve_self_entity_id(self, event: MemoryEvent) -> str | None: ...

    def _non_empty_text(self, value: Any) -> Optional[str]: ...

    def _normalize_entity_type(self, raw_value: Any) -> Optional[str]: ...


@dataclass(frozen=True)
class Phase2AssertionValidationContext:
    event: MemoryEvent
    profile: ExtractionProfile
    host: _L2AssertionHostProtocol
    duplicate_check_candidates: list[dict[str, Any]]
    default_event_ids: list[str]
    claims_by_id: dict[str, L2Phase1FactClaim]
    semantic_routes: dict[str, SemanticRouteDecision]
    assertion_scope: str
    claim_outcomes: list[ClaimProjectionOutcomeDraft]


class L2AssertionValidationMixin:
    """Own assertion normalization, decay, and scope filtering."""

    def _validate_phase2_assertions(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        graph_candidates: list[dict[str, Any]],
        default_event_ids: list[str],
        semantic_routes: dict[str, SemanticRouteDecision],
        phase2_assertions: list,
        phase1_result: L2Phase1Result | None = None,
        claim_outcomes: list[ClaimProjectionOutcomeDraft] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Validate Phase 2 assertion candidates."""
        claims_by_id = _claims_by_id(phase1_result)
        outcome_drafts = claim_outcomes if claim_outcomes is not None else []
        raw_assertions = list(phase2_assertions or [])
        if not policy.allow_assertion_write or not profile.allow_assertion:
            for assertion in raw_assertions:
                _append_assertion_rejection_outcomes(
                    outcome_drafts,
                    assertion=assertion,
                    claims_by_id=claims_by_id,
                    semantic_routes=semantic_routes,
                    reason_code="assertion_write_disabled",
                )
            return [], 0
        if not _profile_accepts_phase2_assertions(profile):
            for assertion in raw_assertions:
                _append_assertion_rejection_outcomes(
                    outcome_drafts,
                    assertion=assertion,
                    claims_by_id=claims_by_id,
                    semantic_routes=semantic_routes,
                    reason_code="assertion_profile_mode_rejected",
                )
            return [], len(raw_assertions)

        assertion_scope = str(getattr(policy, "assertion_scope", None) or "full")
        scoped_assertions = [] if assertion_scope == "none" else raw_assertions
        if assertion_scope == "none":
            for assertion in raw_assertions:
                _append_assertion_rejection_outcomes(
                    outcome_drafts,
                    assertion=assertion,
                    claims_by_id=claims_by_id,
                    semantic_routes=semantic_routes,
                    reason_code="assertion_scope_rejected",
                )

        context = Phase2AssertionValidationContext(
            event=event,
            profile=profile,
            host=self._assertion_host(),
            duplicate_check_candidates=[
                {"predicate": c["predicate"], "object_ref": c["object_id"]}
                for c in graph_candidates
            ],
            default_event_ids=default_event_ids,
            claims_by_id=claims_by_id,
            semantic_routes=dict(semantic_routes),
            assertion_scope=assertion_scope,
            claim_outcomes=outcome_drafts,
        )
        prepared: list[dict[str, Any]] = []
        rejected_count = max(0, len(raw_assertions) - len(scoped_assertions))
        for assertion in scoped_assertions:
            prepared_assertion = self._prepare_phase2_assertion(assertion, context)
            if prepared_assertion is None:
                rejected_count += 1
                continue
            prepared.append(prepared_assertion)
        return prepared, rejected_count

    def _prepare_phase2_assertion(
        self,
        assertion: Any,
        context: Phase2AssertionValidationContext,
    ) -> dict[str, Any] | None:
        supporting_claims = _resolve_supporting_claims(assertion, context.claims_by_id)
        if not supporting_claims:
            _append_assertion_rejection_outcomes(
                context.claim_outcomes,
                assertion=assertion,
                claims_by_id=context.claims_by_id,
                semantic_routes=context.semantic_routes,
                reason_code="invalid_supporting_claims",
            )
            return None
        route = _shared_semantic_route(supporting_claims, context.semantic_routes)
        if route is None or route.family is None or route.trait_code is None:
            _append_assertion_rejection_outcomes(
                context.claim_outcomes,
                assertion=assertion,
                claims_by_id=context.claims_by_id,
                semantic_routes=context.semantic_routes,
                supporting_claims=supporting_claims,
                reason_code="incompatible_semantic_route",
            )
            return None
        trait_family = route.family
        trait_name = route.trait_code
        trait_value = (
            getattr(assertion, "trait_value", "")
            if route.object_role is ObjectRole.STRUCTURED_TARGET_AND_VALUE
            else route.canonical_value
        )
        if trait_value is None or not str(trait_value).strip():
            _append_assertion_rejection_outcomes(
                context.claim_outcomes,
                assertion=assertion,
                claims_by_id=context.claims_by_id,
                semantic_routes=context.semantic_routes,
                supporting_claims=supporting_claims,
                route=route,
                reason_code="missing_trait_value",
            )
            return None
        if not self._phase2_assertion_allowed(
            context,
            trait_family=trait_family,
            trait_name=trait_name,
            trait_value=trait_value,
        ):
            _append_assertion_rejection_outcomes(
                context.claim_outcomes,
                assertion=assertion,
                claims_by_id=context.claims_by_id,
                semantic_routes=context.semantic_routes,
                supporting_claims=supporting_claims,
                route=route,
                reason_code="assertion_policy_rejected",
            )
            return None
        supporting_event_ids = validate_supporting_event_ids(
            _supporting_event_ids(supporting_claims),
            context.default_event_ids,
        )
        if not supporting_event_ids:
            _append_assertion_rejection_outcomes(
                context.claim_outcomes,
                assertion=assertion,
                claims_by_id=context.claims_by_id,
                semantic_routes=context.semantic_routes,
                supporting_claims=supporting_claims,
                route=route,
                reason_code="missing_grounded_support",
            )
            return None
        promotion_decision = self._evaluate_phase2_assertion_promotion(
            event=context.event,
            profile=context.profile,
            trait_family=trait_family,
            trait_name=trait_name,
            supporting_claims=supporting_claims,
            supporting_event_ids=supporting_event_ids,
        )
        if (
            trait_family in _PROFILE_FAMILIES
            and promotion_decision.horizon is PromotionHorizon.EVENT_ONLY
        ):
            for claim in supporting_claims:
                context.claim_outcomes.append(
                    ClaimProjectionOutcomeDraft(
                        claim_id=claim.claim_id,
                        target_kind="assertion",
                        target_id=f"slot:{route.slot_key}",
                        target_slot_key=route.slot_key,
                        outcome="event_only",
                        reason_code=promotion_decision.reason,
                    )
                )
            return None
        return self._normalize_phase2_assertion(
            assertion,
            context=context,
            trait_family=trait_family,
            trait_name=trait_name,
            supporting_event_ids=supporting_event_ids,
            supporting_claims=supporting_claims,
            route=route,
            trait_value=trait_value,
            promotion_decision=promotion_decision,
        )

    def _phase2_assertion_allowed(
        self,
        context: Phase2AssertionValidationContext,
        *,
        trait_family: str,
        trait_name: str,
        trait_value: Any,
    ) -> bool:
        if trait_family not in context.profile.allowed_assertion_families:
            return False
        if (
            context.assertion_scope == "topology_only"
            and trait_family not in _TOPOLOGY_ONLY_TRAIT_FAMILIES
        ):
            return False
        if not _profile_allows_assertion_trait(context.profile, trait_name):
            return False
        assertion_dict = {
            "trait_family": trait_family,
            "trait_name": trait_name,
            "trait_value": trait_value,
        }
        is_valid, _ = validate_assertion_candidate(assertion_dict)
        if not is_valid:
            return False
        return not is_leaf_fact_duplicate(context.duplicate_check_candidates, assertion_dict)

    def _normalize_phase2_assertion(
        self,
        assertion: Any,
        *,
        context: Phase2AssertionValidationContext,
        trait_family: str,
        trait_name: str,
        supporting_event_ids: list[str],
        supporting_claims: list[L2Phase1FactClaim],
        route: SemanticRouteDecision,
        trait_value: Any,
        promotion_decision: AssertionPromotionDecision,
    ) -> dict[str, Any]:
        event = context.event
        self_entity_id = context.host._resolve_self_entity_id(event)
        entity_ref = route.subject_id or _supporting_claim_subject(supporting_claims)
        expiry = promotion_decision.expiry
        temporal_scope = expiry.temporal_scope
        decay_policy = expiry.decay_policy
        expires_at = (
            event.timestamp + expiry.ttl_seconds if expiry.ttl_seconds is not None else None
        )
        return {
            "entity_id": entity_ref or self_entity_id or "",
            "entity_type": route.subject_type or "user",
            "trait_family": trait_family,
            "trait_name": trait_name,
            "trait_value": trait_value,
            "confidence_score": _supporting_claim_confidence(supporting_claims),
            "evidence_events": supporting_event_ids,
            "volatility_index": _volatility_for_temporal_scope(temporal_scope),
            "source_domain": event.memory_domain.label,
            "inference_depth": event.tom_depth.label,
            "validation_state": "tentative",
            "first_inferred_at": event.timestamp,
            "last_validated_at": event.timestamp,
            "target_entity_id": route.target_entity_id or "",
            "target_entity_type": route.target_entity_type or "",
            "target_scope": "entity_bound" if route.target_entity_id else "global",
            "temporal_scope": temporal_scope,
            "decay_policy": decay_policy,
            "decay_anchor_at": event.timestamp,
            "context_ref_id": "",
            "expires_at": expires_at,
            "memory_subdomain": classify_memory_subdomain(temporal_scope, decay_policy),
            "natural_summary": str(getattr(assertion, "natural_summary", "") or "")[:500],
            "semantic_route_key": route.route_key or "",
            "semantic_route_slot_key": route.slot_key or "",
            "route_contract_version": ROUTE_CONTRACT_VERSION,
            "supporting_claim_ids": [claim.claim_id for claim in supporting_claims],
        }

    def _evaluate_phase2_assertion_promotion(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        trait_family: str,
        trait_name: str,
        supporting_claims: list[L2Phase1FactClaim],
        supporting_event_ids: list[str],
    ) -> AssertionPromotionDecision:
        """Derive host-owned horizon and expiry from grounded evidence."""
        name_lower = trait_name.casefold()
        policy = get_assertion_family_policy(trait_family)
        baseline_scope: str | None
        baseline_decay: str | None
        baseline_ttl: float | None
        if name_lower in {"annoyance", "irritation", "frustration"}:
            baseline_scope = "momentary"
            baseline_decay = "fast_decay"
            baseline_ttl = momentary_ttl_seconds()
        else:
            baseline_scope = policy.default_temporal_scope if policy is not None else None
            baseline_decay = policy.default_decay_policy if policy is not None else None
            baseline_ttl = policy.default_ttl_seconds if policy is not None else None
        fact_kind = _promotion_fact_kind(supporting_claims)
        predicate = _promotion_predicate(supporting_claims)
        return evaluate_assertion_promotion(
            AssertionPromotionInput(
                trait_family=trait_family,
                fact_kind=fact_kind,
                predicate=predicate,
                evidence_class=_event_evidence_class(event),
                source_strength=_source_strength_for_claims(event, supporting_claims),
                temporal_cue=_promotion_temporal_cue(supporting_claims),
                observation_count=max(len(supporting_claims), len(supporting_event_ids)),
                evidence_count=len(supporting_event_ids),
                distinct_days=1 if supporting_event_ids else 0,
                span_days=0.0,
                recency_days=0.0,
                durable_permitted=_profile_permits_durable(event, profile, trait_family),
                baseline_temporal_scope=baseline_scope,
                baseline_decay_policy=baseline_decay,
                baseline_ttl_seconds=baseline_ttl,
            )
        )

    def _prepare_unified_assertion_candidates(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        graph_candidates: list[dict[str, Any]],
        resolved_context_refs: list[ResolvedContextRef],
        default_event_ids: list[str],
        raw_candidates: list[L2AssertionCandidate],
    ) -> tuple[list[dict[str, Any]], int]:
        if not policy.allow_assertion_write or not profile.allow_assertion:
            return [], 0

        scoped_assertions = self._apply_assertion_scope(
            raw_candidates=raw_candidates,
            assertion_scope=policy.assertion_scope,
        )
        prepared: list[dict[str, Any]] = []
        rejected_count = max(0, len(raw_candidates) - len(scoped_assertions))
        duplicate_check_candidates = [
            {
                "predicate": candidate["predicate"],
                "object_ref": candidate["object_id"],
            }
            for candidate in graph_candidates
        ]
        for raw_candidate in scoped_assertions:
            if raw_candidate.trait_family.casefold() not in profile.allowed_assertion_families:
                rejected_count += 1
                continue
            is_valid, _ = validate_assertion_candidate(raw_candidate.to_dict())
            if not is_valid:
                rejected_count += 1
                continue
            if is_leaf_fact_duplicate(duplicate_check_candidates, raw_candidate.to_dict()):
                rejected_count += 1
                continue
            supporting_event_ids = validate_supporting_event_ids(
                raw_candidate.supporting_event_ids,
                default_event_ids,
            )
            if not supporting_event_ids:
                rejected_count += 1
                continue
            prepared.append(
                self._normalize_assertion_candidate(
                    event,
                    raw_candidate,
                    resolved_context_refs,
                    supporting_event_ids=supporting_event_ids,
                )
            )
        return prepared, rejected_count

    def _normalize_assertion_candidate(
        self,
        event: MemoryEvent,
        candidate: L2AssertionCandidate,
        resolved_context_refs: list[ResolvedContextRef],
        *,
        supporting_event_ids: list[str],
    ) -> dict[str, Any]:
        host = self._assertion_host()
        trait_value = candidate.trait_value
        if isinstance(trait_value, (dict, list)):
            trait_value = json.dumps(trait_value, ensure_ascii=False, sort_keys=True)
        elif trait_value is None:
            trait_value = ""
        trait_value = str(trait_value)[:40]
        self_entity_id = host._resolve_self_entity_id(event)
        entity_ref = host._non_empty_text(candidate.entity_ref)
        if entity_ref and entity_ref.startswith("user:") and self_entity_id:
            entity_ref = self_entity_id
        target_entity_id, target_entity_type, context_ref_id = self._resolve_assertion_target(
            candidate=candidate,
            resolved_context_refs=resolved_context_refs,
        )
        temporal_scope, decay_policy, expires_at = self._derive_assertion_decay(
            event=event,
            candidate=candidate,
            target_entity_id=target_entity_id,
        )
        return {
            "entity_id": entity_ref or self_entity_id or "",
            "entity_type": candidate.entity_type or "user",
            "trait_family": candidate.trait_family.casefold(),
            "trait_name": candidate.trait_name,
            "trait_value": trait_value,
            "confidence_score": candidate.confidence,
            "evidence_events": supporting_event_ids,
            "volatility_index": candidate.volatility_index,
            "source_domain": event.memory_domain.label,
            "inference_depth": candidate.inference_depth or event.tom_depth.label,
            "validation_state": candidate.validation_state or "tentative",
            "first_inferred_at": event.timestamp,
            "last_validated_at": event.timestamp,
            "target_entity_id": target_entity_id or "",
            "target_entity_type": target_entity_type or "",
            "target_scope": "entity_bound" if target_entity_id else "global",
            "temporal_scope": temporal_scope,
            "decay_policy": decay_policy,
            "decay_anchor_at": event.timestamp,
            "context_ref_id": context_ref_id or "",
            "expires_at": expires_at,
            "memory_subdomain": classify_memory_subdomain(temporal_scope, decay_policy),
            "natural_summary": str(getattr(candidate, "natural_summary", "") or "")[:500],
        }

    def _resolve_assertion_target(
        self,
        *,
        candidate: L2AssertionCandidate,
        resolved_context_refs: list[ResolvedContextRef],
    ) -> tuple[str | None, str | None, str | None]:
        host = self._assertion_host()
        target_ref = host._non_empty_text(candidate.target_ref)
        explicit_target_entity_id = host._non_empty_text(candidate.target_entity_id)
        explicit_target_entity_type = host._normalize_entity_type(candidate.target_entity_type)
        if explicit_target_entity_id:
            return explicit_target_entity_id, explicit_target_entity_type, explicit_target_entity_id
        if not target_ref:
            return None, None, None
        target_ref_casefold = target_ref.casefold()
        for context_ref in resolved_context_refs:
            if (
                context_ref.surface
                and context_ref.resolved_ref
                and context_ref.surface.casefold() == target_ref_casefold
            ):
                kind = host._normalize_entity_type(
                    context_ref.resolved_kind
                ) or host._normalize_entity_type(context_ref.resolved_ref.split(":", 1)[0])
                return context_ref.resolved_ref, kind, context_ref.resolved_ref
        return None, None, None

    def _derive_assertion_decay(
        self,
        *,
        event: MemoryEvent,
        candidate: L2AssertionCandidate,
        target_entity_id: str | None,
    ) -> tuple[str, str, float | None]:
        host = self._assertion_host()
        temporal_scope = host._non_empty_text(candidate.temporal_scope)
        decay_policy = host._non_empty_text(candidate.decay_policy)
        expires_at = candidate.expires_at
        if temporal_scope and decay_policy:
            return (
                temporal_scope,
                decay_policy,
                float(expires_at) if expires_at is not None else None,
            )

        trait_family = candidate.trait_family.casefold()
        trait_name = candidate.trait_name.casefold()
        if target_entity_id and trait_name in {"annoyance", "irritation", "frustration"}:
            return "momentary", "fast_decay", event.timestamp + momentary_ttl_seconds()
        policy = get_assertion_family_policy(trait_family)
        if policy is not None:
            expires_at = (
                event.timestamp + policy.default_ttl_seconds
                if policy.default_ttl_seconds is not None
                else None
            )
            return policy.default_temporal_scope, policy.default_decay_policy, expires_at
        return "stable", "evidence_only", None

    def _apply_assertion_scope(
        self,
        *,
        raw_candidates: list[Any],
        assertion_scope: str,
    ) -> list[Any]:
        if assertion_scope == "none":
            return []
        if assertion_scope == "full":
            return list(raw_candidates)
        if assertion_scope == "topology_only":
            return [
                candidate
                for candidate in raw_candidates
                if candidate.trait_family.casefold() in _TOPOLOGY_ONLY_TRAIT_FAMILIES
            ]
        return []

    def _assertion_host(self) -> _L2AssertionHostProtocol:
        return self  # type: ignore[return-value]
