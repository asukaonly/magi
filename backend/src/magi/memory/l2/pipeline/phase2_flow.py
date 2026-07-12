"""L2 Phase 2 integration, validation, and persistence flow."""

from __future__ import annotations

from typing import Any

from ....core.logger import get_logger
from ..models import L2ConflictArbitrationResult
from .external_dialogue_grounding import ground_phase2_external_dialogue_refs
from .extraction_contracts import (
    _Phase1ExtractionFlow,
    _Phase2CandidateSet,
    _Phase2Context,
    _PreparedExtractionBatch,
)
from .event_entity_map import build_event_entity_map

logger = get_logger("magi.memory.l2.pipeline")


def _fast_track_result_payload(
    pipeline: Any,
    batch: _PreparedExtractionBatch,
    phase1_flow: _Phase1ExtractionFlow,
    candidates: list[dict[str, Any]],
    relation_count: int,
) -> dict[str, Any]:
    touched_entity_ids = pipeline._collect_touched_entities(candidates, [])
    touched_place_ids, touched_topic_keys = pipeline._derive_place_and_topic_hints(
        touched_entity_ids
    )
    return {
        "relation_count": relation_count,
        "assertion_count": 0,
        "touched_entity_ids": touched_entity_ids,
        "touched_place_ids": touched_place_ids,
        "touched_topic_keys": touched_topic_keys,
        "event_entity_map": build_event_entity_map(candidates),
        "snapshot_refresh_entity_ids": [],
        "skipped": False,
        "evidence_class": batch.classification.evidence_class,
        "profile_id": batch.extraction_profile.profile_id,
        "mention_count": len(phase1_flow.phase1_result.entities),
        "direct_write_count": batch.direct_write_count,
        "corroborate_count": 0,
        "graph_candidate_count": len(candidates),
        "assertion_candidate_count": 0,
        "rejected_graph_candidate_count": 0,
        "rejected_assertion_candidate_count": 0,
        "contradiction_hint_count": 0,
        "conflict_arbitration_decision": None,
        "fast_tracked": True,
    }


def _phase2_result_payload(
    pipeline: Any,
    batch: _PreparedExtractionBatch,
    phase1_flow: _Phase1ExtractionFlow,
    candidates: _Phase2CandidateSet,
    conflict_arbitration: L2ConflictArbitrationResult | None,
    *,
    relation_count: int,
    corroborate_count: int,
    assertion_count: int,
) -> dict[str, Any]:
    conflict_decision = conflict_arbitration.decision if conflict_arbitration else None
    touch_scope = _phase2_touch_scope(
        pipeline,
        batch,
        candidates,
        relation_count=relation_count,
        conflict_decision=conflict_decision,
    )
    return {
        "relation_count": relation_count,
        "assertion_count": assertion_count,
        **touch_scope,
        "skipped": False,
        "evidence_class": batch.classification.evidence_class,
        "profile_id": batch.extraction_profile.profile_id,
        "mention_count": len(phase1_flow.phase1_result.entities),
        "resolved_context_ref_count": len(phase1_flow.phase1_result.resolved_refs),
        "graph_candidate_count": len(candidates.graph_candidates),
        "direct_write_count": batch.direct_write_count,
        "corroborate_count": corroborate_count,
        "assertion_candidate_count": len(candidates.assertion_candidates),
        "rejected_graph_candidate_count": candidates.rejected_graph_candidate_count,
        "rejected_assertion_candidate_count": candidates.rejected_assertion_candidate_count,
        "contradiction_hint_count": len(candidates.contradiction_hints),
        "conflict_arbitration_decision": conflict_decision,
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
    snapshot_refresh_entity_ids = (
        touched_entity_ids
        if conflict_decision == "mark_evolution" and relation_count > 0
        else []
    )
    return {
        "touched_entity_ids": touched_entity_ids,
        "touched_place_ids": touched_place_ids,
        "touched_topic_keys": touched_topic_keys,
        "event_entity_map": build_event_entity_map(all_candidates),
        "snapshot_refresh_entity_ids": snapshot_refresh_entity_ids,
    }


class L2Phase2FlowMixin:
    """Run L2 Phase 2 integration, validation, conflict handling, and writes."""

    async def _run_phase2_flow(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
    ) -> dict[str, Any]:
        phase2_context = await self._prepare_phase2_context(batch, phase1_flow)
        fast_track_result = await self._maybe_fast_track_phase1(
            batch,
            phase1_flow,
            phase2_context,
        )
        if fast_track_result is not None:
            return fast_track_result
        phase2_result = await self._run_phase2_integration(
            batch,
            phase1_flow,
            phase2_context,
        )
        phase2_candidates = await self._validate_phase2_outputs(
            batch,
            phase1_flow,
            phase2_result,
        )
        conflict_arbitration = await self._apply_phase2_conflict_arbitration(
            batch,
            phase2_candidates,
        )
        return await self._persist_phase2_result(
            batch=batch,
            phase1_flow=phase1_flow,
            phase2_candidates=phase2_candidates,
            conflict_arbitration=conflict_arbitration,
        )

    async def _prepare_phase2_context(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
    ) -> _Phase2Context:
        focal_entities = self._build_focal_entities(
            batch.stored_event,
            phase1_flow.resolved_mentions,
        )
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
        if self._cognition_store is not None:
            existing_graph_edges, existing_assertions = await self._load_existing_graph_context(
                focal_entities
            )
        return _Phase2Context(
            focal_entities=focal_entities,
            existing_graph_edges=existing_graph_edges,
            existing_assertions=existing_assertions,
        )

    async def _maybe_fast_track_phase1(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
        phase2_context: _Phase2Context,
    ) -> dict[str, Any] | None:
        if not self._can_fast_track(
            phase1_result=phase1_flow.phase1_result,
            resolved_mentions=phase1_flow.resolved_mentions,
            existing_graph_edges=phase2_context.existing_graph_edges,
            profile=batch.extraction_profile,
            policy=batch.policy,
            catalog_name_index=batch.catalog_name_index,
        ):
            return None
        candidates = self._fast_track_claims_to_candidates(
            phase1_result=phase1_flow.phase1_result,
            event=batch.stored_event,
            evidence_event_ids=batch.batch_event_ids,
            resolved_mentions=phase1_flow.resolved_mentions,
            catalog_name_index=batch.catalog_name_index,
            profile=batch.extraction_profile,
            classification=batch.classification,
        )
        relation_count = await self._upsert_knowledge_edges(candidates)
        facet_count = await self._upsert_structured_facets(batch)
        logger.info(
            "L2 fast-track: skipped Phase 2",
            event_id=batch.stored_event.event_id,
            profile_id=batch.extraction_profile.profile_id,
            relation_count=relation_count,
            direct_write_count=batch.direct_write_count,
            facet_count=facet_count,
        )
        return _fast_track_result_payload(
            self,
            batch,
            phase1_flow,
            candidates,
            relation_count,
        )

    async def _run_phase2_integration(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
        phase2_context: _Phase2Context,
    ) -> Any:
        logger.info(
            "L2 Phase 2 integration started",
            event_id=batch.stored_event.event_id,
            existing_edge_count=len(phase2_context.existing_graph_edges),
            existing_assertion_count=len(phase2_context.existing_assertions),
        )
        phase2_result = await self._llm_service.integrate_phase2(
            phase1_result=phase1_flow.phase1_result,
            existing_graph_edges=phase2_context.existing_graph_edges,
            existing_assertions=phase2_context.existing_assertions,
            event_window=batch.event_window,
            focal_subject=batch.focal_subject,
            phase2_instructions=batch.extraction_profile.phase2_instructions,
        )
        self._ground_phase2_result(batch, phase2_result)
        return phase2_result

    def _ground_phase2_result(self: Any, batch: _PreparedExtractionBatch, phase2_result: Any) -> None:
        external_dialogue_stats = ground_phase2_external_dialogue_refs(
            phase2_result,
            batch.event_window,
        )
        if any(external_dialogue_stats.values()):
            logger.info(
                "L2 external dialogue speaker grounding applied",
                event_id=batch.stored_event.event_id,
                **external_dialogue_stats,
            )

    async def _validate_phase2_outputs(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
        phase2_result: Any,
    ) -> _Phase2CandidateSet:
        graph_candidates, corroborate_targets, rejected_graph_count = (
            await self._validate_phase2_graph_output(batch, phase1_flow, phase2_result)
        )
        assertion_candidates, rejected_assertion_count = (
            self._validate_phase2_assertion_output(
                batch,
                phase1_flow,
                phase2_result,
                graph_candidates,
            )
        )
        candidates = _Phase2CandidateSet(
            graph_candidates=graph_candidates,
            corroborate_targets=corroborate_targets,
            facet_candidates=self._build_structured_facet_candidates(
                event=batch.stored_event,
                evidence_event_ids=batch.batch_event_ids,
            ),
            assertion_candidates=assertion_candidates,
            contradiction_hints=self._convert_phase2_contradiction_hints(
                phase2_result.contradiction_hints
            ),
            rejected_graph_candidate_count=rejected_graph_count,
            rejected_assertion_candidate_count=rejected_assertion_count,
        )
        self._log_phase2_candidate_validation(batch, candidates)
        return candidates

    async def _validate_phase2_graph_output(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
        phase2_result: Any,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        catalog_name_index = await self._build_catalog_name_index()
        return self._validate_phase2_graph_edges(
            event=batch.stored_event,
            profile=batch.extraction_profile,
            policy=batch.policy,
            resolved_mentions=phase1_flow.resolved_mentions,
            evidence_event_ids=batch.batch_event_ids,
            phase2_edges=phase2_result.graph_edges,
            profile_signal_object_refs=phase1_flow.profile_signal_object_refs,
            catalog_name_index=catalog_name_index,
            classification=batch.classification,
        )

    def _validate_phase2_assertion_output(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
        phase2_result: Any,
        graph_candidates: list[dict[str, Any]],
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
            phase1_result=phase1_flow.phase1_result,
            phase2_assertions=phase2_result.assertion_candidates,
        )

    def _log_phase2_candidate_validation(
        self: Any,
        batch: _PreparedExtractionBatch,
        candidates: _Phase2CandidateSet,
    ) -> None:
        logger.info(
            "L2 Phase 2 candidate validation completed",
            event_id=batch.stored_event.event_id,
            profile_id=batch.extraction_profile.profile_id,
            graph_candidate_count=len(candidates.graph_candidates),
            assertion_candidate_count=len(candidates.assertion_candidates),
            rejected_graph_candidate_count=candidates.rejected_graph_candidate_count,
            rejected_assertion_candidate_count=candidates.rejected_assertion_candidate_count,
            contradiction_hint_count=len(candidates.contradiction_hints),
        )

    async def _apply_phase2_conflict_arbitration(
        self: Any,
        batch: _PreparedExtractionBatch,
        candidates: _Phase2CandidateSet,
    ) -> L2ConflictArbitrationResult | None:
        if not candidates.contradiction_hints:
            return None
        if not (candidates.graph_candidates or candidates.assertion_candidates):
            return None
        conflict_arbitration = await self._arbitrate_conflicting_candidates(
            anchor_event=batch.stored_event,
            batch_events=[item[0] for item in batch.eligible_events],
            graph_candidates=candidates.graph_candidates,
            assertion_candidates=candidates.assertion_candidates,
            contradiction_hints=candidates.contradiction_hints,
        )
        self._apply_phase2_arbitration_decision(batch, candidates, conflict_arbitration)
        return conflict_arbitration

    def _apply_phase2_arbitration_decision(
        self: Any,
        batch: _PreparedExtractionBatch,
        candidates: _Phase2CandidateSet,
        conflict_arbitration: L2ConflictArbitrationResult | None,
    ) -> None:
        arbitration_decision = (
            conflict_arbitration.decision if conflict_arbitration is not None else None
        )
        if arbitration_decision == "keep_existing":
            logger.info(
                "L2 conflict arbitration kept existing records",
                event_id=batch.stored_event.event_id,
                decision="keep_existing",
                severe_hint_count=len(
                    self._severe_contradiction_hints(candidates.contradiction_hints)
                ),
            )
            candidates.graph_candidates = []
            candidates.assertion_candidates = []
            candidates.contradiction_hints = self._rewrite_hints_for_keep_existing(
                contradiction_hints=candidates.contradiction_hints,
                conflict_arbitration=conflict_arbitration,
            )
        elif arbitration_decision == "mark_evolution":
            candidates.contradiction_hints = self._rewrite_hints_for_evolution(
                contradiction_hints=candidates.contradiction_hints,
                conflict_arbitration=conflict_arbitration,
            )

    async def _persist_phase2_result(
        self: Any,
        *,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
        phase2_candidates: _Phase2CandidateSet,
        conflict_arbitration: L2ConflictArbitrationResult | None,
    ) -> dict[str, Any]:
        relation_count, corroborate_count, facet_count, assertion_count = (
            await self._persist_phase2_outputs(
                graph_candidates=phase2_candidates.graph_candidates,
                direct_write_candidates=batch.direct_write_candidates,
                corroborate_targets=phase2_candidates.corroborate_targets,
                facet_candidates=phase2_candidates.facet_candidates,
                assertion_candidates=phase2_candidates.assertion_candidates,
                contradiction_hints=phase2_candidates.contradiction_hints,
            )
        )
        self._log_phase2_persistence(
            batch,
            phase2_candidates,
            conflict_arbitration,
            relation_count,
            corroborate_count,
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
            corroborate_count=corroborate_count,
            assertion_count=assertion_count,
        )

    def _log_phase2_persistence(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase2_candidates: _Phase2CandidateSet,
        conflict_arbitration: L2ConflictArbitrationResult | None,
        relation_count: int,
        corroborate_count: int,
        facet_count: int,
        assertion_count: int,
    ) -> None:
        logger.info(
            "L2 persistence completed",
            event_id=batch.stored_event.event_id,
            profile_id=batch.extraction_profile.profile_id,
            relation_count=relation_count,
            corroborate_count=corroborate_count,
            facet_count=facet_count,
            assertion_count=assertion_count,
            contradiction_hint_count=len(phase2_candidates.contradiction_hints),
            conflict_arbitration_decision=(
                conflict_arbitration.decision if conflict_arbitration is not None else None
            ),
        )


__all__ = ["L2Phase2FlowMixin"]
