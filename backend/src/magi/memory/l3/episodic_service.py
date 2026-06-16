"""LLM-backed episodic summary generation with deterministic fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from ...i18n import llm_language_label
from ...llm import LLMProviderBridge, LLMScenario, ScenarioLLMPool
from .episodic_evidence import EpisodicEvidencePackMixin
from .episodic_prompts import EPISODIC_SUMMARY_OUTPUT_SCHEMA, EPISODIC_SUMMARY_SYSTEM_PROMPT
from .models import (
    EpisodicEvidencePack,
    EpisodicGenerationResult,
    EpisodicSummaryLLMOutput,
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

        llm_target = self._get_llm_target()
        if llm_target is None:
            return self._build_fallback_result(pack, fallback_label, fallback_content)

        adapter, bridge = llm_target
        prompt = self._render_user_prompt(pack)
        provider = str(getattr(adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(adapter, "model_name", "unknown") or "unknown")
        log_context = {
            "request_kind": "memory:l3_episodic_summary",
            "provider": provider,
            "model": model,
            "event_count": pack.source_event_count,
            "episode_id": pack.episode_id,
        }
        logger.info("L3 episodic LLM call started", extra=log_context)
        try:
            response = await asyncio.wait_for(
                bridge.chat_response(
                    system_prompt=EPISODIC_SUMMARY_SYSTEM_PROMPT + "\nLanguage Rules:\n" + _target_language_instruction(),
                    messages=[{"role": "user", "content": prompt}],
                    json_mode=True,
                    temperature=0.3,
                    disable_thinking=True,
                    cache_system=True,  # constant + per-language system prompt
                    timeout_seconds=self._llm_timeout_seconds,
                    event_context={
                        "request_kind": "memory:l3_episodic_summary",
                        "turn_id": pack.source_event_ids[0] if pack.source_event_ids else None,
                        "agent_id": "memory:l3",
                    },
                ),
                timeout=self._llm_timeout_seconds,
            )
        except Exception as exc:
            logger.warning("L3 episodic LLM call failed (%s); using rule fallback", exc, extra=log_context)
            return self._build_fallback_result(pack, fallback_label, fallback_content)

        raw = response.content
        logger.info("L3 episodic LLM call completed", extra={**log_context, "response_char_count": len(raw or "")})

        parsed = self._parse_output(raw)
        if parsed is None:
            return self._build_fallback_result(pack, fallback_label, fallback_content)

        candidate = self._candidate_from_output(pack, parsed)
        return EpisodicGenerationResult(
            candidate=candidate,
            summary_overrides={},
            used_fallback=False,
        )

    def _get_adapter(self) -> Any | None:
        if self._scenario_llm_pool is None:
            return None
        for scenario in (LLMScenario.MEMORY_SUMMARIZER, LLMScenario.CORE):
            try:
                adapter = self._scenario_llm_pool.get(scenario)
                if adapter is not None:
                    return adapter
            except Exception as exc:
                logger.debug("L3 episodic LLM adapter unavailable for scenario %s: %s", scenario, exc)
        return None

    def _get_llm_target(self) -> tuple[Any, LLMProviderBridge] | None:
        adapter = self._get_adapter()
        if adapter is None:
            return None
        return adapter, LLMProviderBridge(adapter)

    def _render_user_prompt(self, pack: EpisodicEvidencePack) -> str:
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
            lines.append("Activity summary (high-volume sensor sources folded):")
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

        lines.append(f"Output JSON schema:\n{EPISODIC_SUMMARY_OUTPUT_SCHEMA}")
        return "\n".join(lines)

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
                    key_entities.append({
                        "id": str(item.get("id")).strip(),
                        "label": str(item.get("label") or item.get("id")).strip(),
                    })
        return EpisodicSummaryLLMOutput(
            label=label[:36],     # allow 18 zh chars
            content=content[:240],  # allow ~100 zh chars
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
