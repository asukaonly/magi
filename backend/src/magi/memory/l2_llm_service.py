"""Thin LLM wrapper for L2 prompt execution and JSON-safe parsing."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from ..llm import LLMScenario, ScenarioLLMPool
from .l2_extraction_profiles import ExtractionProfile
from .l2_prompt_templates import (
    CONTRADICTION_HINT_SYSTEM_PROMPT,
    ENTITY_RECONCILE_SYSTEM_PROMPT,
    ENTITY_MENTION_SYSTEM_PROMPT,
    ENTITY_RESOLUTION_SYSTEM_PROMPT,
    TOM_EXTRACTION_SYSTEM_PROMPT,
    UNIFIED_EXTRACTION_SYSTEM_PROMPT,
    render_contradiction_hint_prompt,
    render_entity_mention_prompt,
    render_entity_reconcile_prompt,
    render_entity_resolution_prompt,
    render_tom_extraction_prompt,
    render_unified_extraction_prompt,
)

logger = logging.getLogger(__name__)


class L2LLMService:
    """Executes L2 prompts with conservative failure handling."""

    def __init__(self, scenario_llm_pool: ScenarioLLMPool | None) -> None:
        self._scenario_llm_pool = scenario_llm_pool

    def render_entity_mention_prompt(self, *, event_text: str, context_texts: list[str]) -> str:
        return render_entity_mention_prompt(event_text=event_text, context_texts=context_texts)

    def render_unified_extraction_prompt(
        self,
        *,
        event_window: dict[str, Any],
        profile: ExtractionProfile,
        focal_subject: dict[str, Any],
    ) -> str:
        return render_unified_extraction_prompt(
            event_window=event_window,
            profile=profile,
            focal_subject=focal_subject,
        )

    async def extract_unified_candidates(
        self,
        *,
        event_window: dict[str, Any],
        profile: ExtractionProfile,
        focal_subject: dict[str, Any],
    ) -> dict[str, Any]:
        payload = await self._generate_json(
            system_prompt=UNIFIED_EXTRACTION_SYSTEM_PROMPT,
            prompt=self.render_unified_extraction_prompt(
                event_window=event_window,
                profile=profile,
                focal_subject=focal_subject,
            ),
        )
        mentions = payload.get("mentions")
        graph_candidates = payload.get("graph_candidates")
        assertion_candidates = payload.get("assertion_candidates")
        diagnostics = payload.get("diagnostics")

        normalized_mentions = [item for item in mentions if isinstance(item, dict)] if isinstance(mentions, list) else []
        normalized_graph_candidates = (
            [item for item in graph_candidates if isinstance(item, dict)] if isinstance(graph_candidates, list) else []
        )
        normalized_assertions: list[dict[str, Any]] = []
        event_ids = event_window.get("event_ids")
        is_single_event = isinstance(event_ids, list) and len(event_ids) <= 1
        if isinstance(assertion_candidates, list):
            for item in assertion_candidates:
                if not isinstance(item, dict):
                    continue
                candidate = dict(item)
                confidence = float(candidate.get("confidence", 0.0) or 0.0)
                if is_single_event:
                    confidence = min(confidence, 0.3)
                candidate["confidence"] = round(confidence, 4)
                normalized_assertions.append(candidate)

        normalized_diagnostics = diagnostics if isinstance(diagnostics, dict) else {"entity_status": "none"}
        if not normalized_diagnostics.get("entity_status"):
            normalized_diagnostics["entity_status"] = "none"

        return {
            "mentions": normalized_mentions,
            "graph_candidates": normalized_graph_candidates,
            "assertion_candidates": normalized_assertions,
            "diagnostics": normalized_diagnostics,
        }

    async def extract_entity_mentions(self, *, event_text: str, context_texts: list[str]) -> list[dict[str, Any]]:
        payload = await self._generate_json(
            system_prompt=ENTITY_MENTION_SYSTEM_PROMPT,
            prompt=self.render_entity_mention_prompt(event_text=event_text, context_texts=context_texts),
        )
        mentions = payload.get("mentions")
        return mentions if isinstance(mentions, list) else []

    async def resolve_entity(
        self,
        *,
        mention: dict[str, Any],
        candidate_entities: list[dict[str, Any]],
        min_confidence: float = 0.8,
    ) -> dict[str, Any]:
        payload = await self._generate_json(
            system_prompt=ENTITY_RESOLUTION_SYSTEM_PROMPT,
            prompt=render_entity_resolution_prompt(mention=mention, candidate_entities=candidate_entities),
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

        return {
            "decision": "match",
            "matched_entity_id": str(matched_entity_id),
            "matched_entity_name": resolution.get("matched_entity_name"),
            "confidence": confidence,
            "reason_tags": resolution.get("reason_tags", []),
            "should_merge": bool(resolution.get("should_merge", False)),
            "canonical_name_suggestion": resolution.get("canonical_name_suggestion"),
        }

    async def extract_tom_assertions(
        self,
        *,
        event_window: dict[str, Any],
        focal_entities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        payload = await self._generate_json(
            system_prompt=TOM_EXTRACTION_SYSTEM_PROMPT,
            prompt=render_tom_extraction_prompt(event_window=event_window, focal_entities=focal_entities),
        )
        assertions = payload.get("assertion_candidates")
        if not isinstance(assertions, list):
            return []

        normalized: list[dict[str, Any]] = []
        event_ids = event_window.get("event_ids")
        is_single_event = isinstance(event_ids, list) and len(event_ids) <= 1
        for item in assertions:
            if not isinstance(item, dict):
                continue
            candidate = dict(item)
            confidence = float(candidate.get("confidence", 0.0) or 0.0)
            if is_single_event:
                confidence = min(confidence, 0.3)
            candidate["confidence"] = round(confidence, 4)
            normalized.append(candidate)
        return normalized

    async def detect_contradiction_hints(
        self,
        *,
        new_event: dict[str, Any],
        existing_records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        payload = await self._generate_json(
            system_prompt=CONTRADICTION_HINT_SYSTEM_PROMPT,
            prompt=render_contradiction_hint_prompt(new_event=new_event, existing_records=existing_records),
        )
        hints = payload.get("contradiction_hints")
        return hints if isinstance(hints, list) else []

    async def reconcile_entity_state(
        self,
        *,
        entity: dict[str, Any],
        graph_facts: list[dict[str, Any]],
        assertions: list[dict[str, Any]],
        recent_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        payload = await self._generate_json(
            system_prompt=ENTITY_RECONCILE_SYSTEM_PROMPT,
            prompt=render_entity_reconcile_prompt(
                entity=entity,
                graph_facts=graph_facts,
                assertions=assertions,
                recent_events=recent_events,
            ),
        )
        outcomes = payload.get("reconciled_traits")
        return outcomes if isinstance(outcomes, list) else []

    async def _generate_json(self, *, system_prompt: str, prompt: str) -> dict[str, Any]:
        adapter = self._get_adapter()
        if adapter is None:
            return {}

        try:
            raw = await adapter.generate(
                prompt,
                system_prompt=system_prompt,
                temperature=0.0,
                json_mode=True,
            )
        except Exception as exc:
            logger.debug("L2 LLM generation failed: %s", exc)
            return {}

        try:
            parsed = json.loads(raw)
        except Exception:
            logger.debug("L2 LLM returned invalid JSON")
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _get_adapter(self) -> Optional[Any]:
        if self._scenario_llm_pool is None:
            return None
        try:
            return self._scenario_llm_pool.get(LLMScenario.CONTEXT_DECIDER)
        except Exception as exc:
            logger.debug("L2 LLM adapter unavailable: %s", exc)
            return None

    def _unresolved_resolution(self, *, confidence: float = 0.0) -> dict[str, Any]:
        return {
            "decision": "unresolved",
            "matched_entity_id": None,
            "matched_entity_name": None,
            "confidence": float(confidence),
            "reason_tags": ["insufficient_evidence"],
            "should_merge": False,
            "canonical_name_suggestion": None,
        }


__all__ = ["L2LLMService"]
