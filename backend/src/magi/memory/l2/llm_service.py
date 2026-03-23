"""Thin LLM wrapper for L2 prompt execution and JSON-safe parsing."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional

from ...core.logger import get_logger
from ...llm import LLMProviderBridge, LLMScenario, ProviderResponse, ScenarioLLMPool
from .context_bundle import ContextBundle
from .extraction_profiles import ExtractionProfile
from .models import (
    ContradictionHint,
    L2AssertionCandidate,
    L2CandidateSet,
    L2ConflictArbitrationResult,
    L2EntityResolution,
    L2ExistingRecord,
    L2SourceEvent,
    L2EventWindow,
    L2GraphCandidate,
    L2UnifiedExtractionResult,
)
from .prompts import (
    CONFLICT_ARBITRATION_SYSTEM_PROMPT,
    CONTRADICTION_HINT_SYSTEM_PROMPT,
    ENTITY_RECONCILE_SYSTEM_PROMPT,
    ENTITY_RESOLUTION_SYSTEM_PROMPT,
    UNIFIED_EXTRACTION_SYSTEM_PROMPT,
    render_conflict_arbitration_prompt,
    render_contradiction_hint_prompt,
    render_entity_reconcile_prompt,
    render_entity_resolution_prompt,
    render_unified_extraction_prompt,
)

logger = get_logger(__name__)
_RATE_LIMIT_BACKOFF_SECONDS = (1.0, 2.0, 4.0)


class L2LLMService:
    """Executes L2 prompts with conservative failure handling."""

    def __init__(self, scenario_llm_pool: ScenarioLLMPool | None) -> None:
        self._scenario_llm_pool = scenario_llm_pool

    def render_unified_extraction_prompt(
        self,
        *,
        event_window: L2EventWindow,
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
        event_window: L2EventWindow,
        profile: ExtractionProfile,
        focal_subject: dict[str, Any],
        context_bundle: ContextBundle | None = None,
    ) -> L2UnifiedExtractionResult:
        started_at = time.perf_counter()
        event_ids = list(event_window.event_ids)
        batch_event_count = len(event_window.events)
        session_id = self._non_empty_text(event_window.summary.session_id)
        user_id = self._non_empty_text(event_window.summary.user_id)
        logger.info(
            "L2 unified extraction started",
            event_ids=event_ids,
            profile_id=profile.profile_id,
            batch_event_count=batch_event_count or len(event_ids),
            text_count=len(event_window.texts),
            context_count=len(event_window.context_texts),
            session_id=session_id,
            user_id=user_id,
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
            session_id=session_id,
            log_context={
                "event_ids": event_ids,
                "profile_id": profile.profile_id,
                "batch_event_count": batch_event_count or len(event_ids),
                "session_id": session_id,
                "user_id": user_id,
            },
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
        normalized_graph_candidates: list[L2GraphCandidate] = []
        if isinstance(graph_candidates, list):
            for item in graph_candidates:
                if not isinstance(item, dict):
                    continue
                normalized_graph_candidates.append(L2GraphCandidate.from_dict(item))
        normalized_assertions: list[L2AssertionCandidate] = []
        is_single_event = len(event_window.event_ids) <= 1
        if isinstance(assertion_candidates, list):
            for item in assertion_candidates:
                if not isinstance(item, dict):
                    continue
                candidate = dict(item)
                confidence = float(candidate.get("confidence", 0.0) or 0.0)
                if is_single_event:
                    confidence = min(confidence, 0.3)
                candidate["confidence"] = round(confidence, 4)
                normalized_assertions.append(L2AssertionCandidate.from_dict(candidate))

        result = L2UnifiedExtractionResult(
            mentions=normalized_mentions,
            resolved_context_refs=normalized_resolved_context_refs,
            graph_candidates=normalized_graph_candidates,
            assertion_candidates=normalized_assertions,
            diagnostics=diagnostics if isinstance(diagnostics, dict) else {"entity_status": "none"},
        )
        duration_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        logger.info(
            "L2 unified extraction completed",
            duration_ms=duration_ms,
            event_ids=event_ids,
            profile_id=profile.profile_id,
            batch_event_count=batch_event_count or len(event_ids),
            mention_count=len(normalized_mentions),
            resolved_context_ref_count=len(normalized_resolved_context_refs),
            graph_candidate_count=len(normalized_graph_candidates),
            assertion_candidate_count=len(normalized_assertions),
            session_id=session_id,
            user_id=user_id,
        )
        return result

    async def resolve_entity(
        self,
        *,
        mention: dict[str, Any],
        candidate_entities: list[dict[str, Any]],
        min_confidence: float = 0.8,
    ) -> L2EntityResolution:
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

        return L2EntityResolution(
            decision="match",
            matched_entity_id=str(matched_entity_id),
            matched_entity_name=resolution.get("matched_entity_name"),
            confidence=confidence,
            reason_tags=resolution.get("reason_tags", []),
            should_merge=bool(resolution.get("should_merge", False)),
            canonical_name_suggestion=resolution.get("canonical_name_suggestion"),
        )

    async def detect_contradiction_hints(
        self,
        *,
        new_event: dict[str, Any],
        existing_records: list[L2ExistingRecord],
    ) -> list[ContradictionHint]:
        payload = await self._generate_json(
            system_prompt=CONTRADICTION_HINT_SYSTEM_PROMPT,
            prompt=render_contradiction_hint_prompt(new_event=new_event, existing_records=existing_records),
            request_kind="memory:l2_contradiction_hint",
            turn_id=str(new_event.get("event_id") or "") or None,
        )
        hints = payload.get("contradiction_hints")
        if not isinstance(hints, list):
            return []
        normalized_hints: list[ContradictionHint] = []
        for hint in hints:
            if not isinstance(hint, dict):
                continue
            target_record_id = str(hint.get("target_record_id") or "").strip()
            target_record_type = str(hint.get("target_record_type") or "").strip()
            contradiction_kind = str(hint.get("contradiction_kind") or "").strip()
            evidence_text = str(hint.get("evidence_text") or "").strip()
            recommended_action = str(hint.get("recommended_action") or "").strip()
            if not all((target_record_id, target_record_type, contradiction_kind, recommended_action)):
                continue
            normalized_hints.append(
                ContradictionHint(
                    target_record_id=target_record_id,
                    target_record_type=target_record_type,
                    contradiction_kind=contradiction_kind,
                    confidence=float(hint.get("confidence", 0.0) or 0.0),
                    evidence_text=evidence_text,
                    recommended_action=recommended_action,
                )
            )
        return normalized_hints

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
            winning_record_ids=[str(item) for item in payload.get("winning_record_ids", []) if str(item).strip()],
            superseded_record_ids=[
                str(item) for item in payload.get("superseded_record_ids", []) if str(item).strip()
            ],
            reason=str(payload.get("reason") or "").strip(),
        )

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
        scenario: LLMScenario = LLMScenario.CONTEXT_DECIDER,
        disable_thinking: bool = True,
    ) -> dict[str, Any]:
        llm_target = self._get_llm_target(scenario=scenario)
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
                "disable_thinking": disable_thinking,
                "json_mode": True,
                "prompt_char_count": len(prompt),
                "system_prompt_char_count": len(system_prompt),
            }
        )

        started_at = time.perf_counter()

        response = None
        max_output_tokens = self._resolve_max_output_tokens(scenario=scenario)
        for attempt_index in range(len(_RATE_LIMIT_BACKOFF_SECONDS) + 1):
            try:
                response = await provider_bridge.chat_response(
                    system_prompt=system_prompt,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_output_tokens,
                    temperature=0.0,
                    json_mode=True,
                    disable_thinking=disable_thinking,
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
                    logger.warning("L2 LLM rate limited", **failure_context)
                    logger.info("L2 LLM retry scheduled", **failure_context)
                    await asyncio.sleep(backoff_seconds)
                    continue
                logger.warning("L2 LLM call failed", **failure_context)
                return {}

        if response is None:
            return {}

        raw = response.content
        completion_context = dict(context)
        completion_context.update(self._usage_log_fields(response))
        completion_context["duration_ms"] = round((time.perf_counter() - started_at) * 1000.0, 2)
        logger.info("L2 LLM call completed", **completion_context)

        try:
            parsed = json.loads(raw)
        except Exception:
            invalid_context = dict(completion_context)
            invalid_context["response_char_count"] = len(raw or "")
            logger.warning("L2 LLM returned invalid JSON", **invalid_context)
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

    def _get_adapter(self, scenario: LLMScenario = LLMScenario.CONTEXT_DECIDER) -> Optional[Any]:
        if self._scenario_llm_pool is None:
            return None
        try:
            return self._scenario_llm_pool.get(scenario)
        except Exception as exc:
            logger.debug("L2 LLM adapter unavailable", error=str(exc), scenario=scenario.value)
            return None

    def _get_llm_target(self, *, scenario: LLMScenario = LLMScenario.CONTEXT_DECIDER) -> Optional[tuple[Any, LLMProviderBridge]]:
        adapter = self._get_adapter(scenario=scenario)
        if adapter is None:
            return None
        return adapter, LLMProviderBridge(adapter)

    def _resolve_max_output_tokens(self, *, scenario: LLMScenario) -> int:
        default_limit = 1024
        pool = self._scenario_llm_pool
        if pool is None:
            return default_limit

        selection = None
        get_selection = getattr(pool, "get_selection", None)
        if callable(get_selection):
            try:
                selection = get_selection(scenario)
            except Exception:
                selection = None
        if selection is None:
            config = getattr(pool, "_config", None)
            llm_config = getattr(config, "llm", None)
            selections = getattr(llm_config, "selections", None)
            if isinstance(selections, dict):
                selection = selections.get(scenario.value)

        limits = getattr(selection, "limits", None)
        max_output_tokens = getattr(limits, "max_output_tokens", None)
        try:
            resolved = int(max_output_tokens)
        except (TypeError, ValueError):
            return default_limit
        return resolved if resolved > 0 else default_limit

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
