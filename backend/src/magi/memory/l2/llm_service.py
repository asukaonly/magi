"""Thin LLM wrapper for L2 prompt execution and JSON-safe parsing."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from ...llm import LLMProviderBridge, LLMScenario, ProviderResponse, ScenarioLLMPool
from .context_bundle import ContextBundle
from .extraction_profiles import ExtractionProfile
from .prompts import (
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
_RATE_LIMIT_BACKOFF_SECONDS = (1.0, 2.0, 4.0)


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
        context_bundle: ContextBundle | None = None,
    ) -> str:
        return render_unified_extraction_prompt(
            event_window=event_window,
            profile=profile,
            focal_subject=focal_subject,
            context_bundle=context_bundle,
        )

    async def extract_unified_candidates(
        self,
        *,
        event_window: dict[str, Any],
        profile: ExtractionProfile,
        focal_subject: dict[str, Any],
        context_bundle: ContextBundle | None = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        event_ids = event_window.get("event_ids") if isinstance(event_window.get("event_ids"), list) else []
        logger.info(
            "L2 unified extraction started",
            extra={
                "event_ids": event_ids,
                "profile_id": profile.profile_id,
                "text_count": len(event_window.get("texts", [])) if isinstance(event_window.get("texts"), list) else 0,
                "context_count": (
                    len(event_window.get("context_texts", []))
                    if isinstance(event_window.get("context_texts"), list)
                    else 0
                ),
            },
        )
        payload = await self._generate_json(
            system_prompt=UNIFIED_EXTRACTION_SYSTEM_PROMPT,
            prompt=self.render_unified_extraction_prompt(
                event_window=event_window,
                profile=profile,
                focal_subject=focal_subject,
                context_bundle=context_bundle,
            ),
            request_kind="memory:l2_unified_extraction",
            turn_id=event_ids[0] if event_ids else None,
            log_context={"event_ids": event_ids, "profile_id": profile.profile_id},
        )
        mentions = payload.get("mentions")
        resolved_context_refs = payload.get("resolved_context_refs")
        graph_candidates = payload.get("graph_candidates")
        assertion_candidates = payload.get("assertion_candidates")
        diagnostics = payload.get("diagnostics")

        normalized_mentions = [item for item in mentions if isinstance(item, dict)] if isinstance(mentions, list) else []
        normalized_resolved_context_refs = (
            [item for item in resolved_context_refs if isinstance(item, dict)]
            if isinstance(resolved_context_refs, list)
            else []
        )
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

        result = {
            "mentions": normalized_mentions,
            "resolved_context_refs": normalized_resolved_context_refs,
            "graph_candidates": normalized_graph_candidates,
            "assertion_candidates": normalized_assertions,
            "diagnostics": normalized_diagnostics,
        }
        duration_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        logger.info(
            "L2 unified extraction completed",
            extra={
                "duration_ms": duration_ms,
                "event_ids": event_ids,
                "profile_id": profile.profile_id,
                "mention_count": len(normalized_mentions),
                "resolved_context_ref_count": len(normalized_resolved_context_refs),
                "graph_candidate_count": len(normalized_graph_candidates),
                "assertion_candidate_count": len(normalized_assertions),
            },
        )
        return result

    async def extract_entity_mentions(self, *, event_text: str, context_texts: list[str]) -> list[dict[str, Any]]:
        payload = await self._generate_json(
            system_prompt=ENTITY_MENTION_SYSTEM_PROMPT,
            prompt=self.render_entity_mention_prompt(event_text=event_text, context_texts=context_texts),
            request_kind="memory:l2_entity_mentions",
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
        event_ids = event_window.get("event_ids")
        payload = await self._generate_json(
            system_prompt=TOM_EXTRACTION_SYSTEM_PROMPT,
            prompt=render_tom_extraction_prompt(event_window=event_window, focal_entities=focal_entities),
            request_kind="memory:l2_tom_extraction",
            turn_id=event_ids[0] if isinstance(event_ids, list) and event_ids else None,
        )
        assertions = payload.get("assertion_candidates")
        if not isinstance(assertions, list):
            return []

        normalized: list[dict[str, Any]] = []
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
            request_kind="memory:l2_contradiction_hint",
            turn_id=str(new_event.get("event_id") or "") or None,
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
            request_kind="memory:l2_entity_reconcile",
            turn_id=str(entity.get("entity_id") or "") or None,
        )
        outcomes = payload.get("reconciled_traits")
        return outcomes if isinstance(outcomes, list) else []

    async def _generate_json(
        self,
        *,
        system_prompt: str,
        prompt: str,
        request_kind: str,
        turn_id: str | None = None,
        session_id: str | None = None,
        log_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        llm_target = self._get_llm_target()
        if llm_target is None:
            return {}
        adapter, provider_bridge = llm_target
        provider = str(getattr(adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(adapter, "model_name", "unknown") or "unknown")
        context = dict(log_context or {})
        context.update(
            {
                "request_kind": request_kind,
                "provider": provider,
                "model": model,
                "disable_thinking": True,
                "json_mode": True,
                "prompt_char_count": len(prompt),
                "system_prompt_char_count": len(system_prompt),
            }
        )
        logger.info("L2 LLM call started", extra=context)

        started_at = time.perf_counter()

        response = None
        for attempt_index in range(len(_RATE_LIMIT_BACKOFF_SECONDS) + 1):
            try:
                response = await provider_bridge.chat_response(
                    system_prompt=system_prompt,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    json_mode=True,
                    disable_thinking=True,
                    event_context={
                        "request_kind": request_kind,
                        "turn_id": turn_id,
                        "session_id": session_id,
                        "agent_id": "memory:l2",
                    },
                )
                break
            except Exception as exc:
                is_rate_limited = self._is_rate_limit_error(exc)
                failure_context = dict(context)
                failure_context["duration_ms"] = round((time.perf_counter() - started_at) * 1000.0, 2)
                failure_context["error"] = str(exc)
                failure_context["attempt_index"] = attempt_index + 1
                if is_rate_limited and attempt_index < len(_RATE_LIMIT_BACKOFF_SECONDS):
                    backoff_seconds = _RATE_LIMIT_BACKOFF_SECONDS[attempt_index]
                    failure_context["backoff_seconds"] = backoff_seconds
                    logger.warning("L2 LLM rate limited", extra=failure_context)
                    logger.info("L2 LLM retry scheduled", extra=failure_context)
                    await asyncio.sleep(backoff_seconds)
                    continue
                logger.warning("L2 LLM call failed", extra=failure_context)
                return {}

        if response is None:
            return {}

        raw = response.content
        completion_context = dict(context)
        completion_context.update(self._usage_log_fields(response))
        completion_context["duration_ms"] = round((time.perf_counter() - started_at) * 1000.0, 2)
        logger.info("L2 LLM call completed", extra=completion_context)

        try:
            parsed = json.loads(raw)
        except Exception:
            invalid_context = dict(completion_context)
            invalid_context["response_char_count"] = len(raw or "")
            logger.warning("L2 LLM returned invalid JSON", extra=invalid_context)
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _is_rate_limit_error(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code == 429:
            return True
        response = getattr(exc, "response", None)
        if getattr(response, "status_code", None) == 429:
            return True
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "429",
                "rate limit",
                "ratelimit",
                "too many requests",
            )
        )

    def _get_adapter(self) -> Optional[Any]:
        if self._scenario_llm_pool is None:
            return None
        try:
            return self._scenario_llm_pool.get(LLMScenario.CONTEXT_DECIDER)
        except Exception as exc:
            logger.debug("L2 LLM adapter unavailable: %s", exc)
            return None

    def _get_llm_target(self) -> Optional[tuple[Any, LLMProviderBridge]]:
        adapter = self._get_adapter()
        if adapter is None:
            return None
        return adapter, LLMProviderBridge(adapter)

    def _usage_log_fields(self, response: ProviderResponse) -> dict[str, Any]:
        usage = response.usage
        if usage is None:
            return {
                "usage_available": False,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
        return {
            "usage_available": True,
            "prompt_tokens": int(usage.prompt_tokens or 0),
            "completion_tokens": int(usage.completion_tokens or 0),
            "total_tokens": int(usage.total_tokens or 0),
        }

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
