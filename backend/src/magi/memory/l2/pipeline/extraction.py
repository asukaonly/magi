"""L2 extraction orchestration flow."""

from __future__ import annotations

from typing import Any

from ....core.logger import get_logger
from ...event_contracts import MemoryEvent
from ...evidence import (
    EvidenceClassification,
    PolicyDecision,
    classify_event_evidence,
    resolve_l2_policy,
)
from ..extraction_profiles import resolve_extraction_profile
from ..storage.utils import normalize_event_ids
from ..models import (
    L2BatchJob,
    L2EventWindow,
    L2EventWindowSummary,
    ResolvedEntityMention,
)
from .extraction_contracts import (
    L2ExtractionEventDecision,
    L2ExtractionPlan,
    _Phase1ExtractionFlow,
    _PreparedExtractionBatch,
)
from .external_dialogue_grounding import ground_phase1_external_dialogue_refs
from .claim_grounding import ground_phase1_fact_claims
from .phase2_flow import L2Phase2FlowMixin

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


def _l2_extraction_skip_result(
    *,
    skip_reason: str,
    evidence_class: str | None,
) -> dict[str, Any]:
    return {
        "relation_count": 0,
        "assertion_count": 0,
        "touched_entity_ids": [],
        "touched_place_ids": [],
        "touched_topic_keys": [],
        "skipped": True,
        "skip_reason": skip_reason,
        "evidence_class": evidence_class,
        "contradiction_hint_count": 0,
    }


def _policy_requires_extraction_context(policy: PolicyDecision) -> bool:
    return (
        policy.allow_entity_extraction
        or policy.allow_assertion_write
        or policy.allow_graph_write
    )


def _structured_only_result(batch: _PreparedExtractionBatch) -> dict[str, Any]:
    return {
        "relation_count": batch.direct_write_count,
        "assertion_count": 0,
        "touched_entity_ids": [],
        "touched_place_ids": [],
        "touched_topic_keys": [],
        "snapshot_refresh_entity_ids": [],
        "skipped": False,
        "evidence_class": batch.classification.evidence_class,
        "profile_id": batch.extraction_profile.profile_id,
        "mention_count": 0,
        "direct_write_count": batch.direct_write_count,
        "graph_candidate_count": 0,
        "assertion_candidate_count": 0,
        "rejected_graph_candidate_count": 0,
        "rejected_assertion_candidate_count": 0,
        "contradiction_hint_count": 0,
        "conflict_arbitration_decision": None,
        "structured_only": True,
    }


def _empty_phase1_result_payload(
    batch: _PreparedExtractionBatch,
    phase1_flow: _Phase1ExtractionFlow,
) -> dict[str, Any]:
    return {
        "relation_count": batch.direct_write_count,
        "assertion_count": 0,
        "touched_entity_ids": [],
        "touched_place_ids": [],
        "touched_topic_keys": [],
        "snapshot_refresh_entity_ids": [],
        "skipped": False,
        "evidence_class": batch.classification.evidence_class,
        "profile_id": batch.extraction_profile.profile_id,
        "mention_count": len(phase1_flow.phase1_result.entities),
        "direct_write_count": batch.direct_write_count,
        "graph_candidate_count": 0,
        "assertion_candidate_count": 0,
        "rejected_graph_candidate_count": 0,
        "rejected_assertion_candidate_count": 0,
        "contradiction_hint_count": 0,
        "conflict_arbitration_decision": None,
    }


def _prepared_extraction_batch(
    *,
    event: MemoryEvent,
    classification: EvidenceClassification,
    policy: PolicyDecision,
    eligible_events: list[tuple[MemoryEvent, EvidenceClassification, PolicyDecision]],
    batch_event_ids: list[str],
    context_messages: list[dict[str, Any]],
    history_contexts: list[dict[str, Any]],
    extraction_profile: Any,
    self_entity_id: str | None,
    event_window: L2EventWindow,
    existing_entities: list[dict[str, Any]],
    catalog_name_index: dict[str, Any],
    direct_write_candidates: list[dict[str, Any]],
    direct_write_count: int,
) -> _PreparedExtractionBatch:
    return _PreparedExtractionBatch(
        stored_event=event,
        classification=classification,
        policy=policy,
        eligible_events=eligible_events,
        batch_event_ids=batch_event_ids,
        context_messages=context_messages,
        history_contexts=history_contexts,
        extraction_profile=extraction_profile,
        self_entity_id=self_entity_id,
        event_window=event_window,
        focal_subject={
            "entity_ref": self_entity_id,
            "entity_type": "user" if self_entity_id else None,
        },
        existing_entities=existing_entities,
        catalog_name_index=catalog_name_index,
        direct_write_candidates=direct_write_candidates,
        direct_write_count=direct_write_count,
    )


def build_l2_extraction_plan(stored_events: list[MemoryEvent]) -> L2ExtractionPlan:
    """Classify a batch and select the write-eligible L2 extraction workset."""
    if not stored_events:
        return L2ExtractionPlan(
            decisions=[],
            eligible_decisions=[],
            primary=None,
            batch_event_ids=[],
            skip_result=_l2_extraction_skip_result(
                skip_reason="empty_batch",
                evidence_class=None,
            ),
        )

    decisions = [
        L2ExtractionEventDecision(
            event=event,
            classification=(classification := classify_event_evidence(event)),
            policy=resolve_l2_policy(classification),
        )
        for event in stored_events
    ]
    eligible_decisions = [decision for decision in decisions if decision.is_write_eligible]
    if not eligible_decisions:
        last_decision = decisions[-1]
        return L2ExtractionPlan(
            decisions=decisions,
            eligible_decisions=[],
            primary=None,
            batch_event_ids=[],
            skip_result=_l2_extraction_skip_result(
                skip_reason=last_decision.policy.skip_reason or "no_eligible_events",
                evidence_class=last_decision.classification.evidence_class,
            ),
        )

    return L2ExtractionPlan(
        decisions=decisions,
        eligible_decisions=eligible_decisions,
        primary=eligible_decisions[-1],
        batch_event_ids=normalize_event_ids(
            [decision.event.event_id for decision in eligible_decisions]
        ),
        skip_result=None,
    )


class L2PipelineExtractionMixin(L2Phase2FlowMixin):
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
        extraction_plan = build_l2_extraction_plan(stored_events)
        self._record_extraction_decisions(extraction_plan)

        if extraction_plan.skip_result is not None:
            skip_reason = str(extraction_plan.skip_result.get("skip_reason") or "")
            if skip_reason:
                self._increment_bucket(self._stats.skip_by_reason, skip_reason)
            return extraction_plan.skip_result

        primary_decision = extraction_plan.primary
        if primary_decision is None:  # pragma: no cover - defensive guard
            return _l2_extraction_skip_result(
                skip_reason="no_eligible_events",
                evidence_class=None,
            )
        policy_skip = self._policy_skip_result(primary_decision)
        if policy_skip is not None:
            return policy_skip

        batch = await self._prepare_extraction_batch(extraction_plan, primary_decision)
        structured_only_result = await self._maybe_structured_only(batch)
        if structured_only_result is not None:
            return structured_only_result

        phase1_flow = await self._run_phase1_extraction(batch)
        await self._persist_phase1_outputs(batch, phase1_flow)
        if not phase1_flow.phase1_result.has_content:
            return await self._empty_phase1_result(batch, phase1_flow)

        return await self._run_phase2_flow(batch, phase1_flow)

    def _record_extraction_decisions(self: Any, extraction_plan: L2ExtractionPlan) -> None:
        for decision in extraction_plan.decisions:
            event = decision.event
            classification = decision.classification
            policy = decision.policy
            self._increment_bucket(
                self._stats.extract_by_evidence_class,
                classification.evidence_class,
            )
            logger.debug(
                "L2 evidence classified",
                event_id=event.event_id,
                evidence_class=classification.evidence_class,
                grounding_type=classification.grounding_type,
                semantic_owner=classification.semantic_owner,
                originality_type=classification.originality_type,
                source_event_ids=classification.source_event_ids,
            )
            logger.debug(
                "L2 policy resolved",
                event_id=event.event_id,
                evidence_class=classification.evidence_class,
                allow_entity_extraction=policy.allow_entity_extraction,
                allow_graph_write=policy.allow_graph_write,
                allow_assertion_write=policy.allow_assertion_write,
                allow_snapshot_impact=policy.allow_snapshot_impact,
                graph_scope=policy.graph_scope,
                assertion_scope=policy.assertion_scope,
                skip_reason=policy.skip_reason,
            )

    def _policy_skip_result(
        self: Any,
        primary_decision: L2ExtractionEventDecision,
    ) -> dict[str, Any] | None:
        policy = primary_decision.policy
        if policy.allow_graph_write or policy.allow_assertion_write:
            return None
        if policy.skip_reason:
            self._increment_bucket(self._stats.skip_by_reason, policy.skip_reason)
        return _l2_extraction_skip_result(
            skip_reason=policy.skip_reason,
            evidence_class=primary_decision.classification.evidence_class,
        )

    async def _prepare_extraction_batch(
        self: Any,
        extraction_plan: L2ExtractionPlan,
        primary_decision: L2ExtractionEventDecision,
    ) -> _PreparedExtractionBatch:
        event, policy = primary_decision.event, primary_decision.policy
        eligible_events = self._eligible_event_tuples(extraction_plan)
        batch_event_ids = extraction_plan.batch_event_ids
        context_messages, history_contexts = await self._load_batch_contexts(
            event,
            policy,
            eligible_events,
            batch_event_ids,
        )
        extraction_profile = self._resolve_batch_extraction_profile(event)
        self_entity_id = self._resolve_self_entity_id(event)
        event_window = await self._build_extraction_event_window(
            event=event,
            eligible_events=eligible_events,
            batch_event_ids=batch_event_ids,
            context_messages=context_messages,
            history_contexts=history_contexts,
        )
        existing_entities = await self._load_batch_existing_entities(eligible_events)
        catalog_name_index = await self._build_catalog_name_index()
        direct_write_candidates, direct_write_count = await self._prepare_direct_graph_writes(
            eligible_events=eligible_events,
            catalog_name_index=catalog_name_index,
        )
        return _prepared_extraction_batch(
            event=event,
            classification=primary_decision.classification,
            policy=policy,
            eligible_events=eligible_events,
            batch_event_ids=batch_event_ids,
            context_messages=context_messages,
            history_contexts=history_contexts,
            extraction_profile=extraction_profile,
            self_entity_id=self_entity_id,
            event_window=event_window,
            existing_entities=existing_entities,
            catalog_name_index=catalog_name_index,
            direct_write_candidates=direct_write_candidates,
            direct_write_count=direct_write_count,
        )

    def _eligible_event_tuples(
        self: Any,
        extraction_plan: L2ExtractionPlan,
    ) -> list[tuple[MemoryEvent, EvidenceClassification, PolicyDecision]]:
        return [
            (decision.event, decision.classification, decision.policy)
            for decision in extraction_plan.eligible_decisions
        ]

    async def _load_batch_contexts(
        self: Any,
        event: MemoryEvent,
        policy: PolicyDecision,
        eligible_events: list[tuple[MemoryEvent, EvidenceClassification, PolicyDecision]],
        batch_event_ids: list[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        context_messages = await self._load_batch_context_messages(
            event,
            policy,
            batch_event_ids,
        )
        history_contexts = await self._load_batch_history_contexts(
            event,
            policy,
            eligible_events,
            batch_event_ids,
        )
        return context_messages, history_contexts

    async def _load_batch_context_messages(
        self: Any,
        event: MemoryEvent,
        policy: PolicyDecision,
        batch_event_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not _policy_requires_extraction_context(policy):
            return []
        return await self._load_context_messages(event, exclude_event_ids=batch_event_ids)

    async def _load_batch_history_contexts(
        self: Any,
        event: MemoryEvent,
        policy: PolicyDecision,
        eligible_events: list[tuple[MemoryEvent, EvidenceClassification, PolicyDecision]],
        batch_event_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not _policy_requires_extraction_context(policy):
            return []
        return await self._load_history_contexts(
            anchor_event=event,
            batch_events=[item[0] for item in eligible_events],
            exclude_event_ids=batch_event_ids,
        )

    def _resolve_batch_extraction_profile(self: Any, event: MemoryEvent) -> Any:
        profile_specs = (
            list(self._extraction_profile_provider())
            if getattr(self, "_extraction_profile_provider", None) is not None
            else None
        )
        return resolve_extraction_profile(event, plugin_profile_specs=profile_specs)

    async def _build_extraction_event_window(
        self: Any,
        *,
        event: MemoryEvent,
        eligible_events: list[tuple[MemoryEvent, EvidenceClassification, PolicyDecision]],
        batch_event_ids: list[str],
        context_messages: list[dict[str, Any]],
        history_contexts: list[dict[str, Any]],
    ) -> L2EventWindow:
        batch_events = [item[0] for item in eligible_events]
        pinned_by_id = await self._fetch_pinned_payloads(batch_event_ids)
        return L2EventWindow(
            event_ids=batch_event_ids,
            events=[self._serialize_event_for_batch(item) for item in batch_events],
            texts=resolve_window_texts(batch_events, pinned_by_id),
            context_texts=[
                msg.get("content", "")
                for msg in context_messages
                if msg.get("content", "").strip()
            ],
            history_contexts=history_contexts,
            summary=L2EventWindowSummary(
                event_count=len(eligible_events),
                session_id=event.session_id,
                user_id=event.user_id,
                history_context_count=len(history_contexts),
            ),
        )

    async def _load_batch_existing_entities(
        self: Any,
        eligible_events: list[tuple[MemoryEvent, EvidenceClassification, PolicyDecision]],
    ) -> list[dict[str, Any]]:
        existing_entities: list[dict[str, Any]] = []
        if self._entity_catalog is not None:
            for event, _classification, _policy in eligible_events:
                await self._upsert_structured_hint_entities(event)
            existing_entities = await self._entity_catalog.list_entities(limit=30)
        for event, _classification, _policy in eligible_events:
            self._inject_structured_entity_hints(event, existing_entities)
        return existing_entities

    async def _prepare_direct_graph_writes(
        self: Any,
        *,
        eligible_events: list[tuple[MemoryEvent, EvidenceClassification, PolicyDecision]],
        catalog_name_index: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        all_candidates: list[dict[str, Any]] = []
        direct_write_count = 0
        for event, classification, policy in eligible_events:
            profile = self._resolve_batch_extraction_profile(event)
            candidates, _direct_rejected = self._build_structured_graph_candidates(
                event=event,
                profile=profile,
                policy=policy,
                evidence_event_ids=[event.event_id],
                catalog_name_index=catalog_name_index,
                classification=classification,
            )
            direct_write_count += await self._direct_write_graph_candidates(
                event=event,
                candidates=candidates,
            )
            all_candidates.extend(candidates)
        return all_candidates, direct_write_count

    async def _maybe_structured_only(
        self: Any,
        batch: _PreparedExtractionBatch,
    ) -> dict[str, Any] | None:
        should_extract = await resolve_llm_extraction(
            batch.stored_event,
            getattr(self, "_promotion_counter", None),
        )
        if should_extract:
            return None
        facet_count = await self._upsert_structured_facets(batch)
        logger.info(
            "L2 structured-only mode: skipped LLM phase1/2",
            event_id=batch.stored_event.event_id,
            profile_id=batch.extraction_profile.profile_id,
            direct_write_count=batch.direct_write_count,
            facet_count=facet_count,
        )
        return _structured_only_result(batch)

    async def _upsert_structured_facets(self: Any, batch: _PreparedExtractionBatch) -> int:
        facet_candidates = self._build_structured_facet_candidates(
            event=batch.stored_event,
            evidence_event_ids=batch.batch_event_ids,
        )
        return await self._upsert_entity_facets(facet_candidates)

    async def _run_phase1_extraction(
        self: Any,
        batch: _PreparedExtractionBatch,
    ) -> _Phase1ExtractionFlow:
        logger.info(
            "L2 Phase 1 extraction started",
            event_id=batch.stored_event.event_id,
            profile_id=batch.extraction_profile.profile_id,
            context_message_count=len(batch.context_messages),
            history_context_count=len(batch.history_contexts),
            existing_entity_count=len(batch.existing_entities),
        )
        phase1_result = await self._llm_service.extract_phase1(
            event_window=batch.event_window,
            focal_subject=batch.focal_subject,
            existing_entities=batch.existing_entities,
            context_messages=batch.context_messages,
            extraction_instructions=batch.extraction_profile.extraction_instructions,
        )
        self._ground_phase1_result(batch, phase1_result)
        profile_signal_object_refs = self._collect_profile_signal_object_refs(phase1_result)
        resolved_mentions = await self._resolve_phase1_mentions(
            batch,
            phase1_result,
            profile_signal_object_refs,
        )
        logger.debug(
            "L2 Phase 1 completed",
            event_id=batch.stored_event.event_id,
            entity_count=len(phase1_result.entities),
            fact_claim_count=len(phase1_result.fact_claims),
            resolved_ref_count=len(phase1_result.resolved_refs),
            resolved_mention_count=len(resolved_mentions),
        )
        return _Phase1ExtractionFlow(
            phase1_result=phase1_result,
            resolved_mentions=resolved_mentions,
            profile_signal_object_refs=profile_signal_object_refs,
        )

    def _ground_phase1_result(self: Any, batch: _PreparedExtractionBatch, phase1_result: Any) -> None:
        external_dialogue_stats = ground_phase1_external_dialogue_refs(
            phase1_result,
            batch.event_window,
        )
        if any(external_dialogue_stats.values()):
            logger.info(
                "L2 external dialogue speaker grounding applied",
                event_id=batch.stored_event.event_id,
                **external_dialogue_stats,
            )
        rejected_count = self._filter_ungrounded_profile_signal_claims(
            phase1_result,
            batch.event_window.events,
        )
        if rejected_count:
            logger.info(
                "L2 Phase 1 profile signal claims filtered by user evidence",
                event_id=batch.stored_event.event_id,
                rejected_profile_signal_claim_count=rejected_count,
            )
        claim_grounding_stats = ground_phase1_fact_claims(
            phase1_result,
            batch.event_window,
        )
        if claim_grounding_stats["rejected"] or claim_grounding_stats["rebound"]:
            logger.info(
                "L2 Phase 1 claim evidence grounding applied",
                event_id=batch.stored_event.event_id,
                **claim_grounding_stats,
            )

    async def _resolve_phase1_mentions(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_result: Any,
        profile_signal_object_refs: set[str],
    ) -> list[ResolvedEntityMention]:
        if not batch.policy.allow_entity_extraction or not phase1_result.entities:
            return []
        return await self._resolve_phase1_entities(
            batch.stored_event,
            phase1_result,
            evidence_event_ids=batch.batch_event_ids,
            evidence_events=[item[0] for item in batch.eligible_events],
            allowed_entity_types=batch.extraction_profile.allowed_entity_types,
            profile_signal_object_refs=profile_signal_object_refs,
        )

    async def _persist_phase1_outputs(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
    ) -> None:
        await self._write_event_entity_links(
            event=batch.stored_event,
            batch_event_ids=batch.batch_event_ids,
            resolved_mentions=phase1_flow.resolved_mentions,
        )
        await self._build_entity_semantic_edges(
            event=batch.stored_event,
            resolved_mentions=phase1_flow.resolved_mentions,
        )

    async def _empty_phase1_result(
        self: Any,
        batch: _PreparedExtractionBatch,
        phase1_flow: _Phase1ExtractionFlow,
    ) -> dict[str, Any]:
        facet_count = await self._upsert_structured_facets(batch)
        logger.info(
            "L2 Phase 1 returned empty result, skipping Phase 2",
            event_id=batch.stored_event.event_id,
            profile_id=batch.extraction_profile.profile_id,
            evidence_class=batch.classification.evidence_class,
            direct_write_count=batch.direct_write_count,
            facet_count=facet_count,
        )
        return _empty_phase1_result_payload(batch, phase1_flow)

__all__ = ["L2PipelineExtractionMixin"]
