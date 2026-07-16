"""Rule-side helpers for thematic L3 topic summarization."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from ...i18n import llm_language_label
from ...llm import LLMProviderBridge, LLMRequestPriority, LLMScenario, ScenarioLLMPool
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
            prose_content = await asyncio.wait_for(
                self._call_topic_prose_model(pack),
                timeout=self._llm_timeout_seconds,
            )
        except Exception:
            return fallback
        prose_content = str(prose_content or "").strip()
        if not prose_content:
            return fallback

        candidate = L3Candidate(
            summary_type="thematic",
            summary_category="topic",
            content=prose_content,
            source_event_ids=list(pack.source_event_ids),
        )
        summary_overrides: dict[str, object] = {
            "key_topics": [],
            "key_entities": [],
        }
        try:
            payload = await asyncio.wait_for(
                self._call_topic_structure_model(pack, prose_content=prose_content),
                timeout=self._llm_timeout_seconds,
            )
        except Exception:
            payload = None
        if isinstance(payload, dict):
            try:
                summary_overrides.update(
                    self.parse_structure_output(payload, pack=pack, content=prose_content)
                )
            except Exception as exc:
                logger.warning(
                    "L3 thematic topic structure output rejected",
                    extra={
                        "topic": pack.topic,
                        "event_count": pack.source_event_count,
                        "error": str(exc),
                    },
                )
        return ThematicGenerationResult(
            candidate=candidate,
            summary_overrides=summary_overrides,
            used_fallback=False,
        )

    async def _call_topic_prose_model(self, pack: ThematicEvidencePack) -> str | None:
        llm_target = self._get_llm_target()
        if llm_target is None:
            return None
        adapter, provider_bridge = llm_target
        prompt = self.render_topic_prose_prompt(pack)
        started_at = time.perf_counter()
        provider = str(getattr(adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(adapter, "model_name", "unknown") or "unknown")
        log_context = {
            "request_kind": "memory:l3_thematic_topic_summary_prose",
            "provider": provider,
            "model": model,
            "event_count": pack.source_event_count,
            "topic": pack.topic,
        }
        logger.info("L3 thematic topic prose LLM call started", extra=log_context)
        try:
            response = await provider_bridge.chat_response(
                system_prompt=TOPIC_SUMMARY_SYSTEM_PROMPT
                + "\nLanguage Rules:\n"
                + _target_language_instruction(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=False,
                disable_thinking=True,
                cache_system=True,
                timeout_seconds=self._llm_timeout_seconds,
                event_context={
                    "request_kind": "memory:l3_thematic_topic_summary_prose",
                    "turn_id": pack.source_event_ids[0] if pack.source_event_ids else None,
                    "agent_id": "memory:l3",
                },
                priority=LLMRequestPriority.LOW,
            )
        except Exception as exc:
            logger.warning(
                "L3 thematic topic prose LLM call failed", extra={**log_context, "error": str(exc)}
            )
            raise

        raw = str(response.content or "").strip()
        logger.info(
            "L3 thematic topic prose LLM call completed",
            extra={
                **log_context,
                "duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
                "response_char_count": len(raw),
            },
        )
        return raw or None

    async def _call_topic_structure_model(
        self,
        pack: ThematicEvidencePack,
        *,
        prose_content: str,
    ) -> dict[str, Any] | None:
        llm_target = self._get_llm_target()
        if llm_target is None:
            return None
        adapter, provider_bridge = llm_target
        prompt = self.render_topic_structure_prompt(pack, prose_content=prose_content)
        started_at = time.perf_counter()
        provider = str(getattr(adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(adapter, "model_name", "unknown") or "unknown")
        log_context = {
            "request_kind": "memory:l3_thematic_topic_summary_structure",
            "provider": provider,
            "model": model,
            "event_count": pack.source_event_count,
            "topic": pack.topic,
        }
        logger.info("L3 thematic topic structure LLM call started", extra=log_context)
        try:
            response = await provider_bridge.chat_response(
                system_prompt=TOPIC_SUMMARY_SYSTEM_PROMPT
                + "\nLanguage Rules:\n"
                + _target_language_instruction(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=True,
                disable_thinking=True,
                cache_system=True,
                timeout_seconds=self._llm_timeout_seconds,
                event_context={
                    "request_kind": "memory:l3_thematic_topic_summary_structure",
                    "turn_id": pack.source_event_ids[0] if pack.source_event_ids else None,
                    "agent_id": "memory:l3",
                },
                priority=LLMRequestPriority.LOW,
            )
        except Exception as exc:
            logger.warning(
                "L3 thematic topic structure LLM call failed",
                extra={**log_context, "error": str(exc)},
            )
            raise

        raw = str(response.content or "").strip()
        logger.info(
            "L3 thematic topic structure LLM call completed",
            extra={
                **log_context,
                "duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
                "response_char_count": len(raw),
            },
        )
        try:
            parsed = json.loads(raw)
        except Exception:
            logger.warning(
                "L3 thematic topic structure LLM returned invalid JSON", extra=log_context
            )
            return None
        return parsed if isinstance(parsed, dict) else None

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
                system_prompt=TOPIC_SUMMARY_SYSTEM_PROMPT
                + "\nLanguage Rules:\n"
                + _target_language_instruction(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=True,
                disable_thinking=True,
                cache_system=True,  # constant + per-language system prompt
                timeout_seconds=self._llm_timeout_seconds,
                event_context={
                    "request_kind": "memory:l3_thematic_topic_summary",
                    "turn_id": pack.source_event_ids[0] if pack.source_event_ids else None,
                    "agent_id": "memory:l3",
                },
                priority=LLMRequestPriority.LOW,
            )
        except Exception as exc:
            logger.warning(
                "L3 thematic topic LLM call failed", extra={**log_context, "error": str(exc)}
            )
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

    def _topic_prompt_payload(self, pack: ThematicEvidencePack) -> dict[str, object]:
        return {
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
                    "interpretation_context": item.interpretation_context,
                }
                for item in pack.events
            ],
        }

    def render_topic_context_prompt(self, pack: ThematicEvidencePack) -> str:
        evidence = json.dumps(self._topic_prompt_payload(pack), ensure_ascii=False, indent=2)
        return (
            "Shared Context:\n"
            "You are working on one thematic memory summary for the provided topic evidence pack.\n"
            "Use the rule_hints as guidance, not as independent evidence.\n"
            "An event's interpretation_context only explains how to read its content. The product-authored question is not evidence and must never be presented as something the user said, believed, or experienced.\n"
            "Prioritize repeated concerns, decisions, and high-importance events.\n\n"
            "Language Rules:\n"
            f"{_target_language_instruction()}\n\n"
            "Evidence Pack:\n"
            f"{evidence}\n"
        )

    def render_topic_prose_prompt(self, pack: ThematicEvidencePack) -> str:
        return (
            self.render_topic_context_prompt(pack) + "\nGeneration Task / 生成用户可读正文:\n"
            "- Write only the user-facing topic summary body.\n"
            "- Do not return JSON.\n"
            "- Keep content concise and evidence-grounded.\n"
        )

    def render_topic_structure_prompt(
        self,
        pack: ThematicEvidencePack,
        *,
        prose_content: str,
    ) -> str:
        schema = json.dumps(TOPIC_SUMMARY_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
        return (
            self.render_topic_context_prompt(pack) + "\nAccepted User-Facing Summary:\n"
            f"{prose_content.strip()}\n\n"
            "Extraction Task / 提取结构化字段:\n"
            "- Extract optional structured fields from the same evidence and accepted summary.\n"
            "- Do not rewrite the accepted summary.\n"
            "- Return one JSON object only.\n"
            "- `content` is optional here; when present it must exactly match the accepted summary.\n"
            "- Use empty lists or nulls when a field has no support.\n\n"
            "Output JSON Schema:\n"
            f"{schema}\n"
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
                    "interpretation_context": item.interpretation_context,
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
            "An event's interpretation_context only explains how to read its content. The product-authored question is not evidence and must never be presented as something the user said, believed, or experienced.\n"
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
