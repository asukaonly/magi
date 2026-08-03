"""L2 Phase 1 graph projection and Phase 2 inference flow."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ....core.logger import get_logger
from ..assertions.occurrence_stats import (
    ClaimOccurrenceStats,
    ClaimRouteValueKey,
    load_routed_claim_occurrence_stats,
)
from ..corrections.fingerprints import relationship_triple_id, scope_key
from ..llm_json_client import L2LLMJsonError
from ..models import L2ConflictArbitrationResult, L2FocalEntityRef
from ..semantic_routing import ROUTE_CONTRACT_VERSION
from .event_entity_map import build_event_entity_map
from .extraction_contracts import (
    ClaimProjectionOutcomeDraft,
    _Phase1ExtractionFlow,
    _Phase2CandidateSet,
    _Phase2Context,
    _PreparedExtractionBatch,
)
from .validation.claim_assessments import (
    AssessmentActionEligibility,
    ValidatedClaimAssessment,
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


def _record_degraded_stage(
    phase1_flow: _Phase1ExtractionFlow,
    stage: str,
) -> None:
    degraded_stages = _degraded_stages(phase1_flow)
    if stage not in degraded_stages:
        degraded_stages.append(stage)
    phase1_flow.phase1_result.diagnostics["degraded_stages"] = degraded_stages


def _ensure_assertion_outcomes(
    phase1_flow: _Phase1ExtractionFlow,
    *,
    reason_code: str,
    atomically_completed_claim_ids: set[str] | None = None,
) -> None:
    completed_claim_ids = {
        outcome.claim_id
        for outcome in phase1_flow.claim_outcomes
        if outcome.target_kind == "assertion"
    }
    completed_claim_ids.update(atomically_completed_claim_ids or set())
    for claim_id, route in phase1_flow.semantic_routes.items():
        if not route.can_project_assertion or claim_id in completed_claim_ids:
            continue
        phase1_flow.claim_outcomes.append(
            ClaimProjectionOutcomeDraft(
                claim_id=claim_id,
                target_kind="assertion",
                target_id=f"slot:{route.slot_key}",
                target_slot_key=route.slot_key,
                outcome="skipped",
                reason_code=reason_code,
            )
        )


def _record_scoped_candidate_outcomes(
    phase1_flow: _Phase1ExtractionFlow,
    candidates: _Phase2CandidateSet,
    *,
    claim_ids: set[str],
    reason_code: str,
) -> None:
    for candidate in candidates.graph_candidates:
        claim_id = str(candidate.get("_claim_id") or "").strip()
        if not claim_id or claim_id not in claim_ids:
            continue
        phase1_flow.claim_outcomes.append(
            ClaimProjectionOutcomeDraft(
                claim_id=claim_id,
                target_kind="relationship",
                target_id=str(
                    relationship_triple_id(
                        subject_id=str(candidate.get("subject_id") or ""),
                        predicate=str(candidate.get("predicate") or ""),
                        object_id=str(candidate.get("object_id") or ""),
                        scope_key_value=scope_key(candidate.get("scope")),
                    )
                ),
                outcome="skipped",
                reason_code=reason_code,
            )
        )
    for candidate in candidates.assertion_candidates:
        slot_key = str(candidate.get("semantic_route_slot_key") or "").strip()
        for claim_id in candidate.get("supporting_claim_ids", []):
            normalized_claim_id = str(claim_id or "").strip()
            if not normalized_claim_id or normalized_claim_id not in claim_ids:
                continue
            phase1_flow.claim_outcomes.append(
                ClaimProjectionOutcomeDraft(
                    claim_id=normalized_claim_id,
                    target_kind="assertion",
                    target_id=(f"slot:{slot_key}" if slot_key else f"claim:{normalized_claim_id}"),
                    target_slot_key=slot_key or None,
                    outcome="skipped",
                    reason_code=reason_code,
                )
            )


def _append_assessment_outcome(
    phase1_flow: _Phase1ExtractionFlow,
    assessment: ValidatedClaimAssessment,
    *,
    outcome: str,
    reason_code: str,
) -> None:
    phase1_flow.claim_outcomes.append(
        ClaimProjectionOutcomeDraft(
            claim_id=assessment.claim_id,
            target_kind="assessment",
            target_id=assessment.target_id,
            target_slot_key=assessment.target_slot_key,
            outcome=outcome,
            reason_code=reason_code,
            details={
                "compatibility": assessment.compatibility,
                "same_value": assessment.same_value,
                "independent_evidence": assessment.independent_evidence,
                "target_record_type": assessment.target_record_type,
                "related_record_id": assessment.related_record_id,
                "relationship": assessment.relationship,
            },
        )
    )


def _record_terminal_validation_outcomes(
    phase1_flow: _Phase1ExtractionFlow,
    assessments: list[ValidatedClaimAssessment],
) -> None:
    outcome_by_action = {
        AssessmentActionEligibility.REJECTED: "rejected",
        AssessmentActionEligibility.NOOP: "noop",
        AssessmentActionEligibility.QUARANTINED: "quarantined",
        AssessmentActionEligibility.REVALIDATE: "revalidated",
    }
    for assessment in assessments:
        outcome = outcome_by_action.get(assessment.action_eligibility)
        if outcome is None:
            continue
        _append_assessment_outcome(
            phase1_flow,
            assessment,
            outcome=outcome,
            reason_code=assessment.reason_code,
        )


def _candidate_claim_ids(candidate: dict[str, Any]) -> set[str]:
    graph_claim_id = str(candidate.get("_claim_id") or "").strip()
    if graph_claim_id:
        return {graph_claim_id}
    return {
        normalized
        for claim_id in candidate.get("supporting_claim_ids", [])
        if (normalized := str(claim_id or "").strip())
    }


def _remove_candidates_for_claims(
    candidates: _Phase2CandidateSet,
    claim_ids: set[str],
) -> None:
    if not claim_ids:
        return
    candidates.graph_candidates = [
        candidate
        for candidate in candidates.graph_candidates
        if not claim_ids.intersection(_candidate_claim_ids(candidate))
    ]
    candidates.assertion_candidates = [
        candidate
        for candidate in candidates.assertion_candidates
        if not claim_ids.intersection(_candidate_claim_ids(candidate))
    ]


def _phase1_only_result_payload(
    pipeline: Any,
    batch: _PreparedExtractionBatch,
    phase1_flow: _Phase1ExtractionFlow,
    candidates: list[dict[str, Any]],
    *,
    relation_count: int,
    rejected_graph_candidate_count: int,
) -> dict[str, Any]:
    touched_entity_ids = pipeline._collect_touched_entities(
        candidates + batch.direct_write_candidates,
        [],
    )
    touched_place_ids, touched_topic_keys = pipeline._derive_place_and_topic_hints(
        touched_entity_ids
    )
    return {
        "relation_count": relation_count,
        "assertion_count": 0,
        "touched_entity_ids": touched_entity_ids,
        "touched_place_ids": touched_place_ids,
        "touched_topic_keys": touched_topic_keys,
        "event_entity_map": build_event_entity_map(candidates + batch.direct_write_candidates),
        "snapshot_refresh_entity_ids": [],
        "skipped": False,
        "evidence_class": batch.classification.evidence_class,
        "profile_id": batch.extraction_profile.profile_id,
        "mention_count": len(phase1_flow.phase1_result.entities),
        "direct_write_count": batch.direct_write_count,
        "graph_candidate_count": len(candidates),
        "assertion_candidate_count": 0,
        "claim_assessment_count": 0,
        "rejected_graph_candidate_count": rejected_graph_candidate_count,
        "rejected_assertion_candidate_count": 0,
        "rejected_claim_assessment_count": 0,
        "contradiction_hint_count": 0,
        "conflict_arbitration_decision": None,
        "fast_tracked": True,
        "degraded_stages": _degraded_stages(phase1_flow),
    }


def _phase2_result_payload(
    pipeline: Any,
    batch: _PreparedExtractionBatch,
    phase1_flow: _Phase1ExtractionFlow,
    candidates: _Phase2CandidateSet,
    conflict_arbitration: L2ConflictArbitrationResult | None,
    *,
    relation_count: int,
    assertion_count: int,
) -> dict[str, Any]:
    conflict_decision = conflict_arbitration.decision if conflict_arbitration else None
    return {
        "relation_count": relation_count,
        "assertion_count": assertion_count,
        **_phase2_touch_scope(
            pipeline,
            batch,
            candidates,
            relation_count=relation_count,
            conflict_decision=conflict_decision,
        ),
        "skipped": False,
        "evidence_class": batch.classification.evidence_class,
        "profile_id": batch.extraction_profile.profile_id,
        "mention_count": len(phase1_flow.phase1_result.entities),
        "resolved_context_ref_count": len(phase1_flow.phase1_result.resolved_refs),
        "graph_candidate_count": len(candidates.graph_candidates),
        "direct_write_count": batch.direct_write_count,
        "assertion_candidate_count": len(candidates.assertion_candidates),
        "claim_assessment_count": candidates.claim_assessment_count,
        "rejected_graph_candidate_count": candidates.rejected_graph_candidate_count,
        "rejected_assertion_candidate_count": candidates.rejected_assertion_candidate_count,
        "rejected_claim_assessment_count": candidates.rejected_claim_assessment_count,
        "contradiction_hint_count": len(candidates.contradiction_hints),
        "conflict_arbitration_decision": conflict_decision,
        "fast_tracked": False,
        "degraded_stages": _degraded_stages(phase1_flow),
    }


def _phase2_touch_scope(
    pipeline: Any,
    batch: _PreparedExtractionBatch,
    candidates: _Phase2CandidateSet,
    *,
    relation_count: int,
    conflict_decision: str | None,
) -> dict[str, Any]:
    touched_entity_ids = pipeline._collect_touched_entities(
        candidates.graph_candidates + batch.direct_write_candidates,
        candidates.assertion_candidates,
    )
    if candidates.contradiction_hints and batch.self_entity_id:
        if batch.self_entity_id not in touched_entity_ids:
            touched_entity_ids.append(batch.self_entity_id)
    touched_place_ids, touched_topic_keys = pipeline._derive_place_and_topic_hints(
        touched_entity_ids
    )
    all_candidates = (
        candidates.graph_candidates
        + batch.direct_write_candidates
        + candidates.assertion_candidates
    )
    return {
        "touched_entity_ids": touched_entity_ids,
        "touched_place_ids": touched_place_ids,
        "touched_topic_keys": touched_topic_keys,
        "event_entity_map": build_event_entity_map(all_candidates),
        "snapshot_refresh_entity_ids": (
            touched_entity_ids
            if conflict_decision == "mark_evolution" and relation_count > 0
            else []
        ),
    }


class L2Phase2FlowMixin:
    """Persist grounded facts, then run optional higher-order inference."""

    async def _run_phase2_flow(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
    ) -> dict[str, Any]:
        graph_candidates, graph_rejections = self._project_phase1_graph_candidates(
            phase1_result=phase1_flow.phase1_result,
            event=batch.stored_event,
            evidence_event_ids=batch.batch_event_ids,
            resolved_mentions=phase1_flow.resolved_mentions,
            catalog_name_index=batch.catalog_name_index,
            profile=batch.extraction_profile,
            classification=batch.classification,
        )
        phase1_flow.claim_outcomes.extend(graph_rejections)
        rejected_graph_count = len(graph_rejections)
        focal_entities = self._build_focal_entities(
            batch.stored_event,
            phase1_flow.resolved_mentions,
        )
        await self._emit_active_entities(
            event=batch.stored_event,
            focal_entities=focal_entities,
        )
        if not self._phase2_inference_required(
            phase1_result=phase1_flow.phase1_result,
            profile=batch.extraction_profile,
            policy=batch.policy,
        ):
            return await self._persist_phase1_only(
                batch=batch,
                phase1_flow=phase1_flow,
                graph_candidates=graph_candidates,
                rejected_graph_count=rejected_graph_count,
            )

        phase2_context = await self._prepare_phase2_context(
            batch,
            focal_entities=focal_entities,
        )
        try:
            phase2_result = await self._run_phase2_integration(
                batch,
                phase1_flow,
                phase2_context,
            )
        except L2LLMJsonError as exc:
            return await self._persist_degraded_phase1(
                batch=batch,
                phase1_flow=phase1_flow,
                graph_candidates=graph_candidates,
                rejected_graph_count=rejected_graph_count,
                stage="phase2",
                exc=exc,
            )
        phase2_candidates = await self._validate_phase2_outputs(
            batch=batch,
            phase1_flow=phase1_flow,
            phase2_context=phase2_context,
            phase2_result=phase2_result,
            graph_candidates=graph_candidates,
            rejected_graph_count=rejected_graph_count,
        )
        try:
            conflict_arbitration = await self._apply_phase2_conflict_arbitration(
                batch,
                phase1_flow,
                phase2_candidates,
            )
        except L2LLMJsonError as exc:
            logger.warning(
                "L2 conflict arbitration degraded without dropping unrelated Phase 2 candidates",
                event_id=batch.stored_event.event_id,
                profile_id=batch.extraction_profile.profile_id,
                degraded_stage="conflict_arbitration",
                error_type=type(exc).__name__,
            )
            _record_degraded_stage(phase1_flow, "conflict_arbitration")
            self._apply_phase2_arbitration_decision(
                batch,
                phase1_flow,
                phase2_candidates,
                None,
            )
            conflict_arbitration = None
        return await self._persist_phase2_result(
            batch=batch,
            phase1_flow=phase1_flow,
            phase2_candidates=phase2_candidates,
            conflict_arbitration=conflict_arbitration,
        )

    async def _prepare_phase2_context(
        self: Any,
        batch: _PreparedExtractionBatch,
        *,
        focal_entities: list[L2FocalEntityRef],
    ) -> _Phase2Context:
        merged_history_contexts = await self._augment_event_window_with_entity_history(
            anchor_event=batch.stored_event,
            event_window=batch.event_window,
            focal_entities=focal_entities,
            exclude_event_ids=batch.batch_event_ids,
        )
        batch.history_contexts = [
            item.to_dict() if hasattr(item, "to_dict") else dict(item)
            for item in merged_history_contexts
        ]
        await self._emit_active_entities(event=batch.stored_event, focal_entities=focal_entities)
        existing_graph_edges: list[dict[str, Any]] = []
        existing_assertions: list[dict[str, Any]] = []
        graph_conflict_rules: list[dict[str, Any]] = []
        if self._cognition_store is not None:
            existing_graph_edges, existing_assertions = await self._load_existing_graph_context(
                focal_entities
            )
            graph_conflict_rules = await self._cognition_store.list_graph_conflict_rules()
        return _Phase2Context(
            focal_entities=focal_entities,
            existing_graph_edges=existing_graph_edges,
            existing_assertions=existing_assertions,
            graph_conflict_rules=graph_conflict_rules,
        )

    async def _persist_phase1_only(
        self: Any,
        *,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
        graph_candidates: list[dict[str, Any]],
        rejected_graph_count: int,
    ) -> dict[str, Any]:
        await self._assert_current_projection_attempt(batch)
        relation_count = await self._upsert_knowledge_edges_with_outcomes(
            graph_candidates,
            attempt_key=batch.attempt_key,
            route_contract_version=ROUTE_CONTRACT_VERSION,
            projection_leases=batch.projection_leases,
        )
        _ensure_assertion_outcomes(
            phase1_flow,
            reason_code=(
                "phase2_degraded" if _degraded_stages(phase1_flow) else "phase2_not_required"
            ),
        )
        facet_count = await self._upsert_structured_facets(batch)
        await self._persist_claim_projection_outcomes(batch, phase1_flow.claim_outcomes)
        logger.info(
            "L2 Phase 1 persisted without Phase 2 inference",
            event_id=batch.stored_event.event_id,
            profile_id=batch.extraction_profile.profile_id,
            relation_count=relation_count,
            rejected_graph_candidate_count=rejected_graph_count,
            direct_write_count=batch.direct_write_count,
            facet_count=facet_count,
        )
        return _phase1_only_result_payload(
            self,
            batch,
            phase1_flow,
            graph_candidates,
            relation_count=relation_count,
            rejected_graph_candidate_count=rejected_graph_count,
        )

    async def _persist_degraded_phase1(
        self: Any,
        *,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
        graph_candidates: list[dict[str, Any]],
        rejected_graph_count: int,
        stage: str,
        exc: L2LLMJsonError,
    ) -> dict[str, Any]:
        logger.warning(
            "L2 optional inference degraded to Phase 1",
            event_id=batch.stored_event.event_id,
            profile_id=batch.extraction_profile.profile_id,
            degraded_stage=stage,
            error_type=type(exc).__name__,
        )
        _record_degraded_stage(phase1_flow, stage)
        result = await self._persist_phase1_only(
            batch=batch,
            phase1_flow=phase1_flow,
            graph_candidates=graph_candidates,
            rejected_graph_count=rejected_graph_count,
        )
        result["fast_tracked"] = False
        return result

    async def _run_phase2_integration(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
        phase2_context: _Phase2Context,
    ) -> Any:
        logger.info(
            "L2 Phase 2 inference started",
            event_id=batch.stored_event.event_id,
            existing_edge_count=len(phase2_context.existing_graph_edges),
            existing_assertion_count=len(phase2_context.existing_assertions),
        )
        return await self._llm_service.integrate_phase2(
            phase1_result=phase1_flow.phase1_result,
            existing_graph_edges=phase2_context.existing_graph_edges,
            existing_assertions=phase2_context.existing_assertions,
            event_window=batch.event_window,
            focal_subject=batch.focal_subject,
            phase2_instructions=batch.extraction_profile.phase2_instructions,
        )

    async def _validate_phase2_outputs(
        self: Any,
        *,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
        phase2_context: _Phase2Context,
        phase2_result: Any,
        graph_candidates: list[dict[str, Any]],
        rejected_graph_count: int,
    ) -> _Phase2CandidateSet:
        occurrence_stats_by_key = await self._load_phase2_occurrence_stats(phase1_flow)
        assertion_candidates, rejected_assertion_count = self._validate_phase2_assertion_output(
            batch,
            phase1_flow,
            phase2_result,
            graph_candidates,
            occurrence_stats_by_key,
        )
        validated_assessments, rejected_assessment_count = self._validate_phase2_claim_assessments(
            phase1_result=phase1_flow.phase1_result,
            semantic_routes=phase1_flow.semantic_routes,
            graph_candidates=graph_candidates,
            assertion_candidates=assertion_candidates,
            assessments=phase2_result.claim_assessments,
            existing_graph_edges=phase2_context.existing_graph_edges,
            existing_assertions=phase2_context.existing_assertions,
            graph_conflict_rules=phase2_context.graph_conflict_rules,
            arbitration_min_confidence=self._conflict_arbitration_min_confidence,
        )
        contradiction_hints = [
            assessment.hint for assessment in validated_assessments if assessment.hint is not None
        ]
        _record_terminal_validation_outcomes(phase1_flow, validated_assessments)
        candidates = _Phase2CandidateSet(
            graph_candidates=graph_candidates,
            facet_candidates=self._build_structured_facet_candidates(
                event=batch.stored_event,
                evidence_event_ids=batch.batch_event_ids,
            ),
            assertion_candidates=assertion_candidates,
            contradiction_hints=contradiction_hints,
            validated_claim_assessments=validated_assessments,
            rejected_graph_candidate_count=rejected_graph_count,
            rejected_assertion_candidate_count=rejected_assertion_count,
            claim_assessment_count=len(phase2_result.claim_assessments),
            rejected_claim_assessment_count=rejected_assessment_count,
        )
        self._log_phase2_candidate_validation(batch, candidates)
        return candidates

    def _validate_phase2_assertion_output(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
        phase2_result: Any,
        graph_candidates: list[dict[str, Any]],
        occurrence_stats_by_key: dict[ClaimRouteValueKey, ClaimOccurrenceStats],
    ) -> tuple[list[dict[str, Any]], int]:
        assertion_context = self._merge_graph_candidates(
            graph_candidates,
            batch.direct_write_candidates,
        )
        return self._validate_phase2_assertions(
            event=batch.stored_event,
            profile=batch.extraction_profile,
            policy=batch.policy,
            graph_candidates=assertion_context,
            default_event_ids=batch.batch_event_ids,
            semantic_routes=phase1_flow.semantic_routes,
            occurrence_stats_by_key=occurrence_stats_by_key,
            phase1_result=phase1_flow.phase1_result,
            phase2_assertions=phase2_result.assertion_candidates,
            claim_outcomes=phase1_flow.claim_outcomes,
        )

    async def _load_phase2_occurrence_stats(
        self: Any,
        phase1_flow: _Phase1ExtractionFlow,
    ) -> dict[ClaimRouteValueKey, ClaimOccurrenceStats]:
        """Load one recomputable ledger snapshot for all routed Claim values."""

        keys = {
            ClaimRouteValueKey(str(route.slot_key), str(route.value_fingerprint))
            for route in phase1_flow.semantic_routes.values()
            if route.can_project_assertion and route.value_fingerprint
        }
        if not keys:
            return {}
        if self._cognition_store is None:
            raise RuntimeError("L2 cognition store is unavailable for promotion statistics")
        stats = await load_routed_claim_occurrence_stats(
            self._cognition_store.db_path,
            keys=keys,
            local_timezone=datetime.now().astimezone().tzinfo,
        )
        missing = keys.difference(stats)
        if missing:
            missing_slots = sorted(key.target_slot_key for key in missing)
            raise RuntimeError(
                "routed Claims are missing durable occurrence statistics: "
                + ", ".join(missing_slots)
            )
        return stats

    def _log_phase2_candidate_validation(
        self: Any,
        batch: _PreparedExtractionBatch,
        candidates: _Phase2CandidateSet,
    ) -> None:
        logger.info(
            "L2 Phase 2 inference validation completed",
            event_id=batch.stored_event.event_id,
            profile_id=batch.extraction_profile.profile_id,
            graph_candidate_count=len(candidates.graph_candidates),
            assertion_candidate_count=len(candidates.assertion_candidates),
            claim_assessment_count=candidates.claim_assessment_count,
            rejected_graph_candidate_count=candidates.rejected_graph_candidate_count,
            rejected_assertion_candidate_count=candidates.rejected_assertion_candidate_count,
            rejected_claim_assessment_count=candidates.rejected_claim_assessment_count,
            contradiction_hint_count=len(candidates.contradiction_hints),
        )

    async def _apply_phase2_conflict_arbitration(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
        candidates: _Phase2CandidateSet,
    ) -> L2ConflictArbitrationResult | None:
        pending_assessments = self._pending_claim_assessments(
            candidates.validated_claim_assessments
        )
        if not pending_assessments:
            self._apply_phase2_arbitration_decision(
                batch,
                phase1_flow,
                candidates,
                None,
            )
            return None
        pending_claim_ids = self._candidate_claim_ids_for_assessments(pending_assessments)
        graph_candidates = self._graph_candidates_for_claims(
            candidates.graph_candidates,
            pending_claim_ids,
        )
        assertion_candidates = self._assertion_candidates_for_claims(
            candidates.assertion_candidates,
            pending_claim_ids,
        )
        pending_hints = [
            assessment.hint for assessment in pending_assessments if assessment.hint is not None
        ]
        if not pending_hints or not (graph_candidates or assertion_candidates):
            self._apply_phase2_arbitration_decision(
                batch,
                phase1_flow,
                candidates,
                None,
            )
            return None
        conflict_arbitration = await self._arbitrate_conflicting_candidates(
            anchor_event=batch.stored_event,
            batch_events=[item[0] for item in batch.eligible_events],
            graph_candidates=graph_candidates,
            assertion_candidates=assertion_candidates,
            contradiction_hints=pending_hints,
        )
        self._apply_phase2_arbitration_decision(
            batch,
            phase1_flow,
            candidates,
            conflict_arbitration,
        )
        return conflict_arbitration

    def _apply_phase2_arbitration_decision(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
        candidates: _Phase2CandidateSet,
        conflict_arbitration: L2ConflictArbitrationResult | None,
    ) -> None:
        assessments = candidates.validated_claim_assessments
        pending_assessments = self._pending_claim_assessments(assessments)
        validation_blocked = [
            assessment
            for assessment in assessments
            if assessment.action_eligibility is AssessmentActionEligibility.QUARANTINED
            or (
                assessment.action_eligibility is AssessmentActionEligibility.NOOP
                and assessment.reason_code == "assessment_duplicate_evidence_noop"
            )
        ]
        validation_blocked_claim_ids = {assessment.claim_id for assessment in validation_blocked}
        reason_by_removed_claim = {
            assessment.claim_id: "assessment_candidate_quarantined"
            for assessment in validation_blocked
        }
        selected_assessments = (
            self._selected_claim_assessments(pending_assessments, conflict_arbitration)
            if conflict_arbitration is not None
            else []
        )
        selected_keys = {
            (
                assessment.claim_id,
                assessment.target_record_type,
                assessment.related_record_id,
                assessment.relationship,
            )
            for assessment in selected_assessments
        }
        arbitration_decision = conflict_arbitration.decision if conflict_arbitration else None
        if arbitration_decision in {"keep_new", "mark_evolution"}:
            pending_by_claim: dict[str, list[ValidatedClaimAssessment]] = {}
            for assessment in pending_assessments:
                pending_by_claim.setdefault(assessment.claim_id, []).append(assessment)
            for claim_id, claim_assessments in pending_by_claim.items():
                if claim_id in validation_blocked_claim_ids:
                    continue
                if any(
                    (
                        assessment.claim_id,
                        assessment.target_record_type,
                        assessment.related_record_id,
                        assessment.relationship,
                    )
                    not in selected_keys
                    for assessment in claim_assessments
                ):
                    reason_by_removed_claim[claim_id] = "conflict_arbitration_unselected"
        else:
            pending_claim_ids = {assessment.claim_id for assessment in pending_assessments}
            selected_claim_ids = {assessment.claim_id for assessment in selected_assessments}
            for claim_id in pending_claim_ids - validation_blocked_claim_ids:
                reason_by_removed_claim[claim_id] = (
                    "conflict_keep_existing"
                    if arbitration_decision == "keep_existing" and claim_id in selected_claim_ids
                    else (
                        "conflict_arbitration_unavailable"
                        if arbitration_decision is None
                        else "conflict_arbitration_unselected"
                    )
                )

        for reason_code in sorted(set(reason_by_removed_claim.values())):
            scoped_claim_ids = {
                claim_id
                for claim_id, reason in reason_by_removed_claim.items()
                if reason == reason_code
            }
            _record_scoped_candidate_outcomes(
                phase1_flow,
                candidates,
                claim_ids=scoped_claim_ids,
                reason_code=reason_code,
            )
        removed_claim_ids = set(reason_by_removed_claim)
        _remove_candidates_for_claims(candidates, removed_claim_ids)
        actionable_selected_assessments = [
            assessment
            for assessment in selected_assessments
            if assessment.claim_id not in removed_claim_ids
        ]

        safe_assessments = [
            assessment
            for assessment in assessments
            if assessment.action_eligibility is AssessmentActionEligibility.REVALIDATE
            and assessment.claim_id not in removed_claim_ids
        ]
        safe_hints = self._safe_revalidation_hints(safe_assessments)
        candidates.contradiction_hints = safe_hints

        for assessment in pending_assessments:
            key = (
                assessment.claim_id,
                assessment.target_record_type,
                assessment.related_record_id,
                assessment.relationship,
            )
            if assessment.claim_id in validation_blocked_claim_ids:
                _append_assessment_outcome(
                    phase1_flow,
                    assessment,
                    outcome="quarantined",
                    reason_code="assessment_candidate_quarantined",
                )
                continue
            if (
                arbitration_decision in {"keep_new", "mark_evolution"}
                and assessment.claim_id in removed_claim_ids
            ):
                _append_assessment_outcome(
                    phase1_flow,
                    assessment,
                    outcome="quarantined",
                    reason_code=reason_by_removed_claim[assessment.claim_id],
                )
                continue
            if key not in selected_keys:
                _append_assessment_outcome(
                    phase1_flow,
                    assessment,
                    outcome="quarantined",
                    reason_code=(
                        "conflict_arbitration_unavailable"
                        if arbitration_decision is None
                        else "conflict_arbitration_unselected"
                    ),
                )
                continue
            if arbitration_decision == "keep_existing":
                _append_assessment_outcome(
                    phase1_flow,
                    assessment,
                    outcome="noop",
                    reason_code="conflict_keep_existing",
                )
            elif arbitration_decision in {"keep_new", "mark_evolution"}:
                _append_assessment_outcome(
                    phase1_flow,
                    assessment,
                    outcome="accepted",
                    reason_code=f"conflict_{arbitration_decision}",
                )

        if arbitration_decision == "keep_existing":
            logger.info(
                "L2 conflict arbitration kept existing records",
                event_id=batch.stored_event.event_id,
                decision="keep_existing",
                selected_assessment_count=len(selected_assessments),
                removed_claim_count=len(removed_claim_ids),
            )
        elif arbitration_decision == "mark_evolution":
            candidates.contradiction_hints = self._rewrite_hints_for_evolution(
                safe_hints=safe_hints,
                selected_assessments=actionable_selected_assessments,
            )

    async def _persist_phase2_result(
        self: Any,
        *,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
        phase2_candidates: _Phase2CandidateSet,
        conflict_arbitration: L2ConflictArbitrationResult | None,
    ) -> dict[str, Any]:
        await self._assert_current_projection_attempt(batch)
        relation_count, facet_count, assertion_count = await self._persist_extraction_outputs(
            graph_candidates=phase2_candidates.graph_candidates,
            direct_write_candidates=batch.direct_write_candidates,
            facet_candidates=phase2_candidates.facet_candidates,
            assertion_candidates=phase2_candidates.assertion_candidates,
            contradiction_hints=phase2_candidates.contradiction_hints,
            attempt_key=batch.attempt_key,
            route_contract_version=ROUTE_CONTRACT_VERSION,
            projection_leases=batch.projection_leases,
        )
        atomic_assertion_claim_ids = {
            normalized_claim_id
            for candidate in phase2_candidates.assertion_candidates
            for claim_id in candidate.get("supporting_claim_ids", [])
            if (normalized_claim_id := str(claim_id or "").strip())
        }
        _ensure_assertion_outcomes(
            phase1_flow,
            reason_code="phase2_no_assertion_candidate",
            atomically_completed_claim_ids=atomic_assertion_claim_ids,
        )
        await self._persist_claim_projection_outcomes(batch, phase1_flow.claim_outcomes)
        self._log_phase2_persistence(
            batch,
            phase2_candidates,
            conflict_arbitration,
            relation_count,
            facet_count,
            assertion_count,
        )
        return _phase2_result_payload(
            self,
            batch,
            phase1_flow,
            phase2_candidates,
            conflict_arbitration,
            relation_count=relation_count,
            assertion_count=assertion_count,
        )

    def _log_phase2_persistence(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase2_candidates: _Phase2CandidateSet,
        conflict_arbitration: L2ConflictArbitrationResult | None,
        relation_count: int,
        facet_count: int,
        assertion_count: int,
    ) -> None:
        logger.info(
            "L2 inference persistence completed",
            event_id=batch.stored_event.event_id,
            profile_id=batch.extraction_profile.profile_id,
            relation_count=relation_count,
            facet_count=facet_count,
            assertion_count=assertion_count,
            contradiction_hint_count=len(phase2_candidates.contradiction_hints),
            conflict_arbitration_decision=(
                conflict_arbitration.decision if conflict_arbitration is not None else None
            ),
        )


__all__ = ["L2Phase2FlowMixin"]
