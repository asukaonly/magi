"""Rule-side helpers for temporal L3 LLM summarization."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from ...llm import LLMProviderBridge, LLMScenario, ScenarioLLMPool
from .models import L3Candidate, TemporalEvidencePack, TemporalGenerationResult
from .temporal_evidence import TemporalEvidencePackMixin
from .temporal_output import TemporalOutputParsingMixin
from .temporal_prompts import TEMPORAL_SUMMARY_OUTPUT_SCHEMA, TEMPORAL_SUMMARY_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class TemporalSummaryLLMService(TemporalEvidencePackMixin, TemporalOutputParsingMixin):
    """Build evidence packs, call the LLM, and parse temporal summaries."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        llm_timeout_seconds: float = 3.0,
        min_event_count_for_llm: int = 2,
        scenario_llm_pool: ScenarioLLMPool | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._llm_timeout_seconds = float(llm_timeout_seconds)
        self._min_event_count_for_llm = max(1, int(min_event_count_for_llm))
        self._scenario_llm_pool = scenario_llm_pool

    async def generate_temporal_candidate(
        self,
        pack: TemporalEvidencePack,
        *,
        fallback_summary: str,
    ) -> TemporalGenerationResult:
        """Try the model path and fall back to a rule summary on failure."""
        fallback = self._build_fallback_result(pack, fallback_summary)
        if not self._enabled:
            return fallback
        if pack.source_event_count < self._min_event_count_for_llm:
            return fallback
        try:
            payload = await asyncio.wait_for(
                self._call_temporal_model(pack),
                timeout=self._llm_timeout_seconds,
            )
        except Exception:
            return fallback
        if not isinstance(payload, dict):
            return fallback
        try:
            candidate, summary_overrides = self.parse_llm_output(payload, pack=pack)
        except Exception:
            return fallback
        return TemporalGenerationResult(
            candidate=candidate,
            summary_overrides=summary_overrides,
            used_fallback=False,
        )

    async def _call_temporal_model(self, pack: TemporalEvidencePack) -> dict[str, Any] | None:
        """Call the configured LLM adapter for temporal summary generation."""
        llm_target = self._get_llm_target()
        if llm_target is None:
            return None
        adapter, provider_bridge = llm_target
        prompt = self._render_temporal_summary_prompt(pack)
        system_prompt = TEMPORAL_SUMMARY_SYSTEM_PROMPT
        started_at = time.perf_counter()
        provider = str(getattr(adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(adapter, "model_name", "unknown") or "unknown")
        log_context = {
            "request_kind": "memory:l3_temporal_summary",
            "provider": provider,
            "model": model,
            "event_count": pack.source_event_count,
            "summary_category": pack.summary_category,
        }
        logger.info("L3 temporal LLM call started", extra=log_context)
        try:
            response = await provider_bridge.chat_response(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=True,
                disable_thinking=True,
                timeout_seconds=self._llm_timeout_seconds,
                event_context={
                    "request_kind": "memory:l3_temporal_summary",
                    "turn_id": pack.source_event_ids[0] if pack.source_event_ids else None,
                    "agent_id": "memory:l3",
                },
            )
        except Exception as exc:
            logger.warning("L3 temporal LLM call failed", extra={**log_context, "error": str(exc)})
            raise

        raw = response.content
        logger.info(
            "L3 temporal LLM call completed",
            extra={
                **log_context,
                "duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
                "response_char_count": len(raw or ""),
            },
        )
        try:
            parsed = json.loads(raw)
        except Exception:
            logger.warning("L3 temporal LLM returned invalid JSON", extra=log_context)
            return None
        return parsed if isinstance(parsed, dict) else None

    def _build_fallback_result(
        self,
        pack: TemporalEvidencePack,
        fallback_summary: str,
    ) -> TemporalGenerationResult:
        candidate = L3Candidate(
            summary_type="temporal",
            summary_category=pack.summary_category,
            content=str(fallback_summary).strip(),
            source_event_ids=list(pack.source_event_ids),
        )
        summary_overrides: dict[str, object] = {
            "importance_aggregate": pack.importance_aggregate,
            "event_type_distribution": dict(pack.event_type_distribution),
        }
        feature_lines: list[str] = []
        for feature in pack.plugin_summary_features.values():
            if not isinstance(feature, dict):
                continue
            raw_lines = feature.get("summary_lines")
            if not isinstance(raw_lines, list):
                continue
            for item in raw_lines:
                line = str(item).strip()
                if line and line not in feature_lines:
                    feature_lines.append(line)
        if feature_lines:
            stitched = [str(fallback_summary).strip(), *feature_lines]
            candidate.content = "\n".join(part for part in stitched if part).strip()
            summary_overrides["plugin_summary_features"] = dict(pack.plugin_summary_features)
        return TemporalGenerationResult(
            candidate=candidate,
            summary_overrides=summary_overrides,
            used_fallback=True,
        )

    def _render_temporal_summary_prompt(self, pack: TemporalEvidencePack) -> str:
        payload = {
            "summary_type": "temporal",
            "summary_category": pack.summary_category,
            "period_start": pack.period_start,
            "period_end": pack.period_end,
            "window_event_count": pack.window_event_count if pack.window_event_count is not None else pack.source_event_count,
            "source_event_count": pack.source_event_count,
            "omitted_event_count": pack.omitted_event_count,
            "source_event_ids": pack.source_event_ids,
            "importance_aggregate": pack.importance_aggregate,
            "event_type_distribution": pack.event_type_distribution,
            "rule_hints": pack.rule_hints,
            "plugin_summary_features": pack.plugin_summary_features,
            "source_distribution": pack.source_distribution,
            "selection_policy": pack.selection_policy,
            "events": [
                {
                    "event_id": item.event_id,
                    "event_type": item.event_type,
                    "timestamp": item.timestamp,
                    "memory_domain": item.memory_domain,
                    "importance_score": item.importance_score,
                    "content": item.content,
                }
                for item in pack.events
            ],
        }
        schema = json.dumps(TEMPORAL_SUMMARY_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
        evidence = json.dumps(payload, ensure_ascii=False, indent=2)
        return (
            "Task:\n"
            "Write a temporal summary for the provided memory window.\n"
            "Use the rule_hints as guidance, not as independent evidence.\n"
            "When plugin_summary_features are present, use them to surface source-specific behavior patterns such as concentration, revisits, and session structure.\n"
            "Use source_distribution, window_event_count, and omitted_event_count to understand coverage and avoid treating representative events as exhaustive.\n"
            "Prioritize explicit changes, recurring constraints, and high-importance events.\n\n"
            "Output Requirements:\n"
            "- Return one JSON object only.\n"
            "- Keep content concise and evidence-grounded.\n"
            "- Use empty lists or nulls when a field has no support.\n\n"
            "Output JSON Schema:\n"
            f"{schema}\n\n"
            "Evidence Pack:\n"
            f"{evidence}\n"
        )

    def _get_adapter(self) -> Any | None:
        if self._scenario_llm_pool is None:
            return None
        try:
            return self._scenario_llm_pool.get(LLMScenario.CONTEXT_DECIDER)
        except Exception as exc:
            logger.debug("L3 temporal LLM adapter unavailable: %s", exc)
            return None

    def _get_llm_target(self) -> tuple[Any, LLMProviderBridge] | None:
        adapter = self._get_adapter()
        if adapter is None:
            return None
        return adapter, LLMProviderBridge(adapter)


__all__ = [
    "TEMPORAL_SUMMARY_OUTPUT_SCHEMA",
    "TEMPORAL_SUMMARY_SYSTEM_PROMPT",
    "TemporalSummaryLLMService",
]
