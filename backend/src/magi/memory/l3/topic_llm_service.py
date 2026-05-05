"""Rule-side helpers for thematic L3 topic summarization."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from ...i18n import llm_language_label
from ...llm import LLMProviderBridge, LLMScenario, ScenarioLLMPool
from .models import L3Candidate, ThematicEvidencePack, ThematicGenerationResult
from .topic_evidence import TopicEvidencePackMixin
from .topic_output import TopicOutputParsingMixin
from .topic_prompts import TOPIC_SUMMARY_OUTPUT_SCHEMA, TOPIC_SUMMARY_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def _target_language_instruction() -> str:
    target = llm_language_label(default="en")
    return (
        f"- Write user-facing generated fields in {target}: content and key_topics.\n"
        "- Preserve event ids, entity ids, URLs, file paths, source names, product names, song titles, and quoted user text as evidence presents them."
    )


class TopicSummaryLLMService(TopicEvidencePackMixin, TopicOutputParsingMixin):
    """Build topic evidence packs and support a fallback-safe LLM path."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        llm_timeout_seconds: float = 3.0,
        scenario_llm_pool: ScenarioLLMPool | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._llm_timeout_seconds = float(llm_timeout_seconds)
        self._scenario_llm_pool = scenario_llm_pool

    async def generate_topic_candidate(
        self,
        pack: ThematicEvidencePack,
        *,
        fallback_summary: str,
    ) -> ThematicGenerationResult:
        fallback = self._build_fallback_result(pack, fallback_summary)
        if not self._enabled:
            return fallback
        try:
            payload = await asyncio.wait_for(
                self._call_topic_model(pack),
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
        return ThematicGenerationResult(
            candidate=candidate,
            summary_overrides=summary_overrides,
            used_fallback=False,
        )

    async def _call_topic_model(self, pack: ThematicEvidencePack) -> dict[str, Any] | None:
        llm_target = self._get_llm_target()
        if llm_target is None:
            return None
        adapter, provider_bridge = llm_target
        prompt = self.render_topic_prompt(pack)
        started_at = time.perf_counter()
        provider = str(getattr(adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(adapter, "model_name", "unknown") or "unknown")
        log_context = {
            "request_kind": "memory:l3_thematic_topic_summary",
            "provider": provider,
            "model": model,
            "event_count": pack.source_event_count,
            "topic": pack.topic,
        }
        logger.info("L3 thematic topic LLM call started", extra=log_context)
        try:
            response = await provider_bridge.chat_response(
                system_prompt=TOPIC_SUMMARY_SYSTEM_PROMPT + "\nLanguage Rules:\n" + _target_language_instruction(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=True,
                disable_thinking=True,
                timeout_seconds=self._llm_timeout_seconds,
                event_context={
                    "request_kind": "memory:l3_thematic_topic_summary",
                    "turn_id": pack.source_event_ids[0] if pack.source_event_ids else None,
                    "agent_id": "memory:l3",
                },
            )
        except Exception as exc:
            logger.warning("L3 thematic topic LLM call failed", extra={**log_context, "error": str(exc)})
            raise

        raw = response.content
        logger.info(
            "L3 thematic topic LLM call completed",
            extra={
                **log_context,
                "duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
                "response_char_count": len(raw or ""),
            },
        )
        try:
            parsed = json.loads(raw)
        except Exception:
            logger.warning("L3 thematic topic LLM returned invalid JSON", extra=log_context)
            return None
        return parsed if isinstance(parsed, dict) else None

    def _build_fallback_result(
        self,
        pack: ThematicEvidencePack,
        fallback_summary: str,
    ) -> ThematicGenerationResult:
        candidate = L3Candidate(
            summary_type="thematic",
            summary_category="topic",
            content=str(fallback_summary).strip(),
            source_event_ids=list(pack.source_event_ids),
        )
        return ThematicGenerationResult(
            candidate=candidate,
            summary_overrides={
                "importance_aggregate": pack.importance_aggregate,
                "event_type_distribution": dict(pack.event_type_distribution),
            },
            used_fallback=True,
        )

    def render_topic_prompt(self, pack: ThematicEvidencePack) -> str:
        payload = {
            "summary_type": "thematic",
            "summary_category": "topic",
            "topic": pack.topic,
            "source_event_count": pack.source_event_count,
            "source_event_ids": pack.source_event_ids,
            "importance_aggregate": pack.importance_aggregate,
            "event_type_distribution": pack.event_type_distribution,
            "rule_hints": pack.rule_hints,
            "events": [
                {
                    "event_id": item.event_id,
                    "event_type": item.event_type,
                    "timestamp": item.timestamp,
                    "importance_score": item.importance_score,
                    "content": item.content,
                }
                for item in pack.events
            ],
        }
        schema = json.dumps(TOPIC_SUMMARY_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
        evidence = json.dumps(payload, ensure_ascii=False, indent=2)
        return (
            "Task:\n"
            "Write a thematic topic summary for the provided evidence pack.\n"
            "Use the rule_hints as guidance, not as independent evidence.\n"
            "Prioritize repeated concerns, decisions, and high-importance events.\n\n"
            "Output Requirements:\n"
            "- Return one JSON object only.\n"
            "- Keep content concise and evidence-grounded.\n"
            f"{_target_language_instruction()}\n"
            "- Use empty lists when a field has no support.\n\n"
            "Output JSON Schema:\n"
            f"{schema}\n\n"
            "Evidence Pack:\n"
            f"{evidence}\n"
        )

    def _get_adapter(self) -> Any | None:
        if self._scenario_llm_pool is None:
            return None
        try:
            return self._scenario_llm_pool.get(LLMScenario.MEMORY_SUMMARIZER)
        except Exception as exc:
            logger.debug("L3 thematic topic LLM adapter unavailable: %s", exc)
            return None

    def _get_llm_target(self) -> tuple[Any, LLMProviderBridge] | None:
        adapter = self._get_adapter()
        if adapter is None:
            return None
        return adapter, LLMProviderBridge(adapter)


__all__ = [
    "TOPIC_SUMMARY_OUTPUT_SCHEMA",
    "TOPIC_SUMMARY_SYSTEM_PROMPT",
    "TopicSummaryLLMService",
]
