"""Rule-side helpers for temporal L3 LLM summarization."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ...llm import LLMProviderBridge, LLMScenario, ScenarioLLMPool
from .models import (
    L3Candidate,
    TemporalEvidencePack,
    TemporalGenerationResult,
    TemporalSummaryLLMOutput,
)
from .temporal_evidence import TemporalEvidencePackMixin
from .temporal_fallback import TemporalFallbackBuilder
from .temporal_language import TemporalLanguageGuard
from .temporal_language import render_temporal_summary_system_prompt
from .temporal_model_client import TemporalSummaryModelClient
from .temporal_output import TemporalOutputParsingMixin
from .temporal_policy import LEGACY_FLAT_TIMEOUT_SECONDS, TemporalSummaryPolicy
from .temporal_prompt_renderer import TemporalPromptRenderer
from .temporal_prompts import TEMPORAL_SUMMARY_OUTPUT_SCHEMA, TEMPORAL_SUMMARY_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def _render_temporal_summary_system_prompt() -> str:
    return render_temporal_summary_system_prompt()


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
        normalized_timeout = float(llm_timeout_seconds)
        self._llm_timeout_seconds = (
            None if normalized_timeout == LEGACY_FLAT_TIMEOUT_SECONDS else normalized_timeout
        )
        self._min_event_count_for_llm = max(1, int(min_event_count_for_llm))
        self._scenario_llm_pool = scenario_llm_pool
        self._policy = TemporalSummaryPolicy(timeout_override_seconds=self._llm_timeout_seconds)
        self._prompt_renderer = TemporalPromptRenderer(policy=self._policy)
        self._fallback_builder = TemporalFallbackBuilder()
        self._language_guard = TemporalLanguageGuard()
        self._model_client = TemporalSummaryModelClient(
            target_resolver=lambda: self._get_llm_target(),
            prompt_renderer=self._prompt_renderer,
            policy=self._policy,
        )

    async def generate_temporal_candidate(
        self,
        pack: TemporalEvidencePack,
        *,
        fallback_summary: str,
    ) -> TemporalGenerationResult:
        """Generate user-facing prose first, then best-effort structured fields."""
        fallback = self._build_fallback_result(pack, fallback_summary)
        if not self._should_use_temporal_llm(pack):
            return fallback

        timeout_seconds = self._timeout_seconds_for_pack(pack)
        disable_thinking = self._disable_thinking_for_pack(pack)
        prose_content = await self._generate_temporal_prose(
            pack,
            timeout_seconds=timeout_seconds,
            disable_thinking=disable_thinking,
        )
        if prose_content is None:
            return fallback

        summary_overrides = await self._generate_temporal_structure_overrides(
            pack,
            prose_content=prose_content,
            timeout_seconds=timeout_seconds,
            disable_thinking=disable_thinking,
        )
        return TemporalGenerationResult(
            candidate=self._candidate_from_temporal_prose(pack, prose_content),
            summary_overrides=summary_overrides,
            used_fallback=False,
        )

    def _should_use_temporal_llm(self, pack: TemporalEvidencePack) -> bool:
        return self._enabled and pack.source_event_count >= self._min_event_count_for_llm

    async def _generate_temporal_prose(
        self,
        pack: TemporalEvidencePack,
        *,
        timeout_seconds: float,
        disable_thinking: bool,
    ) -> str | None:
        try:
            prose_content = await asyncio.wait_for(
                self._call_temporal_prose_model(
                    pack,
                    timeout_seconds=timeout_seconds,
                    disable_thinking=disable_thinking,
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            self._log_temporal_timeout(
                "L3 temporal LLM call timed out",
                pack,
                timeout_seconds=timeout_seconds,
                disable_thinking=disable_thinking,
            )
            return None
        except Exception:
            return None

        prose_content = str(prose_content or "").strip()
        if not prose_content:
            return None
        try:
            self._validate_temporal_prose(prose_content)
        except Exception:
            return None
        return prose_content

    async def _generate_temporal_structure_overrides(
        self,
        pack: TemporalEvidencePack,
        *,
        prose_content: str,
        timeout_seconds: float,
        disable_thinking: bool,
    ) -> dict[str, object]:
        summary_overrides = self._empty_temporal_summary_overrides()
        payload = await self._call_temporal_structure_payload(
            pack,
            prose_content=prose_content,
            timeout_seconds=timeout_seconds,
            disable_thinking=disable_thinking,
        )
        if isinstance(payload, dict):
            try:
                summary_overrides.update(
                    self.parse_structure_output(payload, pack=pack, content=prose_content)
                )
            except Exception as exc:
                logger.warning(
                    "L3 temporal structure output rejected",
                    extra={
                        "summary_category": pack.summary_category,
                        "event_count": pack.source_event_count,
                        "error": str(exc),
                    },
                )
        return summary_overrides

    async def _call_temporal_structure_payload(
        self,
        pack: TemporalEvidencePack,
        *,
        prose_content: str,
        timeout_seconds: float,
        disable_thinking: bool,
    ) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(
                self._call_temporal_structure_model(
                    pack,
                    prose_content=prose_content,
                    timeout_seconds=timeout_seconds,
                    disable_thinking=disable_thinking,
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            self._log_temporal_timeout(
                "L3 temporal structure LLM call timed out",
                pack,
                timeout_seconds=timeout_seconds,
                disable_thinking=disable_thinking,
            )
            return None
        except Exception:
            return None

    def _empty_temporal_summary_overrides(self) -> dict[str, object]:
        return {
            "key_topics": [],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
        }

    def _candidate_from_temporal_prose(
        self,
        pack: TemporalEvidencePack,
        prose_content: str,
    ) -> L3Candidate:
        return L3Candidate(
            summary_type="temporal",
            summary_category=pack.summary_category,
            content=prose_content,
            source_event_ids=list(pack.source_event_ids),
        )

    def _log_temporal_timeout(
        self,
        message: str,
        pack: TemporalEvidencePack,
        *,
        timeout_seconds: float,
        disable_thinking: bool,
    ) -> None:
        logger.warning(
            message,
            extra={
                "summary_category": pack.summary_category,
                "event_count": pack.source_event_count,
                "timeout_seconds": timeout_seconds,
                "thinking_enabled": not disable_thinking,
            },
        )

    async def _call_temporal_prose_model(
        self,
        pack: TemporalEvidencePack,
        *,
        timeout_seconds: float | None = None,
        disable_thinking: bool | None = None,
    ) -> str | None:
        """Call the configured LLM for user-facing temporal summary prose."""
        return await self._model_client.call_prose_model(
            pack,
            timeout_seconds=timeout_seconds,
            disable_thinking=disable_thinking,
        )

    async def _call_temporal_structure_model(
        self,
        pack: TemporalEvidencePack,
        *,
        prose_content: str,
        timeout_seconds: float | None = None,
        disable_thinking: bool | None = None,
    ) -> dict[str, Any] | None:
        """Call the configured LLM for optional temporal summary structure."""
        return await self._model_client.call_structure_model(
            pack,
            prose_content=prose_content,
            timeout_seconds=timeout_seconds,
            disable_thinking=disable_thinking,
        )

    async def _call_temporal_model(
        self,
        pack: TemporalEvidencePack,
        *,
        timeout_seconds: float | None = None,
        disable_thinking: bool | None = None,
    ) -> dict[str, Any] | None:
        """Call the configured LLM adapter for temporal summary generation."""
        return await self._model_client.call_model(
            pack,
            timeout_seconds=timeout_seconds,
            disable_thinking=disable_thinking,
        )

    def _timeout_seconds_for_pack(self, pack: TemporalEvidencePack) -> float:
        return self._policy.timeout_seconds_for_category(pack.summary_category)

    def _disable_thinking_for_pack(self, pack: TemporalEvidencePack) -> bool:
        return self._policy.disable_thinking_for_category(pack.summary_category)

    def _build_fallback_result(
        self,
        pack: TemporalEvidencePack,
        fallback_summary: str,
    ) -> TemporalGenerationResult:
        return self._fallback_builder.build_result(pack, fallback_summary)

    def _raw_plugin_summary_lines(self, pack: TemporalEvidencePack) -> list[str]:
        return self._fallback_builder.raw_plugin_summary_lines(pack)

    def _build_fallback_content(
        self,
        pack: TemporalEvidencePack,
        *,
        fallback_summary: str,
        raw_feature_lines: list[str],
    ) -> str:
        return self._fallback_builder.build_content(
            pack,
            fallback_summary=fallback_summary,
            raw_feature_lines=raw_feature_lines,
        )

    def _zh_source_labels(self, source_distribution: dict[str, object]) -> list[str]:
        return self._fallback_builder.zh_source_labels(source_distribution)

    def _join_zh(self, values: list[str]) -> str:
        return self._fallback_builder.join_zh(values)

    def _build_zh_feature_lines(self, pack: TemporalEvidencePack) -> list[str]:
        return self._fallback_builder.build_zh_feature_lines(pack)

    def _validate_target_language(self, output: TemporalSummaryLLMOutput) -> None:
        self._language_guard.validate_output(output)

    def _user_facing_strings(self, output: TemporalSummaryLLMOutput) -> list[str]:
        return self._language_guard.user_facing_strings(output)

    def _validate_temporal_prose(self, content: str) -> None:
        self._language_guard.validate_prose(content)

    def _looks_like_non_zh_user_text(self, text: str) -> bool:
        return self._language_guard.looks_like_non_zh_user_text(text)

    def _temporal_prompt_payload(self, pack: TemporalEvidencePack) -> dict[str, object]:
        return self._prompt_renderer.prompt_payload(pack)

    def _render_temporal_context_prompt(self, pack: TemporalEvidencePack) -> str:
        return self._prompt_renderer.render_context_prompt(pack)

    def _render_temporal_prose_prompt(self, pack: TemporalEvidencePack) -> str:
        return self._prompt_renderer.render_prose_prompt(pack)

    def _render_temporal_structure_prompt(
        self,
        pack: TemporalEvidencePack,
        *,
        prose_content: str,
    ) -> str:
        return self._prompt_renderer.render_structure_prompt(pack, prose_content=prose_content)

    def _render_temporal_summary_prompt(self, pack: TemporalEvidencePack) -> str:
        return self._prompt_renderer.render_summary_prompt(pack)

    def _period_focus_instruction(self, pack: TemporalEvidencePack) -> str:
        return self._policy.focus_instruction(pack.summary_category)

    def _period_structure_instruction(self, pack: TemporalEvidencePack) -> str:
        return self._policy.structure_instruction(pack.summary_category)

    def _get_adapter(self) -> Any | None:
        if self._scenario_llm_pool is None:
            return None
        try:
            return self._scenario_llm_pool.get(LLMScenario.MEMORY_SUMMARIZER)
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
