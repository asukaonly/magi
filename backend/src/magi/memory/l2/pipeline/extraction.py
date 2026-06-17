"""L2 extraction orchestration flow."""

from __future__ import annotations

from typing import Any

from ....core.logger import get_logger
from ...event_contracts import MemoryEvent
from ...evidence import classify_event_evidence, resolve_l2_policy
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


def event_allows_llm_extraction(event: Any) -> bool:
    """Whether an event may drive LLM phase1/2 extraction.

    A sensor can set ``allow_llm_extraction=False`` (carried in ``metadata_json``) to run
    in "structured-only" mode: deterministic direct-writes still happen, but the LLM
    extractor is skipped. A missing key defaults to True (full extraction).
    """
    metadata = getattr(event, "metadata_json", None) or {}
    return bool(metadata.get("allow_llm_extraction", True))


async def resolve_llm_extraction(event: Any, counter: Any) -> bool:
    """Final per-event LLM-extraction decision: P4 override, then P1 flag + P2 gate.

    - P4: a per-event ``promotion_override`` (metadata_json) is the escape hatch —
      ``force_full`` runs full extraction and ``force_structured_only`` skips it,
      either way beating both P1 and P2. An unknown value is ignored.
    - P1: if ``allow_llm_extraction`` is False -> structured-only (skip LLM).
    - P2: a sensor declaring ``promotion_threshold`` (metadata_json) + a per-event
      ``promotion_key`` runs structured-only until the key has been seen >= threshold
      times, then is promoted to full extraction (and stays promoted).
    No counter or no frequency policy -> falls back to the P1 flag.
    """
    metadata = getattr(event, "metadata_json", None) or {}
    override = str(metadata.get("promotion_override") or "").strip()
    if override == "force_full":
        return True
    if override == "force_structured_only":
        return False
    if not event_allows_llm_extraction(event):
        return False
    threshold = int(metadata.get("promotion_threshold") or 0)
    key = str(metadata.get("promotion_key") or "").strip()
    if threshold <= 0 or not key or counter is None:
        return True
    source_type = str(getattr(event, "source", "") or "")
    event_id = str(getattr(event, "event_id", "") or "")
    _count, promoted = await counter.bump(source_type, key, event_id, threshold=threshold)
    return bool(promoted)


def resolve_window_texts(events: Any, pinned_by_id: dict[str, str]) -> list[str]:
    """Per-event window text for L2 extraction: the pinned capture-time full text
    when present, else the lean L1 ``content`` (RFC #56 P3).

    L2 reads the frozen snapshot, never the live source. An empty/missing pinned
    value falls back to ``content`` so a blank snapshot never erases the text.
    """
    return [
        (pinned_by_id.get(getattr(ev, "event_id", "") or "") or getattr(ev, "content", "") or "")
        for ev in events
    ]


class L2PipelineExtractionMixin:
    """Run the end-to-end L2 Phase 1/Phase 2 extraction and persistence flow."""

    async def _fetch_pinned_payloads(self: Any, event_ids: Any) -> dict[str, str]:
        """Batch-load pinned capture-time full texts for the window (RFC #56 P3).

        Asks L1 (owner of the pinned-payload satellite). Resilient to a missing
        store/method or read error -> empty map, so extraction falls back to the
        lean ``content``.
        """
        ids = [e for e in (event_ids or []) if e]
        if not ids:
            return {}
        l1 = getattr(self, "_l1_store", None)
        getter = getattr(l1, "get_pinned_payloads", None) if l1 is not None else None
        if getter is None:
            return {}
        try:
            return await getter(ids)
        except Exception:
            return {}

    async def _extract_and_persist(self: Any, job: L2BatchJob) -> dict[str, Any]:
        if self._cognition_store is None:
            return {
                "relation_count": 0,
                "assertion_count": 0,
                "touched_entity_ids": [],
                "touched_place_ids": [],
                "touched_topic_keys": [],
                "skipped": True,
            }

        stored_events = await self._load_batch_events(job)
        if not stored_events:
            return {
                "relation_count": 0,
                "assertion_count": 0,
                "touched_entity_ids": [],
                "touched_place_ids": [],
                "touched_topic_keys": [],
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
                "touched_place_ids": [],
                "touched_topic_keys": [],
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
                "touched_place_ids": [],
                "touched_topic_keys": [],
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

        pinned_by_id = await self._fetch_pinned_payloads(batch_event_ids)
        event_window = L2EventWindow(
            event_ids=batch_event_ids,
            events=[self._serialize_event_for_batch(item[0]) for item in eligible_events],
            texts=resolve_window_texts([item[0] for item in eligible_events], pinned_by_id),
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
            await self._upsert_structured_hint_entities(stored_event)
            existing_entities = await self._entity_catalog.list_entities(limit=30)

        self._inject_structured_entity_hints(stored_event, existing_entities)

        catalog_name_index = await self._build_catalog_name_index()
        direct_write_candidates, _direct_rejected = self._build_structured_graph_candidates(
            event=stored_event,
            profile=extraction_profile,
            policy=policy,
            evidence_event_ids=batch_event_ids,
            catalog_name_index=catalog_name_index,
            classification=classification,
        )
        direct_write_count = await self._direct_write_graph_candidates(
            event=stored_event,
            candidates=direct_write_candidates,
        )

        if not await resolve_llm_extraction(stored_event, getattr(self, "_promotion_counter", None)):
            # Structured-only (P1 opt-out or P2 below-threshold): direct-writes done above; skip LLM.
            facet_candidates = self._build_structured_facet_candidates(
                event=stored_event,
                evidence_event_ids=batch_event_ids,
            )
            facet_count = await self._upsert_entity_facets(facet_candidates)
            logger.info(
                "L2 structured-only mode: skipped LLM phase1/2",
                event_id=stored_event.event_id,
                profile_id=extraction_profile.profile_id,
                direct_write_count=direct_write_count,
                facet_count=facet_count,
            )
            return {
                "relation_count": direct_write_count,
                "assertion_count": 0,
                "touched_entity_ids": [],
                "touched_place_ids": [],
                "touched_topic_keys": [],
                "snapshot_refresh_entity_ids": [],
                "skipped": False,
                "evidence_class": classification.evidence_class,
                "profile_id": extraction_profile.profile_id,
                "mention_count": 0,
                "direct_write_count": direct_write_count,
                "graph_candidate_count": 0,
                "assertion_candidate_count": 0,
                "rejected_graph_candidate_count": 0,
                "rejected_assertion_candidate_count": 0,
                "contradiction_hint_count": 0,
                "conflict_arbitration_decision": None,
                "structured_only": True,
            }

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
        rejected_profile_signal_claim_count = self._filter_ungrounded_profile_signal_claims(
            phase1_result,
            event_window.events,
        )
        if rejected_profile_signal_claim_count:
            logger.info(
                "L2 Phase 1 profile signal claims filtered by user evidence",
                event_id=stored_event.event_id,
                rejected_profile_signal_claim_count=rejected_profile_signal_claim_count,
            )

        profile_signal_object_refs = self._collect_profile_signal_object_refs(phase1_result)
        resolved_mentions: list[ResolvedEntityMention] = []
        if policy.allow_entity_extraction and phase1_result.entities:
            resolved_mentions = await self._resolve_phase1_entities(
                stored_event,
                phase1_result,
                evidence_event_ids=batch_event_ids,
                evidence_events=[item[0] for item in eligible_events],
                allowed_entity_types=extraction_profile.allowed_entity_types,
                profile_signal_object_refs=profile_signal_object_refs,
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
                "touched_place_ids": [],
                "touched_topic_keys": [],
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
            catalog_name_index=catalog_name_index,
        ):
            fast_track_candidates = self._fast_track_claims_to_candidates(
                phase1_result=phase1_result,
                event=stored_event,
                evidence_event_ids=batch_event_ids,
                resolved_mentions=resolved_mentions,
                catalog_name_index=catalog_name_index,
                profile=extraction_profile,
                classification=classification,
            )
            facet_candidates = self._build_structured_facet_candidates(
                event=stored_event,
                evidence_event_ids=batch_event_ids,
            )
            relation_count = await self._upsert_knowledge_edges(fast_track_candidates)
            facet_count = await self._upsert_entity_facets(facet_candidates)
            touched_entity_ids = self._collect_touched_entities(fast_track_candidates, [])
            touched_place_ids, touched_topic_keys = self._derive_place_and_topic_hints(
                touched_entity_ids
            )
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
                "touched_place_ids": touched_place_ids,
                "touched_topic_keys": touched_topic_keys,
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
            phase2_instructions=extraction_profile.phase2_instructions,
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
                profile_signal_object_refs=profile_signal_object_refs,
                catalog_name_index=catalog_name_index,
                classification=classification,
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
            phase1_result=phase1_result,
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
        touched_place_ids, touched_topic_keys = self._derive_place_and_topic_hints(
            touched_entity_ids
        )
        snapshot_refresh_entity_ids = (
            touched_entity_ids
            if conflict_arbitration_decision == "mark_evolution" and relation_count > 0
            else []
        )

        return {
            "relation_count": relation_count,
            "assertion_count": assertion_count,
            "touched_entity_ids": touched_entity_ids,
            "touched_place_ids": touched_place_ids,
            "touched_topic_keys": touched_topic_keys,
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
