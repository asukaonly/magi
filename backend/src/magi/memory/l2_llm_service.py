"""Thin LLM wrapper for L2 prompt execution and JSON-safe parsing."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from ..llm import LLMScenario, ScenarioLLMPool
from .l2_prompt_templates import (
    ENTITY_MENTION_SYSTEM_PROMPT,
    ENTITY_RESOLUTION_SYSTEM_PROMPT,
    TOM_EXTRACTION_SYSTEM_PROMPT,
    render_entity_mention_prompt,
    render_entity_resolution_prompt,
    render_tom_extraction_prompt,
)

logger = logging.getLogger(__name__)


class L2LLMService:
    """Executes L2 prompts with conservative failure handling."""

    def __init__(self, scenario_llm_pool: ScenarioLLMPool | None) -> None:
        self._scenario_llm_pool = scenario_llm_pool

    def render_entity_mention_prompt(self, *, event_text: str, context_texts: list[str]) -> str:
        return render_entity_mention_prompt(event_text=event_text, context_texts=context_texts)

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
