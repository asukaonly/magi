"""Deterministic L2 graph and assertion projection flow."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ..claim_text import load_claim_texts
from ..assertions.materialize import (
    MaterializationDecision,
    MaterializationInput,
    materialize_assertion,
)
from ..assertions.occurrence_stats import (
    ClaimOccurrenceStats,
    ClaimRouteValueKey,
    load_routed_claim_occurrence_stats,
)
from ..claims.outcomes import ClaimTargetOutcomeContext
from ..phase1_models import L2Phase1FactClaim
from ..reviews import PendingReviewProposal
from ..semantic_routing import ROUTE_CONTRACT_VERSION, SemanticRouteDecision
from .claim_evidence import resolve_claim_graph_sources
from .claim_persistence import EVIDENCE_RULE_VERSION
from .event_entity_map import build_event_entity_map
from .extraction_contracts import (
    ClaimProjectionOutcomeDraft,
    _Phase1ExtractionFlow,
    _PreparedExtractionBatch,
)

logger = get_logger("magi.memory.l2.pipeline")


def _degraded_stages(phase1_flow: _Phase1ExtractionFlow) -> list[str]:
    raw_stages = phase1_flow.phase1_result.diagnostics.get("degraded_stages", [])
    if not isinstance(raw_stages, list):
        return []
    return list(
        dict.fromkeys(
            stage.strip() for stage in raw_stages if isinstance(stage, str) and stage.strip()
        )
    )


def _route_group_key(route: SemanticRouteDecision) -> ClaimRouteValueKey:
    slot_key = str(route.slot_key or "").strip()
    value_fingerprint = str(route.value_fingerprint or "").strip()
    if not slot_key or not value_fingerprint:
        raise RuntimeError("routed Claim is missing its materialization identity")
    return ClaimRouteValueKey(slot_key, value_fingerprint)


def _claim_groups(
    phase1_flow: _Phase1ExtractionFlow,
) -> dict[ClaimRouteValueKey, tuple[SemanticRouteDecision, tuple[L2Phase1FactClaim, ...]]]:
    claims_by_id = {
        claim.claim_id: claim
        for claim in phase1_flow.phase1_result.fact_claims
        if str(claim.claim_id or "").strip()
    }
    grouped: dict[ClaimRouteValueKey, list[L2Phase1FactClaim]] = defaultdict(list)
    route_by_key: dict[ClaimRouteValueKey, SemanticRouteDecision] = {}
    for claim_id, route in phase1_flow.semantic_routes.items():
        if not route.can_project_assertion:
            continue
        claim = claims_by_id.get(claim_id)
        if claim is None:
            continue
        key = _route_group_key(route)
        grouped[key].append(claim)
        route_by_key[key] = route
    return {
        key: (route_by_key[key], tuple(sorted(claims, key=lambda claim: claim.claim_id)))
        for key, claims in grouped.items()
    }


def _materialization_outcomes(
    decision: MaterializationDecision,
    claims: tuple[L2Phase1FactClaim, ...],
) -> list[ClaimProjectionOutcomeDraft]:
    if decision.action in {"write", "review"}:
        return []
    target_id = f"slot:{decision.slot_key}" if decision.slot_key else "assertion:unrouted"
    return [
        ClaimProjectionOutcomeDraft(
            claim_id=claim.claim_id,
            target_kind="assertion",
            target_id=target_id,
            target_slot_key=decision.slot_key,
            outcome=decision.action,
            reason_code=decision.reason_code,
        )
        for claim in claims
    ]


def _pending_review_kind(decision: MaterializationDecision) -> str:
    if decision.family == "goal_profile":
        return "goal_currentness"
    if decision.reason_code in {"low_time_confidence", "assertion_currentness"}:
        return "assertion_currentness"
    return "materialization"


def _ensure_terminal_assertion_outcomes(
    phase1_flow: _Phase1ExtractionFlow,
    *,
    atomically_completed_claim_ids: set[str],
) -> None:
    completed = {
        outcome.claim_id
        for outcome in phase1_flow.claim_outcomes
        if outcome.target_kind == "assertion"
    }.union(atomically_completed_claim_ids)
    missing = [
        claim_id
        for claim_id, route in phase1_flow.semantic_routes.items()
        if route.can_project_assertion and claim_id not in completed
    ]
    if missing:
        raise RuntimeError(
            "routed Claims are missing terminal Assertion outcomes: " + ", ".join(sorted(missing))
        )


class L2ProjectionFlowMixin:
    """Persist Claim projections with model-independent Assertion semantics."""

    async def _run_projection_flow(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
    ) -> dict[str, Any]:
        graph_candidates, graph_rejections = self._project_phase1_graph_candidates(
            phase1_result=phase1_flow.phase1_result,
            semantic_routes=phase1_flow.semantic_routes,
            event=batch.stored_event,
            evidence_event_ids=batch.batch_event_ids,
            resolved_mentions=phase1_flow.resolved_mentions,
            catalog_name_index=batch.catalog_name_index,
            profile=batch.extraction_profile,
            claim_sources=resolve_claim_graph_sources(phase1_flow.phase1_result.fact_claims, batch.eligible_events),
        )
        phase1_flow.claim_outcomes.extend(graph_rejections)
        focal_entities = self._build_focal_entities(
            batch.stored_event,
            phase1_flow.resolved_mentions,
        )
        await self._emit_active_entities(event=batch.stored_event, focal_entities=focal_entities)

        groups = _claim_groups(phase1_flow)
        occurrence_stats = await self._load_materialization_occurrence_stats(groups)
        claim_texts = {}
        if groups:
            async with sqlite_connection_async(self._cognition_store.db_path) as db:
                claim_texts = await load_claim_texts(
                    db, [claim.claim_id for _route, claims in groups.values() for claim in claims]
                )
        decisions: list[MaterializationDecision] = []
        assertion_candidates: list[dict[str, Any]] = []
        pending_review_proposals: list[PendingReviewProposal] = []
        for key, (route, claims) in sorted(groups.items(), key=lambda item: item[0].target_slot_key):
            stats = occurrence_stats.get(key)
            if stats is None:
                raise RuntimeError(
                    f"routed Claim is missing durable occurrence statistics: {key.target_slot_key}"
                )
            decision = materialize_assertion(
                MaterializationInput(
                    route=route,
                    claims=claims,
                    occurrence_stats=stats,
                    self_entity_id=str(batch.self_entity_id or ""),
                    direct_assertion_write_allowed=stats.evidence_class == "user_self_report",
                    profile_allows_assertion=bool(batch.extraction_profile.allow_assertion),
                    allowed_families=frozenset(
                        batch.extraction_profile.allowed_assertion_families
                    ),
                    allowed_traits=batch.extraction_profile.allowed_assertion_traits,
                    source_domain=batch.stored_event.memory_domain.label,
                    inference_depth=batch.stored_event.tom_depth.label,
                    observed_at=float(batch.stored_event.timestamp),
                    now=datetime.now().timestamp(),
                    claim_texts=claim_texts,
                )
            )
            decisions.append(decision)
            phase1_flow.claim_outcomes.extend(_materialization_outcomes(decision, claims))
            if decision.candidate is not None:
                assertion_candidates.append(decision.candidate)
            if decision.action == "review":
                if decision.review_proposal is None or not decision.slot_key:
                    raise RuntimeError("review materialization is missing its host proposal")
                pending_review_proposals.append(
                    PendingReviewProposal(
                        subject_id=route.subject_id or str(batch.self_entity_id or ""),
                        kind=_pending_review_kind(decision),  # type: ignore[arg-type]
                        slot_key=decision.slot_key,
                        value_fingerprint=decision.value_fingerprint or "",
                        semantic_lineage_key=decision.semantic_lineage_key or "",
                        claim_ids=tuple(claim.claim_id for claim in claims),
                        reason_code=decision.reason_code,
                        proposed=decision.review_proposal,
                        route_contract_version=ROUTE_CONTRACT_VERSION,
                        evidence_rule_version=EVIDENCE_RULE_VERSION,
                    )
                )

        return await L2ProjectionFlowMixin._persist_materialization_result(
            self,
            batch=batch,
            phase1_flow=phase1_flow,
            graph_candidates=graph_candidates,
            assertion_candidates=assertion_candidates,
            pending_review_proposals=pending_review_proposals,
            decisions=decisions,
            rejected_graph_count=len(graph_rejections),
        )

    async def _load_materialization_occurrence_stats(
        self: Any,
        groups: dict[
            ClaimRouteValueKey,
            tuple[SemanticRouteDecision, tuple[L2Phase1FactClaim, ...]],
        ],
    ) -> dict[ClaimRouteValueKey, ClaimOccurrenceStats]:
        if not groups:
            return {}
        if self._cognition_store is None:
            raise RuntimeError("L2 cognition store is unavailable for occurrence statistics")
        stats: dict[ClaimRouteValueKey, ClaimOccurrenceStats] = await load_routed_claim_occurrence_stats(
            self._cognition_store.db_path,
            keys=set(groups),
            local_timezone=datetime.now().astimezone().tzinfo,
        )
        missing = set(groups).difference(stats)
        if missing:
            raise RuntimeError(
                "routed Claims are missing durable occurrence statistics: "
                + ", ".join(sorted(key.target_slot_key for key in missing))
            )
        return stats

    async def _persist_materialization_result(
        self: Any,
        *,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
        graph_candidates: list[dict[str, Any]],
        assertion_candidates: list[dict[str, Any]],
        pending_review_proposals: list[PendingReviewProposal],
        decisions: list[MaterializationDecision],
        rejected_graph_count: int,
    ) -> dict[str, Any]:
        await self._assert_current_projection_attempt(batch)
        relation_count, _facet_count, assertion_count = await self._persist_extraction_outputs(
            graph_candidates=graph_candidates,
            direct_write_candidates=batch.direct_write_candidates,
            facet_candidates=[],
            assertion_candidates=assertion_candidates,
            contradiction_hints=[],
            attempt_key=batch.attempt_key,
            route_contract_version=ROUTE_CONTRACT_VERSION,
            projection_leases=batch.projection_leases,
        )
        atomic_claim_ids = {
            str(claim_id)
            for candidate in assertion_candidates
            for claim_id in candidate.get("supporting_claim_ids", [])
            if str(claim_id or "").strip()
        }
        review_count = 0
        if pending_review_proposals:
            if self._cognition_store is None:
                raise RuntimeError("L2 cognition store is unavailable for pending reviews")
            for proposal in pending_review_proposals:
                result = await self._cognition_store.upsert_pending_review_with_receipt(
                    proposal,
                    claim_outcome_context=ClaimTargetOutcomeContext(
                        claim_ids=proposal.claim_ids,
                        attempt_key=batch.attempt_key,
                        route_contract_version=ROUTE_CONTRACT_VERSION,
                    ),
                    projection_leases=batch.projection_leases,
                )
                atomic_claim_ids.update(result.atomically_completed_claim_ids)
                if result.status == "pending":
                    review_count += 1
        _ensure_terminal_assertion_outcomes(
            phase1_flow,
            atomically_completed_claim_ids=atomic_claim_ids,
        )
        await self._persist_claim_projection_outcomes(batch, phase1_flow.claim_outcomes)

        touched_entity_ids = self._collect_touched_entities(
            graph_candidates + batch.direct_write_candidates,
            assertion_candidates,
        )
        touched_place_ids, touched_topic_keys = await self._derive_place_and_topic_hints(
            touched_entity_ids
        )
        materialization_by_action: dict[str, int] = {}
        for decision in decisions:
            materialization_by_action[decision.action] = (
                materialization_by_action.get(decision.action, 0) + 1
            )
        logger.info(
            "L2 Claim projections persisted",
            event_id=batch.stored_event.event_id,
            relation_count=relation_count,
            assertion_count=assertion_count,
            review_count=review_count,
            materialization_by_action=materialization_by_action,
        )
        return {
            "relation_count": relation_count,
            "assertion_count": assertion_count,
            "review_count": review_count,
            "touched_entity_ids": touched_entity_ids,
            "touched_place_ids": touched_place_ids,
            "touched_topic_keys": touched_topic_keys,
            "event_entity_map": build_event_entity_map(
                graph_candidates + batch.direct_write_candidates + assertion_candidates
            ),
            "snapshot_refresh_entity_ids": [],
            "skipped": False,
            "evidence_class": batch.classification.evidence_class,
            "profile_id": batch.extraction_profile.profile_id,
            "mention_count": len(phase1_flow.phase1_result.entities),
            "resolved_context_ref_count": len(phase1_flow.phase1_result.resolved_refs),
            "graph_candidate_count": len(graph_candidates),
            "direct_write_count": batch.direct_write_count,
            "materialization_count": len(decisions),
            "materialization_by_action": materialization_by_action,
            "rejected_graph_candidate_count": rejected_graph_count,
            "degraded_stages": _degraded_stages(phase1_flow),
        }


__all__ = ["L2ProjectionFlowMixin"]
