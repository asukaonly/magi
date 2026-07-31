"""Two-phase L2 extraction prompt execution."""

from __future__ import annotations

import time
from typing import Any

from ...core.logger import get_logger
from ...utils.diagnostic_logging import full_content_logging_enabled
from .models import L2EventWindow, L2Phase1Result, L2Phase2Result
from .llm_priority import l2_llm_priority_for_event_window
from .pipeline.claim_grounding import (
    normalize_phase1_claim_contract,
)
from .pipeline.evidence_packet import build_phase2_evidence_packet
from .pipeline.prompts import (
    PHASE1_EXTRACT_SYSTEM_PROMPT,
    build_phase2_integrate_system_prompt,
    render_phase1_extract_prompt,
    render_phase2_integrate_prompt,
)
from .storage.utils import single_event_confidence_cap

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
            priority=l2_llm_priority_for_event_window(event_window),
            required_fields={
                "entities": list,
                "fact_claims": list,
                "resolved_refs": list,
            },
            contract_normalizer=lambda response: normalize_phase1_claim_contract(
                response,
                event_window,
                context_messages=context_messages,
            ),
        )
        result = L2Phase1Result.from_dict(payload)
        is_single_event = len(event_window.event_ids) <= 1
        if is_single_event:
            cap = single_event_confidence_cap()
            for claim in result.fact_claims:
                claim.confidence = min(claim.confidence, cap)
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
        if full_content_logging_enabled():
            logger.info(
                "L2 Phase 1 candidate summary",
                event_ids=event_ids,
                entities=_summarize_phase1_entities(result),
                fact_claims=_summarize_phase1_fact_claims(result),
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
        phase2_instructions: str | None = None,
    ) -> L2Phase2Result:
        """Phase 2: infer higher-order assertions and assess non-obvious conflicts."""
        started_at = time.perf_counter()
        event_ids = list(event_window.event_ids)
        session_id = self._non_empty_text(event_window.summary.session_id)
        _log_phase2_started(
            event_ids=event_ids,
            phase1_result=phase1_result,
            existing_graph_edges=existing_graph_edges,
            existing_assertions=existing_assertions,
        )
        user_language = _phase2_user_language()
        prompt = _phase2_prompt(
            phase1_result=phase1_result,
            existing_graph_edges=existing_graph_edges,
            existing_assertions=existing_assertions,
            event_window=event_window,
            focal_subject=focal_subject,
            phase2_instructions=phase2_instructions,
        )
        payload = await self._generate_json(
            system_prompt=build_phase2_integrate_system_prompt(user_language or None),
            prompt=prompt,
            request_kind="memory:l2_phase2_integrate",
            turn_id=event_ids[0] if event_ids else None,
            session_id=session_id,
            log_context=_phase2_log_context(
                event_ids=event_ids,
                phase1_result=phase1_result,
                existing_graph_edges=existing_graph_edges,
                existing_assertions=existing_assertions,
                event_window=event_window,
            ),
            priority=l2_llm_priority_for_event_window(event_window),
            required_fields={
                "claim_assessments": list,
                "assertion_candidates": list,
            },
        )
        result = L2Phase2Result.from_dict(payload)
        _log_phase2_completed(
            started_at=started_at,
            event_ids=event_ids,
            result=result,
        )
        return result


def _log_phase2_started(
    *,
    event_ids: list[str],
    phase1_result: L2Phase1Result,
    existing_graph_edges: list[dict[str, Any]] | None,
    existing_assertions: list[dict[str, Any]] | None,
) -> None:
    logger.info(
        "L2 Phase 2 integration started",
        event_ids=event_ids,
        fact_claim_count=len(phase1_result.fact_claims),
        existing_edge_count=len(existing_graph_edges) if existing_graph_edges else 0,
        existing_assertion_count=len(existing_assertions) if existing_assertions else 0,
    )


def _phase2_user_language() -> str:
    from ...i18n import get_effective_language

    try:
        return get_effective_language(default="")
    except Exception:
        return ""


def _phase2_prompt(
    *,
    phase1_result: L2Phase1Result,
    existing_graph_edges: list[dict[str, Any]] | None,
    existing_assertions: list[dict[str, Any]] | None,
    event_window: L2EventWindow,
    focal_subject: dict[str, Any],
    phase2_instructions: str | None,
) -> str:
    evidence_packet = build_phase2_evidence_packet(
        phase1_result=phase1_result,
        existing_graph_edges=existing_graph_edges,
        existing_assertions=existing_assertions,
        event_window=event_window,
    )
    return render_phase2_integrate_prompt(
        phase1_result=phase1_result.to_dict(),
        focal_subject=focal_subject,
        source_integration_instructions=phase2_instructions,
        evidence_packet=evidence_packet,
    )


def _phase2_log_context(
    *,
    event_ids: list[str],
    phase1_result: L2Phase1Result,
    existing_graph_edges: list[dict[str, Any]] | None,
    existing_assertions: list[dict[str, Any]] | None,
    event_window: L2EventWindow,
) -> dict[str, Any]:
    return {
        "event_ids": event_ids,
        "fact_claim_count": len(phase1_result.fact_claims),
        "existing_edge_count": len(existing_graph_edges) if existing_graph_edges else 0,
        "existing_assertion_count": len(existing_assertions) if existing_assertions else 0,
        "history_context_count": len(event_window.history_contexts),
    }


def _log_phase2_completed(
    *,
    started_at: float,
    event_ids: list[str],
    result: L2Phase2Result,
) -> None:
    duration_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
    logger.info(
        "L2 Phase 2 inference completed",
        duration_ms=duration_ms,
        event_ids=event_ids,
        claim_assessment_count=len(result.claim_assessments),
        assertion_count=len(result.assertion_candidates),
    )
    if full_content_logging_enabled():
        logger.info(
            "L2 Phase 2 candidate summary",
            event_ids=event_ids,
            claim_assessments=_summarize_phase2_claim_assessments(result),
            assertion_candidates=_summarize_phase2_assertions(result),
        )


def _summarize_phase1_entities(result: L2Phase1Result) -> list[dict[str, Any]]:
    return [
        {
            "surface": entity.surface,
            "normalized_name": entity.normalized_name,
            "entity_type": entity.entity_type,
            "resolved_id": entity.resolved_id,
            "confidence": entity.confidence,
        }
        for entity in result.entities[:20]
    ]


def _summarize_phase1_fact_claims(result: L2Phase1Result) -> list[dict[str, Any]]:
    return [
        {
            "subject_ref": claim.subject_ref,
            "claim_id": claim.claim_id,
            "predicate": claim.predicate,
            "object_ref": claim.object_ref,
            "object_type": claim.object_type,
            "fact_kind": claim.fact_kind,
            "evidence_text": claim.evidence_text,
            "confidence": claim.confidence,
        }
        for claim in result.fact_claims[:20]
    ]


def _summarize_phase2_claim_assessments(result: L2Phase2Result) -> list[dict[str, Any]]:
    return [
        {
            "claim_id": assessment.claim_id,
            "relationship": assessment.relationship,
            "related_record_id": assessment.related_record_id,
        }
        for assessment in result.claim_assessments[:20]
    ]


def _summarize_phase2_assertions(result: L2Phase2Result) -> list[dict[str, Any]]:
    return [
        {
            "entity_ref": assertion.entity_ref,
            "trait_family": assertion.trait_family,
            "trait_name": assertion.trait_name,
            "trait_value": assertion.trait_value,
            "natural_summary": assertion.natural_summary,
            "supporting_claim_ids": assertion.supporting_claim_ids,
        }
        for assertion in result.assertion_candidates[:20]
    ]


__all__ = ["L2LLMExtractionMixin"]
