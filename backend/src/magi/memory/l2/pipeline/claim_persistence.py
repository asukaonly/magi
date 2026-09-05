"""Orchestration boundary for persisting grounded Phase 1 Claims."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, Protocol, cast

from ....core.logger import get_logger
from ....utils.calendar_timezone import calendar_timezone_id_from_metadata
from ...evidence import EvidenceClassification, classify_event_evidence
from ...event_contracts import MemoryEvent
from ..claims.identity import derive_claim_identity_key
from ..claims.models import (
    ClaimEntityRefInput,
    ClaimEvidenceInput,
    GroundedClaimInput,
    ProjectionOutcomeInput,
)
from ..models import L2Phase1FactClaim, L2ProjectionLease, ResolvedEntityMention
from ..ontology_aliases import canonicalize_predicate
from ..semantic_routing import (
    ROUTE_CONTRACT_VERSION,
    SemanticRouteDecision,
    SemanticRouteInput,
    derive_semantic_route,
)
from .extraction_contracts import ClaimProjectionOutcomeDraft, _PreparedExtractionBatch
from .history_markdown import (
    HISTORY_DOCUMENT_EVENT_TYPE,
    find_history_document_author_occurrence,
)
from .source_time_policy import resolve_event_time_semantics
from .temporal_claims import resolve_claim_temporal_fields

logger = get_logger("magi.memory.l2.pipeline")

EXTRACTOR_CONTRACT_VERSION = 4
EVIDENCE_RULE_VERSION = 2
ENTITY_RESOLUTION_VERSION = 1


class _ClaimPersistenceStoreProtocol(Protocol):
    async def touch_running_projection_jobs(
        self,
        leases: list[L2ProjectionLease],
    ) -> int: ...

    async def upsert_grounded_claim(
        self,
        *,
        claim: Any,
        evidence: Any,
        projection_leases: list[L2ProjectionLease],
    ) -> dict[str, Any]: ...

    async def upsert_claim_entity_ref(
        self,
        ref: ClaimEntityRefInput,
        *,
        projection_leases: list[L2ProjectionLease],
    ) -> dict[str, Any] | None: ...

    async def append_claim_projection_outcome(
        self,
        outcome: ProjectionOutcomeInput,
        *,
        projection_leases: list[L2ProjectionLease],
    ) -> dict[str, Any] | None: ...


class _ClaimPersistenceHostProtocol(Protocol):
    _cognition_store: _ClaimPersistenceStoreProtocol | None
    _l1_store: Any

    def _normalize_entity_type(self, raw_value: Any) -> str | None: ...

    def _resolve_phase2_object_id(
        self,
        *,
        raw_object_ref: Any,
        object_type: str | None,
        resolved_mentions: list[ResolvedEntityMention],
        catalog_name_index: dict[str, str] | None,
    ) -> str | None: ...


class L2ClaimPersistenceMixin:
    """Persist grounded Claims before optional entity resolution and Phase 2."""

    async def _assert_current_projection_attempt(
        self,
        batch: _PreparedExtractionBatch,
    ) -> None:
        host = self._claim_persistence_host()
        if not batch.projection_leases:
            return
        if host._cognition_store is None:
            raise RuntimeError("L2 cognition store is unavailable")
        touched = await host._cognition_store.touch_running_projection_jobs(batch.projection_leases)
        if touched != len(batch.projection_leases):
            raise RuntimeError("projection_attempt_fenced")

    async def _persist_grounded_phase1_claims(
        self,
        batch: _PreparedExtractionBatch,
        phase1_result: Any,
    ) -> None:
        """Assign stable IDs by writing Claims and normalized event provenance."""

        host = self._claim_persistence_host()
        if not batch.projection_leases:
            logger.warning(
                "L2 grounded Claims remain transient without a durable projection lease",
                event_id=batch.stored_event.event_id,
            )
            return
        if host._cognition_store is None:
            raise RuntimeError("L2 cognition store is unavailable")

        await self._assert_current_projection_attempt(batch)
        antecedent_events = await _load_antecedent_events(host, phase1_result)
        retained_claims: list[L2Phase1FactClaim] = []
        blocked_count = 0
        for claim in phase1_result.fact_claims:
            event_links = _claim_event_links(
                batch,
                claim,
                antecedent_events=antecedent_events,
            )
            if not event_links:
                blocked_count += 1
                continue
            subject_ref = _canonical_subject_ref(batch, claim)
            canonical_predicate = (
                canonicalize_predicate(claim.predicate) or str(claim.predicate or "").strip()
            )
            fact_kind = str(getattr(claim.fact_kind, "value", claim.fact_kind) or "explicit_fact")
            evidence_mode = str(getattr(claim.evidence_mode, "value", claim.evidence_mode))
            temporal = resolve_claim_temporal_fields(
                raw_expression=claim.raw_time_expression,
                future_intent=fact_kind == "future_intent",
                evidence=event_links,
            )
            claim.fact_valid_from = temporal.fact_valid_from
            claim.fact_valid_to = temporal.fact_valid_to
            claim.target_from = temporal.target_from
            claim.target_to = temporal.target_to
            claim.raw_time_frame = temporal.raw_time_frame
            identity_key = derive_claim_identity_key(
                extractor_contract_version=EXTRACTOR_CONTRACT_VERSION,
                evidence_rule_version=EVIDENCE_RULE_VERSION,
                user_id=batch.stored_event.user_id,
                subject_ref=subject_ref,
                subject_type=str(claim.subject_type or "user"),
                canonical_predicate=canonical_predicate,
                fact_kind=fact_kind,
                object_type=str(claim.object_type or "entity"),
                polarity=str(claim.polarity or "positive"),
                specificity=str(claim.specificity or "concrete"),
                temporal_cue=str(getattr(claim.temporal_cue, "value", claim.temporal_cue)),
                fact_valid_from=claim.fact_valid_from,
                fact_valid_to=claim.fact_valid_to,
                target_from=claim.target_from,
                target_to=claim.target_to,
                raw_time_frame=claim.raw_time_frame,
                evidence_mode=evidence_mode,
                object_surface=str(claim.object_ref or ""),
                object_value=str(claim.object_ref or ""),
                supporting_event_ids=claim.supporting_event_ids,
                antecedent_event_ids=claim.antecedent_event_ids,
            )
            stored = await host._cognition_store.upsert_grounded_claim(
                claim=GroundedClaimInput(
                    identity_key=identity_key,
                    extractor_contract_version=EXTRACTOR_CONTRACT_VERSION,
                    evidence_rule_version=EVIDENCE_RULE_VERSION,
                    origin_attempt_key=batch.attempt_key,
                    profile_id=batch.extraction_profile.profile_id,
                    user_id=batch.stored_event.user_id,
                    subject_ref=subject_ref,
                    subject_type=str(claim.subject_type or "user"),
                    canonical_predicate=canonical_predicate,
                    fact_kind=fact_kind,
                    object_type=str(claim.object_type or "entity"),
                    polarity=str(claim.polarity or "positive"),
                    specificity=str(claim.specificity or "concrete"),
                    confidence=float(claim.confidence or 0.0),
                    object_value=str(claim.object_ref or ""),
                    object_surface=str(claim.object_ref or ""),
                    temporal_cue=str(getattr(claim.temporal_cue, "value", claim.temporal_cue)),
                    fact_valid_from=claim.fact_valid_from,
                    fact_valid_to=claim.fact_valid_to,
                    target_from=claim.target_from,
                    target_to=claim.target_to,
                    raw_time_frame=claim.raw_time_frame,
                ),
                evidence=event_links,
                projection_leases=batch.projection_leases,
            )
            if stored.get("replay_blocked") or not stored.get("claim_id"):
                blocked_count += 1
                continue
            claim.claim_id = str(stored["claim_id"])
            claim.fact_valid_from = _optional_float(stored.get("fact_valid_from"))
            claim.fact_valid_to = _optional_float(stored.get("fact_valid_to"))
            claim.target_from = _optional_float(stored.get("target_from"))
            claim.target_to = _optional_float(stored.get("target_to"))
            stored_time_frame = stored.get("raw_time_frame")
            claim.raw_time_frame = (
                dict(stored_time_frame) if isinstance(stored_time_frame, Mapping) else None
            )
            retained_claims.append(claim)
            if batch.self_entity_id and subject_ref == batch.self_entity_id:
                await host._cognition_store.upsert_claim_entity_ref(
                    ClaimEntityRefInput(
                        claim_id=claim.claim_id,
                        ref_role="subject",
                        entity_id=batch.self_entity_id,
                        resolution_version=ENTITY_RESOLUTION_VERSION,
                    ),
                    projection_leases=batch.projection_leases,
                )
        phase1_result.fact_claims = retained_claims
        if blocked_count:
            phase1_result.diagnostics["replay_blocked_claim_count"] = blocked_count
            logger.info(
                "L2 grounded Claims blocked by source governance",
                event_id=batch.stored_event.event_id,
                blocked_claim_count=blocked_count,
            )

    async def _persist_grounded_claim_entity_refs(
        self,
        batch: _PreparedExtractionBatch,
        phase1_result: Any,
        resolved_mentions: list[ResolvedEntityMention],
    ) -> dict[str, tuple[str, str]]:
        """Append versioned object resolver enrichments without mutating Claims."""

        host = self._claim_persistence_host()
        if host._cognition_store is None or not batch.projection_leases:
            return {}
        await self._assert_current_projection_attempt(batch)
        object_refs: dict[str, tuple[str, str]] = {}
        for claim in phase1_result.fact_claims:
            object_type = host._normalize_entity_type(claim.object_type)
            object_id = host._resolve_phase2_object_id(
                raw_object_ref=claim.object_ref,
                object_type=object_type,
                resolved_mentions=resolved_mentions,
                catalog_name_index=batch.catalog_name_index,
            )
            if not object_id:
                continue
            stored_ref = await host._cognition_store.upsert_claim_entity_ref(
                ClaimEntityRefInput(
                    claim_id=claim.claim_id,
                    ref_role="object",
                    entity_id=object_id,
                    resolution_version=ENTITY_RESOLUTION_VERSION,
                ),
                projection_leases=batch.projection_leases,
            )
            if stored_ref is None:
                continue
            persisted_object_id = str(stored_ref["entity_id"])
            object_refs[claim.claim_id] = (
                persisted_object_id,
                object_type or str(claim.object_type or "other"),
            )
        return object_refs

    async def _route_grounded_phase1_claims(
        self,
        batch: _PreparedExtractionBatch,
        phase1_result: Any,
        *,
        object_refs: dict[str, tuple[str, str]],
    ) -> dict[str, SemanticRouteDecision]:
        """Derive and persist one exhaustive host route outcome per Claim."""

        host = self._claim_persistence_host()
        if host._cognition_store is None or not batch.projection_leases:
            return {}
        await self._assert_current_projection_attempt(batch)
        decisions: dict[str, SemanticRouteDecision] = {}
        for claim in phase1_result.fact_claims:
            object_ref = object_refs.get(claim.claim_id)
            canonical_predicate = (
                canonicalize_predicate(claim.predicate)
                or str(claim.predicate or "").strip().upper()
            )
            decision = derive_semantic_route(
                SemanticRouteInput(
                    claim_id=claim.claim_id,
                    subject_id=_canonical_subject_ref(batch, claim),
                    subject_type=str(claim.subject_type or "user"),
                    canonical_predicate=canonical_predicate,
                    fact_kind=str(claim.fact_kind or "explicit_fact"),
                    polarity=claim.polarity,
                    object_type=(
                        object_ref[1]
                        if object_ref is not None
                        else str(claim.object_type or "other")
                    ),
                    object_value=claim.object_ref,
                    object_entity_id=object_ref[0] if object_ref is not None else None,
                    temporal_cue=str(getattr(claim.temporal_cue, "value", claim.temporal_cue)),
                    specificity=str(claim.specificity or "concrete"),
                    target_from=claim.target_from,
                    target_to=claim.target_to,
                    raw_time_expression=claim.raw_time_expression,
                    time_resolution=(
                        str(claim.raw_time_frame.get("resolution") or "")
                        if claim.raw_time_frame is not None
                        else "unscheduled"
                    ),
                    time_frame=claim.raw_time_frame,
                )
            )
            stored = await host._cognition_store.append_claim_projection_outcome(
                ProjectionOutcomeInput(
                    claim_id=claim.claim_id,
                    attempt_key=batch.attempt_key,
                    target_kind="route",
                    target_id=decision.route_key or f"predicate:{canonical_predicate}",
                    target_slot_key=decision.slot_key,
                    route_contract_version=ROUTE_CONTRACT_VERSION,
                    outcome=decision.disposition.value,
                    reason_code=decision.reason_code,
                    details=_route_outcome_details(
                        decision,
                        subject_resolution_version=(
                            ENTITY_RESOLUTION_VERSION
                            if batch.self_entity_id
                            and decision.subject_id == batch.self_entity_id
                            else 0
                        ),
                        object_resolution_version=(
                            ENTITY_RESOLUTION_VERSION if object_ref is not None else 0
                        ),
                    ),
                ),
                projection_leases=batch.projection_leases,
            )
            if stored is None:
                raise RuntimeError("active grounded Claim did not accept a route outcome")
            decisions[claim.claim_id] = decision
        return decisions

    async def _persist_claim_projection_outcomes(
        self,
        batch: _PreparedExtractionBatch,
        outcomes: list[ClaimProjectionOutcomeDraft],
    ) -> None:
        """Append final target outcomes while the exact projection lease is live."""

        host = self._claim_persistence_host()
        if host._cognition_store is None or not batch.projection_leases:
            return
        await self._assert_current_projection_attempt(batch)
        seen: set[tuple[str, str, str]] = set()
        for draft in outcomes:
            claim_id = str(draft.claim_id or "").strip()
            if not claim_id:
                continue
            key = (claim_id, draft.target_kind, draft.target_id)
            if key in seen:
                continue
            seen.add(key)
            stored = await host._cognition_store.append_claim_projection_outcome(
                ProjectionOutcomeInput(
                    claim_id=claim_id,
                    attempt_key=batch.attempt_key,
                    target_kind=draft.target_kind,
                    target_id=draft.target_id,
                    target_slot_key=draft.target_slot_key,
                    route_contract_version=ROUTE_CONTRACT_VERSION,
                    outcome=draft.outcome,
                    reason_code=draft.reason_code,
                    details=draft.details,
                ),
                projection_leases=batch.projection_leases,
            )
            if stored is None:
                raise RuntimeError("active grounded Claim did not accept a target outcome")

    def _claim_persistence_host(self) -> _ClaimPersistenceHostProtocol:
        return cast(_ClaimPersistenceHostProtocol, self)


def _canonical_subject_ref(
    batch: _PreparedExtractionBatch,
    claim: L2Phase1FactClaim,
) -> str:
    subject_ref = str(claim.subject_ref or "").strip()
    if subject_ref.startswith("user:") and batch.self_entity_id:
        return cast(str, batch.self_entity_id)
    return subject_ref


def _claim_event_links(
    batch: _PreparedExtractionBatch,
    claim: L2Phase1FactClaim,
    *,
    antecedent_events: dict[str, MemoryEvent],
) -> list[ClaimEvidenceInput]:
    events = {batch_event.event_id: batch_event for batch_event in batch.event_window.events}
    classifications: dict[str, EvidenceClassification] = {
        event.event_id: classification for event, classification, _policy in batch.eligible_events
    }
    evidence_mode = str(getattr(claim.evidence_mode, "value", claim.evidence_mode))
    links: list[ClaimEvidenceInput] = []
    for event_id in claim.supporting_event_ids:
        batch_event = events.get(event_id)
        if batch_event is None:
            continue
        time_semantics = resolve_event_time_semantics(batch_event)
        classification = classifications.get(event_id)
        links.append(
            ClaimEvidenceInput(
                event_id=event_id,
                link_role="supporting",
                required_for_grounding=False,
                event_time=batch_event.timestamp,
                timestamp_confidence=time_semantics.timestamp_confidence,
                timestamp_quality=time_semantics.timestamp_quality,
                timestamp_anchor_source=time_semantics.timestamp_anchor_source,
                evidence_rule_version=EVIDENCE_RULE_VERSION,
                evidence_mode=evidence_mode,
                source_type=batch_event.source,
                source_domain=_event_memory_domain(batch, event_id),
                author_type=batch_event.author_type,
                evidence_class=(
                    classification.evidence_class if classification is not None else None
                ),
                evidence_locator=_evidence_locator(
                    batch_event.content,
                    claim.evidence_text,
                    event_type=batch_event.event_type,
                ),
                calendar_timezone_id=calendar_timezone_id_from_metadata(
                    batch_event.metadata_json
                ),
            )
        )
    for event_id in claim.antecedent_event_ids:
        antecedent_event = antecedent_events.get(event_id)
        if antecedent_event is None:
            continue
        time_semantics = resolve_event_time_semantics(antecedent_event)
        classification = classify_event_evidence(antecedent_event)
        links.append(
            ClaimEvidenceInput(
                event_id=event_id,
                link_role="antecedent",
                required_for_grounding=True,
                event_time=antecedent_event.timestamp,
                timestamp_confidence=time_semantics.timestamp_confidence,
                timestamp_quality=time_semantics.timestamp_quality,
                timestamp_anchor_source=time_semantics.timestamp_anchor_source,
                evidence_rule_version=EVIDENCE_RULE_VERSION,
                evidence_mode=evidence_mode,
                source_type=antecedent_event.source,
                source_domain=antecedent_event.memory_domain.label,
                author_type=antecedent_event.author_type,
                evidence_class=classification.evidence_class,
                calendar_timezone_id=calendar_timezone_id_from_metadata(
                    antecedent_event.metadata_json
                ),
            )
        )
    return links


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def _load_antecedent_events(
    host: _ClaimPersistenceHostProtocol,
    phase1_result: Any,
) -> dict[str, MemoryEvent]:
    event_ids = sorted(
        {
            str(event_id).strip()
            for claim in phase1_result.fact_claims
            for event_id in claim.antecedent_event_ids
            if str(event_id).strip()
        }
    )
    if not event_ids:
        return {}
    if host._l1_store is None:
        raise RuntimeError("L1 event store is unavailable for Claim antecedents")
    hydrated: dict[str, MemoryEvent] = {}
    for event_id in event_ids:
        event = await host._l1_store.get_memory_event(event_id)
        if event is None:
            raise RuntimeError(f"Claim antecedent event is unavailable: {event_id}")
        hydrated[event_id] = event
    return hydrated


def _event_memory_domain(batch: _PreparedExtractionBatch, event_id: str) -> str | None:
    for event, _classification, _policy in batch.eligible_events:
        if event.event_id == event_id:
            return cast(str | None, event.memory_domain.label)
    return None


def _evidence_locator(
    content: str,
    evidence_text: str,
    *,
    event_type: str = "",
) -> dict[str, Any]:
    quote = str(evidence_text or "")
    is_history_document = event_type == HISTORY_DOCUMENT_EVENT_TYPE
    if is_history_document:
        occurrence = find_history_document_author_occurrence(content, quote)
        start, end = occurrence if occurrence is not None else (-1, -1)
    else:
        start = str(content or "").find(quote) if quote else -1
        end = start + len(quote) if start >= 0 else -1
    locator = {
        "start": start if start >= 0 else None,
        "end": end if end >= 0 else None,
        "quote_hash": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
    }
    if is_history_document:
        locator["attribution"] = "author_prose" if start >= 0 else None
    return locator


def _route_outcome_details(
    decision: SemanticRouteDecision,
    *,
    subject_resolution_version: int,
    object_resolution_version: int,
) -> dict[str, Any]:
    return {
        "semantic_route_id": decision.semantic_route_id,
        "family": decision.family,
        "trait_code": decision.trait_code,
        "object_role": decision.object_role.value,
        "projection_targets": sorted(target.value for target in decision.projection_targets),
        "value_fingerprint": decision.value_fingerprint,
        "semantic_target_key": decision.semantic_target_key,
        "object_surface": decision.object_surface,
        "normalized_target_text": decision.normalized_target_text,
        "target_entity_type": decision.target_entity_type,
        "goal_lineage_key": decision.goal_lineage_key,
        "target_window_key": decision.target_window_key,
        "scope_key": decision.scope_key,
        "subject_resolution_version": max(0, int(subject_resolution_version)),
        "object_resolution_version": max(0, int(object_resolution_version)),
    }


__all__ = [
    "EVIDENCE_RULE_VERSION",
    "ENTITY_RESOLUTION_VERSION",
    "EXTRACTOR_CONTRACT_VERSION",
    "L2ClaimPersistenceMixin",
]
