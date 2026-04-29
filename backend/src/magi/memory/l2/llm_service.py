"""Thin LLM wrapper for L2 prompt execution and JSON-safe parsing."""

from __future__ import annotations

import time
from typing import Any

from ...core.logger import get_logger
from ...llm import LLMScenario, ScenarioLLMPool
from .llm_json_client import L2LLMJsonClientMixin
from .models import (
    ContradictionHint,
    L2BatchEntityResolutionItem,
    L2CandidateSet,
    L2ConflictArbitrationResult,
    L2EntityCandidate,
    L2EntityResolution,
    L2EntityResolutionMention,
    L2ExistingRecord,
    L2Phase1Result,
    L2Phase2Result,
    L2ReconcileAssertion,
    L2ReconcileEntity,
    L2ReconcileGraphFact,
    L2SourceEvent,
    L2EventWindow,
    ReconciledTraitOutcome,
)
from .pipeline.prompts import (
    BATCH_ENTITY_RESOLUTION_SYSTEM_PROMPT,
    CONFLICT_ARBITRATION_SYSTEM_PROMPT,
    ENTITY_RECONCILE_SYSTEM_PROMPT,
    ENTITY_RESOLUTION_SYSTEM_PROMPT,
    PHASE1_EXTRACT_SYSTEM_PROMPT,
    PHASE2_INTEGRATE_SYSTEM_PROMPT,
    render_batch_entity_resolution_prompt,
    render_conflict_arbitration_prompt,
    render_entity_reconcile_prompt,
    render_entity_resolution_prompt,
    render_phase1_extract_prompt,
    render_phase2_integrate_prompt,
)

logger = get_logger(__name__)


class L2LLMService(L2LLMJsonClientMixin):
    """Executes L2 prompts with conservative failure handling."""

    def __init__(self, scenario_llm_pool: ScenarioLLMPool | None) -> None:
        self._scenario_llm_pool = scenario_llm_pool

    # ------------------------------------------------------------------
    # Two-phase extraction
    # ------------------------------------------------------------------

    async def extract_phase1(
        self,
        *,
        event_window: L2EventWindow,
        focal_subject: dict[str, Any],
        existing_entities: list[dict[str, Any]] | None = None,
        context_messages: list[dict[str, Any]] | None = None,
        extraction_instructions: str | None = None,
    ) -> L2Phase1Result:
        """Phase 1: extract entities, resolve references, produce fact claims."""
        started_at = time.perf_counter()
        event_ids = list(event_window.event_ids)
        session_id = self._non_empty_text(event_window.summary.session_id)
        user_id = self._non_empty_text(event_window.summary.user_id)
        logger.info(
            "L2 Phase 1 extraction started",
            event_ids=event_ids,
            batch_event_count=len(event_window.events),
            session_id=session_id,
            user_id=user_id,
        )
        prompt = render_phase1_extract_prompt(
            event_window=event_window,
            focal_subject=focal_subject,
            existing_entities=existing_entities,
            context_messages=context_messages,
            extraction_instructions=extraction_instructions,
        )
        payload = await self._generate_json(
            system_prompt=PHASE1_EXTRACT_SYSTEM_PROMPT,
            prompt=prompt,
            request_kind="memory:l2_phase1_extract",
            turn_id=event_ids[0] if event_ids else None,
            session_id=session_id,
            log_context={
                "event_ids": event_ids,
                "batch_event_count": len(event_window.events),
                "session_id": session_id,
                "user_id": user_id,
                "existing_entity_count": len(existing_entities) if existing_entities else 0,
                "context_message_count": len(context_messages) if context_messages else 0,
            },
        )
        result = L2Phase1Result.from_dict(payload)
        # Cap assertion-level confidence for single-event windows.
        is_single_event = len(event_window.event_ids) <= 1
        if is_single_event:
            for claim in result.fact_claims:
                claim.confidence = min(claim.confidence, 0.3)
        duration_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        logger.info(
            "L2 Phase 1 extraction completed",
            duration_ms=duration_ms,
            event_ids=event_ids,
            entity_count=len(result.entities),
            fact_claim_count=len(result.fact_claims),
            resolved_ref_count=len(result.resolved_refs),
            entity_status=result.diagnostics.get("entity_status"),
        )
        return result

    async def integrate_phase2(
        self,
        *,
        phase1_result: L2Phase1Result,
        existing_graph_edges: list[dict[str, Any]] | None = None,
        existing_assertions: list[dict[str, Any]] | None = None,
        event_window: L2EventWindow,
        focal_subject: dict[str, Any],
    ) -> L2Phase2Result:
        """Phase 2: integrate facts with existing graph, produce edges/assertions/contradictions."""
        started_at = time.perf_counter()
        event_ids = list(event_window.event_ids)
        session_id = self._non_empty_text(event_window.summary.session_id)
        logger.info(
            "L2 Phase 2 integration started",
            event_ids=event_ids,
            fact_claim_count=len(phase1_result.fact_claims),
            existing_edge_count=len(existing_graph_edges) if existing_graph_edges else 0,
            existing_assertion_count=len(existing_assertions) if existing_assertions else 0,
        )
        prompt = render_phase2_integrate_prompt(
            phase1_result=phase1_result.to_dict(),
            existing_graph_edges=existing_graph_edges,
            existing_assertions=existing_assertions,
            event_window=event_window,
            focal_subject=focal_subject,
        )
        payload = await self._generate_json(
            system_prompt=PHASE2_INTEGRATE_SYSTEM_PROMPT,
            prompt=prompt,
            request_kind="memory:l2_phase2_integrate",
            turn_id=event_ids[0] if event_ids else None,
            session_id=session_id,
            log_context={
                "event_ids": event_ids,
                "fact_claim_count": len(phase1_result.fact_claims),
                "existing_edge_count": len(existing_graph_edges) if existing_graph_edges else 0,
                "existing_assertion_count": len(existing_assertions) if existing_assertions else 0,
            },
        )
        result = L2Phase2Result.from_dict(payload)
        # Cap assertion confidence for single-event windows.
        is_single_event = len(event_window.event_ids) <= 1
        if is_single_event:
            for assertion in result.assertion_candidates:
                assertion.confidence = min(assertion.confidence, 0.3)
        duration_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        logger.info(
            "L2 Phase 2 integration completed",
            duration_ms=duration_ms,
            event_ids=event_ids,
            graph_edge_count=len(result.graph_edges),
            assertion_count=len(result.assertion_candidates),
            contradiction_hint_count=len(result.contradiction_hints),
            refinement_count=len(result.refinements),
        )
        return result

    async def resolve_entity(
        self,
        *,
        mention: L2EntityResolutionMention,
        candidate_entities: list[L2EntityCandidate],
        min_confidence: float = 0.8,
    ) -> L2EntityResolution:
        payload = await self._generate_json(
            system_prompt=ENTITY_RESOLUTION_SYSTEM_PROMPT,
            prompt=render_entity_resolution_prompt(
                mention=mention, candidate_entities=candidate_entities
            ),
            request_kind="memory:l2_entity_resolution",
        )
        resolution = payload.get("resolution")
        if not isinstance(resolution, dict):
            return self._unresolved_resolution()

        confidence = float(resolution.get("confidence", 0.0) or 0.0)
        decision = str(resolution.get("decision", "unresolved"))
        if decision == "match" and confidence < min_confidence:
            return self._unresolved_resolution(confidence=confidence)

        matched_entity_id = resolution.get("matched_entity_id")
        if decision != "match" or not matched_entity_id:
            return self._unresolved_resolution(confidence=confidence)

        return L2EntityResolution(
            decision="match",
            matched_entity_id=str(matched_entity_id),
            matched_entity_name=resolution.get("matched_entity_name"),
            confidence=confidence,
            reason_tags=resolution.get("reason_tags", []),
            should_merge=bool(resolution.get("should_merge", False)),
            canonical_name_suggestion=resolution.get("canonical_name_suggestion"),
        )

    async def resolve_entities_batch(
        self,
        *,
        items: list[L2BatchEntityResolutionItem],
        min_confidence: float = 0.8,
    ) -> dict[str, L2EntityResolution]:
        """Resolve multiple entity mentions in a single LLM call.

        Returns a dict mapping mention_key → L2EntityResolution.
        """
        if not items:
            return {}

        # Single item → delegate to non-batch path for efficiency
        if len(items) == 1:
            item = items[0]
            result = await self.resolve_entity(
                mention=item.mention,
                candidate_entities=item.candidate_entities,
                min_confidence=min_confidence,
            )
            return {item.mention_key: result}

        payload = await self._generate_json(
            system_prompt=BATCH_ENTITY_RESOLUTION_SYSTEM_PROMPT,
            prompt=render_batch_entity_resolution_prompt(items=items),
            request_kind="memory:l2_entity_resolution",
        )
        raw_resolutions = payload.get("resolutions")
        if not isinstance(raw_resolutions, list):
            return {item.mention_key: self._unresolved_resolution() for item in items}

        results: dict[str, L2EntityResolution] = {}
        for raw in raw_resolutions:
            if not isinstance(raw, dict):
                continue
            mention_key = str(raw.get("mention_key", ""))
            if not mention_key:
                continue
            confidence = float(raw.get("confidence", 0.0) or 0.0)
            decision = str(raw.get("decision", "unresolved"))
            if decision == "match" and confidence < min_confidence:
                results[mention_key] = self._unresolved_resolution(confidence=confidence)
                continue
            matched_entity_id = raw.get("matched_entity_id")
            if decision != "match" or not matched_entity_id:
                results[mention_key] = self._unresolved_resolution(confidence=confidence)
                continue
            results[mention_key] = L2EntityResolution(
                decision="match",
                matched_entity_id=str(matched_entity_id),
                matched_entity_name=raw.get("matched_entity_name"),
                confidence=confidence,
                reason_tags=raw.get("reason_tags", []),
                should_merge=bool(raw.get("should_merge", False)),
                canonical_name_suggestion=raw.get("canonical_name_suggestion"),
            )

        # Fill in any missing keys as unresolved
        for item in items:
            if item.mention_key not in results:
                results[item.mention_key] = self._unresolved_resolution()

        return results

    async def arbitrate_conflict(
        self,
        *,
        new_event_window: L2EventWindow,
        new_candidates: L2CandidateSet,
        contradiction_hints: list[ContradictionHint],
        existing_records: list[L2ExistingRecord],
        source_events: list[L2SourceEvent],
    ) -> L2ConflictArbitrationResult | None:
        event_ids = list(new_event_window.event_ids)
        contradiction_hint_payload = [hint.to_dict() for hint in contradiction_hints]
        payload = await self._generate_json(
            system_prompt=CONFLICT_ARBITRATION_SYSTEM_PROMPT,
            prompt=render_conflict_arbitration_prompt(
                new_event_window=new_event_window,
                new_candidates=new_candidates,
                contradiction_hints=contradiction_hint_payload,
                existing_records=existing_records,
                source_events=source_events,
            ),
            request_kind="memory:l2_conflict_arbitration",
            turn_id=str(event_ids[0]) if isinstance(event_ids, list) and event_ids else None,
            session_id=self._non_empty_text(new_event_window.summary.session_id),
            log_context={
                "event_ids": event_ids if isinstance(event_ids, list) else [],
                "contradiction_hint_count": len(contradiction_hint_payload),
                "existing_record_count": len(existing_records),
            },
            scenario=LLMScenario.CORE,
            disable_thinking=False,
        )
        decision = str(payload.get("decision") or "").strip()
        if decision not in {"keep_new", "keep_existing", "mark_evolution"}:
            return None
        return L2ConflictArbitrationResult(
            decision=decision,
            winning_record_ids=[
                str(item) for item in payload.get("winning_record_ids", []) if str(item).strip()
            ],
            superseded_record_ids=[
                str(item) for item in payload.get("superseded_record_ids", []) if str(item).strip()
            ],
            reason=str(payload.get("reason") or "").strip(),
        )

    async def reconcile_entity_state(
        self,
        *,
        entity: L2ReconcileEntity,
        graph_facts: list[L2ReconcileGraphFact],
        assertions: list[L2ReconcileAssertion],
        recent_events: list[L2SourceEvent],
    ) -> list[ReconciledTraitOutcome]:
        payload = await self._generate_json(
            system_prompt=ENTITY_RECONCILE_SYSTEM_PROMPT,
            prompt=render_entity_reconcile_prompt(
                entity=entity,
                graph_facts=graph_facts,
                assertions=assertions,
                recent_events=recent_events,
            ),
            request_kind="memory:l2_entity_reconcile",
            turn_id=entity.entity_id,
        )
        outcomes = payload.get("reconciled_traits")
        if not isinstance(outcomes, list):
            return []
        normalized_outcomes: list[ReconciledTraitOutcome] = []
        for item in outcomes:
            if not isinstance(item, dict):
                continue
            try:
                normalized_outcomes.append(ReconciledTraitOutcome(**item))
            except Exception:
                continue
        return normalized_outcomes

    def _unresolved_resolution(self, *, confidence: float = 0.0) -> L2EntityResolution:
        return L2EntityResolution(
            confidence=float(confidence),
            reason_tags=["insufficient_evidence"],
        )

    def _non_empty_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


__all__ = ["L2LLMService"]
