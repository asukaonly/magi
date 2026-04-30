"""Two-phase L2 extraction prompt execution."""

from __future__ import annotations

import time
from typing import Any

from ...core.logger import get_logger
from .models import L2EventWindow, L2Phase1Result, L2Phase2Result
from .pipeline.prompts import (
    PHASE1_EXTRACT_SYSTEM_PROMPT,
    PHASE2_INTEGRATE_SYSTEM_PROMPT,
    render_phase1_extract_prompt,
    render_phase2_integrate_prompt,
)

logger = get_logger(__name__)


class L2LLMExtractionMixin:
    """Execute the L2 phase 1 and phase 2 extraction prompts."""

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


__all__ = ["L2LLMExtractionMixin"]
