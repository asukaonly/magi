"""LLM-backed episodic summary generation with deterministic fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from ...i18n import llm_language_label
from ...llm import LLMProviderBridge, LLMRequestPriority, LLMScenario, ScenarioLLMPool
from .episodic_evidence import EpisodicEvidencePackMixin
from .episodic_prompts import EPISODIC_SUMMARY_OUTPUT_SCHEMA, EPISODIC_SUMMARY_SYSTEM_PROMPT
from .experience_prompts import EXPERIENCE_REVIEW_OUTPUT_SCHEMA, EXPERIENCE_REVIEW_SYSTEM_PROMPT
from .models import (
    EpisodicEvidencePack,
    EpisodicGenerationResult,
    EpisodicSummaryLLMOutput,
    ExperienceReviewLLMOutput,
    L3Candidate,
)

logger = logging.getLogger(__name__)


def _target_language_instruction() -> str:
    target = llm_language_label(default="en")
    return (
        f"- Write label and content in {target}.\n"
        "- Preserve event ids, entity ids, URLs, file paths, source names, product names, "
        "song titles, and quoted user text exactly as the evidence presents them."
    )


class EpisodicSummaryLLMService(EpisodicEvidencePackMixin):
    """Generate episodic L3 candidates from an evidence pack, with rule fallback."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        llm_timeout_seconds: float = 30.0,
        scenario_llm_pool: ScenarioLLMPool | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._llm_timeout_seconds = float(llm_timeout_seconds)
        self._scenario_llm_pool = scenario_llm_pool

    async def generate_episodic_candidate(
        self,
        pack: EpisodicEvidencePack,
        *,
        fallback_label: str,
        fallback_content: str,
    ) -> EpisodicGenerationResult:
        if not self._enabled or self._scenario_llm_pool is None:
            return self._build_fallback_result(pack, fallback_label, fallback_content)

        try:
            prose_content = await asyncio.wait_for(
                self._call_episodic_prose_model(pack),
                timeout=self._llm_timeout_seconds,
            )
        except Exception:
            return self._build_fallback_result(pack, fallback_label, fallback_content)
        prose_content = str(prose_content or "").strip()
        if not prose_content:
            return self._build_fallback_result(pack, fallback_label, fallback_content)

        metadata: dict[str, object] = {
            "source_episode_id": pack.episode_id,
            "label": fallback_label,
        }
        try:
            payload = await asyncio.wait_for(
                self._call_episodic_structure_model(pack, prose_content=prose_content),
                timeout=self._llm_timeout_seconds,
            )
        except Exception:
            payload = None
        if isinstance(payload, dict):
            parsed_metadata = self._parse_structure_output(
                payload,
                pack=pack,
                content=prose_content,
                fallback_label=fallback_label,
            )
            if parsed_metadata:
                metadata.update(parsed_metadata)

        return EpisodicGenerationResult(
            candidate=L3Candidate(
                content=prose_content[:240],
                source_event_ids=list(pack.source_event_ids),
                summary_category="episodic",
                summary_type="thematic",
                insight_metadata=metadata,
            ),
            summary_overrides={},
            used_fallback=False,
        )

    async def generate_experience_review(
        self,
        pack: EpisodicEvidencePack,
        *,
        fallback_label: str,
        fallback_content: str,
    ) -> EpisodicGenerationResult:
        if not self._enabled or self._scenario_llm_pool is None:
            return self._build_fallback_result(pack, fallback_label, fallback_content)

        try:
            raw = await asyncio.wait_for(
                self._call_experience_review_model(pack),
                timeout=self._llm_timeout_seconds,
            )
        except Exception:
            return self._build_fallback_result(pack, fallback_label, fallback_content)

        parsed = self._parse_experience_review_output(str(raw or ""))
        if parsed is None:
            return self._build_fallback_result(pack, fallback_label, fallback_content)

        return EpisodicGenerationResult(
            candidate=self._candidate_from_experience_review_output(pack, parsed),
            summary_overrides={},
            used_fallback=False,
        )

    async def _call_episodic_prose_model(self, pack: EpisodicEvidencePack) -> str | None:
        llm_target = self._get_llm_target()
        if llm_target is None:
            return None

        adapter, bridge = llm_target
        prompt = self._render_prose_prompt(pack)
        provider = str(getattr(adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(adapter, "model_name", "unknown") or "unknown")
        log_context = {
            "request_kind": "memory:l3_episodic_summary_prose",
            "provider": provider,
            "model": model,
            "event_count": pack.source_event_count,
            "episode_id": pack.episode_id,
        }
        logger.info("L3 episodic prose LLM call started", extra=log_context)
        try:
            response = await bridge.chat_response(
                system_prompt=EPISODIC_SUMMARY_SYSTEM_PROMPT
                + "\nLanguage Rules:\n"
                + _target_language_instruction(),
                messages=[{"role": "user", "content": prompt}],
                json_mode=False,
                temperature=0.3,
                disable_thinking=True,
                cache_system=True,
                timeout_seconds=self._llm_timeout_seconds,
                event_context={
                    "request_kind": "memory:l3_episodic_summary_prose",
                    "turn_id": pack.source_event_ids[0] if pack.source_event_ids else None,
                    "agent_id": "memory:l3",
                },
                priority=LLMRequestPriority.LOW,
            )
        except Exception as exc:
            logger.warning(
                "L3 episodic prose LLM call failed", extra={**log_context, "error": str(exc)}
            )
            raise

        raw = str(response.content or "").strip()
        logger.info(
            "L3 episodic prose LLM call completed",
            extra={**log_context, "response_char_count": len(raw)},
        )
        return raw or None

    async def _call_episodic_structure_model(
        self,
        pack: EpisodicEvidencePack,
        *,
        prose_content: str,
    ) -> dict[str, Any] | None:
        llm_target = self._get_llm_target()
        if llm_target is None:
            return None

        adapter, bridge = llm_target
        prompt = self._render_structure_prompt(pack, prose_content=prose_content)
        provider = str(getattr(adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(adapter, "model_name", "unknown") or "unknown")
        log_context = {
            "request_kind": "memory:l3_episodic_summary_structure",
            "provider": provider,
            "model": model,
            "event_count": pack.source_event_count,
            "episode_id": pack.episode_id,
        }
        logger.info("L3 episodic structure LLM call started", extra=log_context)
        try:
            response = await bridge.chat_response(
                system_prompt=EPISODIC_SUMMARY_SYSTEM_PROMPT
                + "\nLanguage Rules:\n"
                + _target_language_instruction(),
                messages=[{"role": "user", "content": prompt}],
                json_mode=True,
                temperature=0.0,
                disable_thinking=True,
                cache_system=True,
                timeout_seconds=self._llm_timeout_seconds,
                event_context={
                    "request_kind": "memory:l3_episodic_summary_structure",
                    "turn_id": pack.source_event_ids[0] if pack.source_event_ids else None,
                    "agent_id": "memory:l3",
                },
                priority=LLMRequestPriority.LOW,
            )
        except Exception as exc:
            logger.warning(
                "L3 episodic structure LLM call failed", extra={**log_context, "error": str(exc)}
            )
            raise

        raw = str(response.content or "").strip()
        logger.info(
            "L3 episodic structure LLM call completed",
            extra={**log_context, "response_char_count": len(raw)},
        )
        try:
            parsed = json.loads(raw)
        except Exception:
            logger.warning("L3 episodic structure LLM returned invalid JSON", extra=log_context)
            return None
        return parsed if isinstance(parsed, dict) else None

    async def _call_experience_review_model(self, pack: EpisodicEvidencePack) -> str | None:
        llm_target = self._get_llm_target()
        if llm_target is None:
            return None

        adapter, bridge = llm_target
        prompt = self._render_experience_review_prompt(pack)
        provider = str(getattr(adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(adapter, "model_name", "unknown") or "unknown")
        log_context = {
            "request_kind": "memory:l3_experience_review",
            "provider": provider,
            "model": model,
            "event_count": pack.source_event_count,
            "experience_id": pack.episode_id,
        }
        logger.info("L3 experience review LLM call started", extra=log_context)
        try:
            response = await bridge.chat_response(
                system_prompt=EXPERIENCE_REVIEW_SYSTEM_PROMPT
                + "\nLanguage Rules:\n"
                + _target_language_instruction(),
                messages=[{"role": "user", "content": prompt}],
                json_mode=True,
                temperature=0.2,
                disable_thinking=True,
                cache_system=True,
                timeout_seconds=self._llm_timeout_seconds,
                event_context={
                    "request_kind": "memory:l3_experience_review",
                    "turn_id": pack.source_event_ids[0] if pack.source_event_ids else None,
                    "agent_id": "memory:l3",
                },
                priority=LLMRequestPriority.LOW,
            )
        except Exception as exc:
            logger.warning(
                "L3 experience review LLM call failed",
                extra={**log_context, "error": str(exc)},
            )
            raise

        raw = str(response.content or "").strip()
        logger.info(
            "L3 experience review LLM call completed",
            extra={**log_context, "response_char_count": len(raw)},
        )
        return raw or None

    def _get_adapter(self) -> Any | None:
        if self._scenario_llm_pool is None:
            return None
        for scenario in (LLMScenario.MEMORY_SUMMARIZER, LLMScenario.CORE):
            try:
                adapter = self._scenario_llm_pool.get(scenario)
                if adapter is not None:
                    return adapter
            except Exception as exc:
                logger.debug(
                    "L3 episodic LLM adapter unavailable for scenario %s: %s", scenario, exc
                )
        return None

    def _get_llm_target(self) -> tuple[Any, LLMProviderBridge] | None:
        adapter = self._get_adapter()
        if adapter is None:
            return None
        return adapter, LLMProviderBridge(adapter)

    def _render_context_prompt(self, pack: EpisodicEvidencePack) -> str:
        entity_label = ", ".join(_render_entity(eid) for eid in pack.primary_entity_ids) or "(none)"
        topics = pack.primary_topic_keys or pack.derived_topics
        topics_label = ", ".join(topics) if topics else "(none extracted)"
        topics_source = "" if pack.primary_topic_keys else " [derived from event entities]"

        verbatim_count = len(pack.events)
        folded_count = pack.source_event_count - verbatim_count

        lines = [
            f"Type: {pack.episode_type}",
            f"Time window: {_format_ts(pack.time_start)} – {_format_ts(pack.time_end)} ({_format_duration(pack.time_end - pack.time_start)})",
            f"Primary entities: {entity_label}",
            f"Topics: {topics_label}{topics_source}",
            f"Total events: {pack.source_event_count} ({verbatim_count} verbatim, {folded_count} folded into summaries below)",
            "",
        ]

        if pack.folded_groups:
            lines.append("Activity summary (high-volume sources folded):")
            for group in pack.folded_groups:
                lines.append(f"  - {group}")
            lines.append("")

        if pack.events:
            lines.append("Notable events (chronological):")
            for event in pack.events:
                ts = _format_ts(event.timestamp) if event.timestamp else "??"
                role_prefix = f"{event.role}: " if event.role else ""
                source_tag = event.source or event.event_type
                lines.append(f"  [{ts}] ({source_tag}) {role_prefix}{event.content}")
            lines.append("")

        return "\n".join(lines)

    def _render_user_prompt(self, pack: EpisodicEvidencePack) -> str:
        return (
            self._render_context_prompt(pack)
            + f"\nOutput JSON schema:\n{EPISODIC_SUMMARY_OUTPUT_SCHEMA}"
        )

    def _render_prose_prompt(self, pack: EpisodicEvidencePack) -> str:
        return (
            self._render_context_prompt(pack) + "\nGeneration Task / 生成用户可读正文:\n"
            "- Write only the user-facing episode summary body.\n"
            "- Do not return JSON.\n"
            "- Keep it concrete, compact, and grounded in the evidence.\n"
        )

    def _render_structure_prompt(
        self,
        pack: EpisodicEvidencePack,
        *,
        prose_content: str,
    ) -> str:
        return (
            self._render_context_prompt(pack) + "\nAccepted User-Facing Summary:\n"
            f"{prose_content.strip()}\n\n"
            "Extraction Task / 提取结构化字段:\n"
            "- Extract label, key_topics, and key_entities from the same evidence and accepted summary.\n"
            "- Do not rewrite the accepted summary.\n"
            "- Return one JSON object only.\n"
            "- `content` is optional here; when present it must exactly match the accepted summary.\n\n"
            f"Output JSON schema:\n{EPISODIC_SUMMARY_OUTPUT_SCHEMA}"
        )

    def _render_experience_review_prompt(self, pack: EpisodicEvidencePack) -> str:
        return (
            self._render_context_prompt(pack) + "\nExperience Review Task / 生成用户可读经历回顾:\n"
            "- Return one JSON object only.\n"
            "- Write a narrative that covers why the experience started, what happened, and where it landed.\n"
            "- Keep intent and outcome separate from the narrative.\n"
            "- Stay grounded in the evidence; say unresolved when the ending is unclear.\n\n"
            f"Output JSON schema:\n{EXPERIENCE_REVIEW_OUTPUT_SCHEMA}"
        )

    def _parse_output(self, raw: str) -> EpisodicSummaryLLMOutput | None:
        try:
            data = json.loads(raw or "{}")
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        label = str(data.get("label") or "").strip()
        content = str(data.get("content") or "").strip()
        if not label or not content:
            return None
        key_topics_raw = data.get("key_topics") or []
        key_entities_raw = data.get("key_entities") or []
        key_topics = [
            str(t).strip()
            for t in key_topics_raw
            if isinstance(t, (str, int, float)) and str(t).strip()
        ][:5]
        key_entities: list[dict[str, object]] = []
        if isinstance(key_entities_raw, list):
            for item in key_entities_raw[:5]:
                if isinstance(item, dict) and item.get("id"):
                    key_entities.append(
                        {
                            "id": str(item.get("id")).strip(),
                            "label": str(item.get("label") or item.get("id")).strip(),
                        }
                    )
        return EpisodicSummaryLLMOutput(
            label=label[:36],  # allow 18 zh chars
            content=content[:240],  # allow ~100 zh chars
            key_topics=key_topics,
            key_entities=key_entities,
        )

    def _parse_structure_output(
        self,
        payload: dict[str, Any],
        *,
        pack: EpisodicEvidencePack,
        content: str,
        fallback_label: str,
    ) -> dict[str, object] | None:
        content = str(content or "").strip()
        if not content:
            return None
        payload_content = payload.get("content")
        if payload_content is not None:
            normalized_payload_content = str(payload_content).strip()
            if normalized_payload_content and normalized_payload_content != content:
                return None
        label = str(payload.get("label") or fallback_label).strip()[:36]
        if not label:
            label = fallback_label
        key_topics_raw = payload.get("key_topics") or []
        key_entities_raw = payload.get("key_entities") or []
        key_topics = [
            str(t).strip()
            for t in key_topics_raw
            if isinstance(t, (str, int, float)) and str(t).strip()
        ][:5]
        key_entities: list[dict[str, object]] = []
        if isinstance(key_entities_raw, list):
            for item in key_entities_raw[:5]:
                if isinstance(item, dict) and item.get("id"):
                    key_entities.append(
                        {
                            "id": str(item.get("id")).strip(),
                            "label": str(item.get("label") or item.get("id")).strip(),
                        }
                    )
        return {
            "source_episode_id": pack.episode_id,
            "label": label,
            "key_topics": key_topics,
            "key_entities": key_entities,
        }

    def _parse_experience_review_output(self, raw: str) -> ExperienceReviewLLMOutput | None:
        try:
            data = json.loads(raw or "{}")
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None

        label = str(data.get("label") or "").strip()[:48]
        narrative = str(data.get("narrative") or "").strip()[:400]
        if not label or not narrative:
            return None

        intent = str(data.get("intent") or "").strip()[:180]
        outcome = str(data.get("outcome") or "").strip()[:180]
        key_topics_raw = data.get("key_topics") or []
        key_entities_raw = data.get("key_entities") or []
        key_topics = [
            str(t).strip()
            for t in key_topics_raw
            if isinstance(t, (str, int, float)) and str(t).strip()
        ][:5]
        key_entities: list[dict[str, object]] = []
        if isinstance(key_entities_raw, list):
            for item in key_entities_raw[:5]:
                if isinstance(item, dict) and item.get("id"):
                    key_entities.append(
                        {
                            "id": str(item.get("id")).strip(),
                            "label": str(item.get("label") or item.get("id")).strip(),
                        }
                    )
        return ExperienceReviewLLMOutput(
            label=label,
            narrative=narrative,
            intent=intent,
            outcome=outcome,
            key_topics=key_topics,
            key_entities=key_entities,
        )

    def _candidate_from_output(
        self,
        pack: EpisodicEvidencePack,
        parsed: EpisodicSummaryLLMOutput,
    ) -> L3Candidate:
        return L3Candidate(
            content=parsed.content,
            source_event_ids=list(pack.source_event_ids),
            summary_category="episodic",
            summary_type="thematic",
            insight_metadata={
                "source_episode_id": pack.episode_id,
                "label": parsed.label,
                "key_topics": parsed.key_topics,
                "key_entities": parsed.key_entities,
            },
        )

    def _candidate_from_experience_review_output(
        self,
        pack: EpisodicEvidencePack,
        parsed: ExperienceReviewLLMOutput,
    ) -> L3Candidate:
        metadata: dict[str, object] = {
            "label": parsed.label,
            "key_topics": parsed.key_topics,
            "key_entities": parsed.key_entities,
        }
        if parsed.intent:
            metadata["intent"] = parsed.intent
        if parsed.outcome:
            metadata["outcome"] = parsed.outcome
        return L3Candidate(
            content=parsed.narrative,
            source_event_ids=list(pack.source_event_ids),
            summary_category="episodic",
            summary_type="thematic",
            insight_metadata=metadata,
        )

    def _build_fallback_result(
        self,
        pack: EpisodicEvidencePack,
        fallback_label: str,
        fallback_content: str,
    ) -> EpisodicGenerationResult:
        candidate = L3Candidate(
            content=fallback_content,
            source_event_ids=list(pack.source_event_ids),
            summary_category="episodic",
            summary_type="thematic",
            insight_metadata={
                "source_episode_id": pack.episode_id,
                "label": fallback_label,
                "fallback": True,
            },
        )
        return EpisodicGenerationResult(
            candidate=candidate,
            summary_overrides={},
            used_fallback=True,
        )


def _render_entity(entity_id: str) -> str:
    """Convert 'software:v2ex' -> 'v2ex (software)' for prompt readability."""
    if ":" in entity_id:
        kind, _, name = entity_id.partition(":")
        if name:
            return f"{name} ({kind})"
    return entity_id


def _format_ts(ts: float | None) -> str:
    if not ts:
        return "??"
    return time.strftime("%m/%d %H:%M", time.localtime(ts))


def _format_duration(seconds: float) -> str:
    minutes = max(0, int(seconds // 60))
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    rem = minutes % 60
    return f"{hours}h{rem}m" if rem else f"{hours}h"


__all__ = ["EpisodicSummaryLLMService"]
