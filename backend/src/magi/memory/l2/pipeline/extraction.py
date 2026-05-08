"""L2 extraction orchestration flow."""

from __future__ import annotations

from typing import Any

from ....core.logger import get_logger
from ...event_contracts import MemoryEvent
from ..evidence_classifier import classify_event_evidence
from ..evidence_policy import resolve_l2_policy
from ..extraction_profiles import resolve_extraction_profile
from ..storage.utils import normalize_event_ids
from ..models import (
    L2BatchJob,
    L2ConflictArbitrationResult,
    L2EventWindow,
    L2EventWindowSummary,
    ResolvedEntityMention,
)

logger = get_logger("magi.memory.l2.pipeline")


class L2PipelineExtractionMixin:
    """Run the end-to-end L2 Phase 1/Phase 2 extraction and persistence flow."""

    async def _extract_and_persist(self: Any, job: L2BatchJob) -> dict[str, Any]:
        if self._cognition_store is None:
            return {
                "relation_count": 0,
                "assertion_count": 0,
                "touched_entity_ids": [],
                "skipped": True,
            }

        stored_events = await self._load_batch_events(job)
        if not stored_events:
            return {
                "relation_count": 0,
                "assertion_count": 0,
                "touched_entity_ids": [],
                "skipped": True,
                "skip_reason": "empty_batch",
                "evidence_class": None,
                "contradiction_hint_count": 0,
            }

        eligible_events: list[tuple[MemoryEvent, Any, Any]] = []
        for stored_event in stored_events:
            classification = classify_event_evidence(stored_event)
            self._increment_bucket(
                self._stats.extract_by_evidence_class, classification.evidence_class
            )
            logger.debug(
                "L2 evidence classified",
                event_id=stored_event.event_id,
                evidence_class=classification.evidence_class,
                grounding_type=classification.grounding_type,
                semantic_owner=classification.semantic_owner,
                originality_type=classification.originality_type,
                source_event_ids=classification.source_event_ids,
            )
            policy = resolve_l2_policy(classification)
            logger.debug(
                "L2 policy resolved",
                event_id=stored_event.event_id,
                evidence_class=classification.evidence_class,
                allow_entity_extraction=policy.allow_entity_extraction,
                allow_graph_write=policy.allow_graph_write,
                allow_assertion_write=policy.allow_assertion_write,
                allow_snapshot_impact=policy.allow_snapshot_impact,
                graph_scope=policy.graph_scope,
                assertion_scope=policy.assertion_scope,
                skip_reason=policy.skip_reason,
            )
            if policy.allow_graph_write or policy.allow_assertion_write:
                eligible_events.append((stored_event, classification, policy))

        if not eligible_events:
            classification = classify_event_evidence(stored_events[-1])
            policy = resolve_l2_policy(classification)
            if policy.skip_reason:
                self._increment_bucket(self._stats.skip_by_reason, policy.skip_reason)
            return {
                "relation_count": 0,
                "assertion_count": 0,
                "touched_entity_ids": [],
                "skipped": True,
                "skip_reason": policy.skip_reason or "no_eligible_events",
                "evidence_class": classification.evidence_class,
                "contradiction_hint_count": 0,
            }

        stored_event, classification, policy = eligible_events[-1]
        batch_event_ids = normalize_event_ids(
            [item.event_id for item, _, _ in eligible_events]
        )
        if not policy.allow_graph_write and not policy.allow_assertion_write:
            if policy.skip_reason:
                self._increment_bucket(self._stats.skip_by_reason, policy.skip_reason)
            return {
                "relation_count": 0,
                "assertion_count": 0,
                "touched_entity_ids": [],
                "skipped": True,
                "skip_reason": policy.skip_reason,
                "evidence_class": classification.evidence_class,
                "contradiction_hint_count": 0,
            }

        context_messages = (
            await self._load_context_messages(stored_event, exclude_event_ids=batch_event_ids)
            if policy.allow_entity_extraction
            or policy.allow_assertion_write
            or policy.allow_graph_write
            else []
        )
        history_contexts = (
            await self._load_history_contexts(
                anchor_event=stored_event,
                batch_events=[item[0] for item in eligible_events],
                exclude_event_ids=batch_event_ids,
            )
            if policy.allow_entity_extraction
            or policy.allow_assertion_write
            or policy.allow_graph_write
            else []
        )
        extraction_profile_specs = (
            list(self._extraction_profile_provider())
            if getattr(self, "_extraction_profile_provider", None) is not None
            else None
        )
        extraction_profile = resolve_extraction_profile(
            stored_event,
            plugin_profile_specs=extraction_profile_specs,
        )
        self_entity_id = self._resolve_self_entity_id(stored_event)

        event_window = L2EventWindow(
            event_ids=batch_event_ids,
            events=[self._serialize_event_for_batch(item[0]) for item in eligible_events],
            texts=[item[0].content for item in eligible_events],
            context_texts=[
                msg.get("content", "") for msg in context_messages if msg.get("content", "").strip()
            ],
            history_contexts=history_contexts,
            summary=L2EventWindowSummary(
                event_count=len(eligible_events),
                session_id=stored_event.session_id,
                user_id=stored_event.user_id,
                history_context_count=len(history_contexts),
            ),
        )
        focal_subject = {
            "entity_ref": self_entity_id,
            "entity_type": "user" if self_entity_id else None,
        }

        existing_entities: list[dict[str, Any]] = []
        if self._entity_catalog is not None:
            existing_entities = await self._entity_catalog.list_entities(limit=30)

        self._inject_structured_entity_hints(stored_event, existing_entities)

        catalog_name_index = await self._build_catalog_name_index()
        direct_write_candidates, _direct_rejected = self._build_structured_graph_candidates(
            event=stored_event,
            profile=extraction_profile,
            policy=policy,
            evidence_event_ids=batch_event_ids,
            catalog_name_index=catalog_name_index,
        )
        direct_write_count = await self._direct_write_graph_candidates(
            event=stored_event,
            candidates=direct_write_candidates,
        )

        logger.info(
            "L2 Phase 1 extraction started",
            event_id=stored_event.event_id,
            profile_id=extraction_profile.profile_id,
            context_message_count=len(context_messages),
            history_context_count=len(history_contexts),
            existing_entity_count=len(existing_entities),
        )

        phase1_result = await self._llm_service.extract_phase1(
            event_window=event_window,
            focal_subject=focal_subject,
            existing_entities=existing_entities,
            context_messages=context_messages,
            extraction_instructions=extraction_profile.extraction_instructions,
        )

        resolved_mentions: list[ResolvedEntityMention] = []
        if policy.allow_entity_extraction and phase1_result.entities:
            resolved_mentions = await self._resolve_phase1_entities(
                stored_event,
                phase1_result,
                evidence_event_ids=batch_event_ids,
                allowed_entity_types=extraction_profile.allowed_entity_types,
            )

        logger.debug(
            "L2 Phase 1 completed",
            event_id=stored_event.event_id,
            entity_count=len(phase1_result.entities),
            fact_claim_count=len(phase1_result.fact_claims),
            resolved_ref_count=len(phase1_result.resolved_refs),
            resolved_mention_count=len(resolved_mentions),
        )

        await self._write_event_entity_links(
            event=stored_event,
            batch_event_ids=batch_event_ids,
            resolved_mentions=resolved_mentions,
        )
        await self._build_entity_semantic_edges(
            event=stored_event,
            resolved_mentions=resolved_mentions,
        )

        if not phase1_result.has_content:
            facet_candidates = self._build_structured_facet_candidates(
                event=stored_event,
                evidence_event_ids=batch_event_ids,
            )
            facet_count = await self._upsert_entity_facets(facet_candidates)

            logger.info(
                "L2 Phase 1 returned empty result, skipping Phase 2",
                event_id=stored_event.event_id,
                profile_id=extraction_profile.profile_id,
                evidence_class=classification.evidence_class,
                direct_write_count=direct_write_count,
                facet_count=facet_count,
            )
            return {
                "relation_count": direct_write_count,
                "assertion_count": 0,
                "touched_entity_ids": [],
                "snapshot_refresh_entity_ids": [],
                "skipped": False,
                "evidence_class": classification.evidence_class,
                "profile_id": extraction_profile.profile_id,
                "mention_count": len(phase1_result.entities),
                "direct_write_count": direct_write_count,
                "graph_candidate_count": 0,
                "assertion_candidate_count": 0,
                "rejected_graph_candidate_count": 0,
                "rejected_assertion_candidate_count": 0,
                "contradiction_hint_count": 0,
                "conflict_arbitration_decision": None,
            }

        existing_graph_edges: list[dict[str, Any]] = []
        existing_assertions: list[dict[str, Any]] = []
        focal_entities = self._build_focal_entities(stored_event, resolved_mentions)
        await self._emit_active_entities(event=stored_event, focal_entities=focal_entities)
        if self._cognition_store is not None:
            existing_graph_edges, existing_assertions = await self._load_existing_graph_context(
                focal_entities
            )

        if self._can_fast_track(
            phase1_result=phase1_result,
            resolved_mentions=resolved_mentions,
            existing_graph_edges=existing_graph_edges,
            profile=extraction_profile,
            policy=policy,
        ):
            fast_track_candidates = self._fast_track_claims_to_candidates(
                phase1_result=phase1_result,
                event=stored_event,
                evidence_event_ids=batch_event_ids,
                resolved_mentions=resolved_mentions,
                catalog_name_index=catalog_name_index,
                profile=extraction_profile,
            )
            facet_candidates = self._build_structured_facet_candidates(
                event=stored_event,
                evidence_event_ids=batch_event_ids,
            )
            relation_count = await self._upsert_knowledge_edges(fast_track_candidates)
            facet_count = await self._upsert_entity_facets(facet_candidates)
            touched_entity_ids = self._collect_touched_entities(fast_track_candidates, [])
            logger.info(
                "L2 fast-track: skipped Phase 2",
                event_id=stored_event.event_id,
                profile_id=extraction_profile.profile_id,
                relation_count=relation_count,
                direct_write_count=direct_write_count,
                facet_count=facet_count,
            )
            return {
                "relation_count": relation_count,
                "assertion_count": 0,
                "touched_entity_ids": touched_entity_ids,
                "snapshot_refresh_entity_ids": [],
                "skipped": False,
                "evidence_class": classification.evidence_class,
                "profile_id": extraction_profile.profile_id,
                "mention_count": len(phase1_result.entities),
                "direct_write_count": direct_write_count,
                "corroborate_count": 0,
                "graph_candidate_count": len(fast_track_candidates),
                "assertion_candidate_count": 0,
                "rejected_graph_candidate_count": 0,
                "rejected_assertion_candidate_count": 0,
                "contradiction_hint_count": 0,
                "conflict_arbitration_decision": None,
                "fast_tracked": True,
            }

        logger.info(
            "L2 Phase 2 integration started",
            event_id=stored_event.event_id,
            existing_edge_count=len(existing_graph_edges),
            existing_assertion_count=len(existing_assertions),
        )

        phase2_result = await self._llm_service.integrate_phase2(
            phase1_result=phase1_result,
            existing_graph_edges=existing_graph_edges,
            existing_assertions=existing_assertions,
            event_window=event_window,
            focal_subject=focal_subject,
        )

        catalog_name_index = await self._build_catalog_name_index()
        graph_candidates, corroborate_targets, rejected_graph_candidate_count = (
            self._validate_phase2_graph_edges(
                event=stored_event,
                profile=extraction_profile,
                policy=policy,
                resolved_mentions=resolved_mentions,
                evidence_event_ids=batch_event_ids,
                phase2_edges=phase2_result.graph_edges,
                catalog_name_index=catalog_name_index,
            )
        )
        facet_candidates = self._build_structured_facet_candidates(
            event=stored_event,
            evidence_event_ids=batch_event_ids,
        )

        assertion_dedup_context = self._merge_graph_candidates(
            graph_candidates,
            direct_write_candidates,
        )

        assertion_candidates, rejected_assertion_candidate_count = self._validate_phase2_assertions(
            event=stored_event,
            profile=extraction_profile,
            policy=policy,
            graph_candidates=assertion_dedup_context,
            default_event_ids=batch_event_ids,
            phase2_assertions=phase2_result.assertion_candidates,
        )

        contradiction_hints = self._convert_phase2_contradiction_hints(
            phase2_result.contradiction_hints
        )

        logger.info(
            "L2 Phase 2 candidate validation completed",
            event_id=stored_event.event_id,
            profile_id=extraction_profile.profile_id,
            graph_candidate_count=len(graph_candidates),
            assertion_candidate_count=len(assertion_candidates),
            rejected_graph_candidate_count=rejected_graph_candidate_count,
            rejected_assertion_candidate_count=rejected_assertion_candidate_count,
            contradiction_hint_count=len(contradiction_hints),
        )

        conflict_arbitration: L2ConflictArbitrationResult | None = None
        if contradiction_hints and (graph_candidates or assertion_candidates):
            conflict_arbitration = await self._arbitrate_conflicting_candidates(
                anchor_event=stored_event,
                batch_events=[item[0] for item in eligible_events],
                graph_candidates=graph_candidates,
                assertion_candidates=assertion_candidates,
                contradiction_hints=contradiction_hints,
            )
            arbitration_decision = (
                conflict_arbitration.decision if conflict_arbitration is not None else None
            )
            if arbitration_decision == "keep_existing":
                logger.info(
                    "L2 conflict arbitration kept existing records",
                    event_id=stored_event.event_id,
                    decision="keep_existing",
                    severe_hint_count=len(self._severe_contradiction_hints(contradiction_hints)),
                )
                graph_candidates = []
                assertion_candidates = []
                contradiction_hints = self._rewrite_hints_for_keep_existing(
                    contradiction_hints=contradiction_hints,
                    conflict_arbitration=conflict_arbitration,
                )
            elif arbitration_decision == "mark_evolution":
                contradiction_hints = self._rewrite_hints_for_evolution(
                    contradiction_hints=contradiction_hints,
                    conflict_arbitration=conflict_arbitration,
                )

        relation_count, corroborate_count, facet_count, assertion_count = (
            await self._persist_phase2_outputs(
                graph_candidates=graph_candidates,
                direct_write_candidates=direct_write_candidates,
                corroborate_targets=corroborate_targets,
                facet_candidates=facet_candidates,
                assertion_candidates=assertion_candidates,
                contradiction_hints=contradiction_hints,
            )
        )

        logger.info(
            "L2 persistence completed",
            event_id=stored_event.event_id,
            profile_id=extraction_profile.profile_id,
            relation_count=relation_count,
            corroborate_count=corroborate_count,
            facet_count=facet_count,
            assertion_count=assertion_count,
            contradiction_hint_count=len(contradiction_hints),
            conflict_arbitration_decision=conflict_arbitration.decision
            if conflict_arbitration is not None
            else None,
        )

        conflict_arbitration_decision = (
            conflict_arbitration.decision if conflict_arbitration is not None else None
        )
        touched_entity_ids = self._collect_touched_entities(
            graph_candidates + direct_write_candidates, assertion_candidates
        )
        if contradiction_hints:
            self_entity_id = self._resolve_self_entity_id(stored_event)
            if self_entity_id and self_entity_id not in touched_entity_ids:
                touched_entity_ids.append(self_entity_id)
        snapshot_refresh_entity_ids = (
            touched_entity_ids
            if conflict_arbitration_decision == "mark_evolution" and relation_count > 0
            else []
        )

        return {
            "relation_count": relation_count,
            "assertion_count": assertion_count,
            "touched_entity_ids": touched_entity_ids,
            "snapshot_refresh_entity_ids": snapshot_refresh_entity_ids,
            "skipped": False,
            "evidence_class": classification.evidence_class,
            "profile_id": extraction_profile.profile_id,
            "mention_count": len(phase1_result.entities),
            "resolved_context_ref_count": len(phase1_result.resolved_refs),
            "graph_candidate_count": len(graph_candidates),
            "direct_write_count": direct_write_count,
            "corroborate_count": corroborate_count,
            "assertion_candidate_count": len(assertion_candidates),
            "rejected_graph_candidate_count": rejected_graph_candidate_count,
            "rejected_assertion_candidate_count": rejected_assertion_candidate_count,
            "contradiction_hint_count": len(contradiction_hints),
            "conflict_arbitration_decision": conflict_arbitration_decision,
        }


__all__ = ["L2PipelineExtractionMixin"]
