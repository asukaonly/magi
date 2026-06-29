"""LLM call client for L3 temporal summaries."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from ...llm import LLMProviderBridge
from .models import TemporalEvidencePack
from .temporal_language import render_temporal_summary_system_prompt
from .temporal_policy import TemporalSummaryPolicy
from .temporal_prompt_renderer import TemporalPromptRenderer

logger = logging.getLogger(__name__)
TemporalLLMTargetResolver = Callable[[], tuple[Any, LLMProviderBridge] | None]


class TemporalSummaryModelClient:
    """Own provider calls for temporal summary prose and structure generation."""

    def __init__(
        self,
        *,
        target_resolver: TemporalLLMTargetResolver,
        prompt_renderer: TemporalPromptRenderer,
        policy: TemporalSummaryPolicy,
    ) -> None:
        self._target_resolver = target_resolver
        self._prompt_renderer = prompt_renderer
        self._policy = policy

    async def call_prose_model(
        self,
        pack: TemporalEvidencePack,
        *,
        timeout_seconds: float | None = None,
        disable_thinking: bool | None = None,
    ) -> str | None:
        """Call the configured LLM for user-facing temporal summary prose."""
        llm_target = self._target_resolver()
        if llm_target is None:
            return None
        adapter, provider_bridge = llm_target
        raw = await self._chat_completion(
            adapter=adapter,
            provider_bridge=provider_bridge,
            pack=pack,
            request_kind="memory:l3_temporal_summary_prose",
            prompt=self._prompt_renderer.render_prose_prompt(pack),
            json_mode=False,
            timeout_seconds=timeout_seconds,
            disable_thinking=disable_thinking,
            log_label="prose",
        )
        return raw or None

    async def call_structure_model(
        self,
        pack: TemporalEvidencePack,
        *,
        prose_content: str,
        timeout_seconds: float | None = None,
        disable_thinking: bool | None = None,
    ) -> dict[str, Any] | None:
        """Call the configured LLM for optional temporal summary structure."""
        llm_target = self._target_resolver()
        if llm_target is None:
            return None
        adapter, provider_bridge = llm_target
        raw = await self._chat_completion(
            adapter=adapter,
            provider_bridge=provider_bridge,
            pack=pack,
            request_kind="memory:l3_temporal_summary_structure",
            prompt=self._prompt_renderer.render_structure_prompt(pack, prose_content=prose_content),
            json_mode=True,
            timeout_seconds=timeout_seconds,
            disable_thinking=disable_thinking,
            log_label="structure",
        )
        return self._parse_json_payload(raw, request_kind="memory:l3_temporal_summary_structure")

    async def call_model(
        self,
        pack: TemporalEvidencePack,
        *,
        timeout_seconds: float | None = None,
        disable_thinking: bool | None = None,
    ) -> dict[str, Any] | None:
        """Call the legacy single-step JSON temporal summary path."""
        llm_target = self._target_resolver()
        if llm_target is None:
            return None
        adapter, provider_bridge = llm_target
        raw = await self._chat_completion(
            adapter=adapter,
            provider_bridge=provider_bridge,
            pack=pack,
            request_kind="memory:l3_temporal_summary",
            prompt=self._prompt_renderer.render_summary_prompt(pack),
            json_mode=True,
            timeout_seconds=timeout_seconds,
            disable_thinking=disable_thinking,
            log_label="",
        )
        return self._parse_json_payload(raw, request_kind="memory:l3_temporal_summary")

    async def _chat_completion(
        self,
        *,
        adapter: Any,
        provider_bridge: LLMProviderBridge,
        pack: TemporalEvidencePack,
        request_kind: str,
        prompt: str,
        json_mode: bool,
        timeout_seconds: float | None,
        disable_thinking: bool | None,
        log_label: str,
    ) -> str:
        resolved_timeout_seconds = timeout_seconds or self._policy.timeout_seconds_for_category(
            pack.summary_category
        )
        resolved_disable_thinking = (
            disable_thinking
            if disable_thinking is not None
            else self._policy.disable_thinking_for_category(pack.summary_category)
        )
        provider = str(getattr(adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(adapter, "model_name", "unknown") or "unknown")
        log_context = {
            "request_kind": request_kind,
            "provider": provider,
            "model": model,
            "event_count": pack.source_event_count,
            "summary_category": pack.summary_category,
            "timeout_seconds": resolved_timeout_seconds,
            "thinking_enabled": not resolved_disable_thinking,
        }
        display_label = f" {log_label}" if log_label else ""
        logger.info("L3 temporal%s LLM call started", display_label, extra=log_context)
        started_at = time.perf_counter()
        try:
            response = await provider_bridge.chat_response(
                system_prompt=render_temporal_summary_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=json_mode,
                disable_thinking=resolved_disable_thinking,
                cache_system=True,
                timeout_seconds=resolved_timeout_seconds,
                event_context={
                    "request_kind": request_kind,
                    "turn_id": pack.source_event_ids[0] if pack.source_event_ids else None,
                    "agent_id": "memory:l3",
                },
            )
        except Exception as exc:
            logger.warning(
                "L3 temporal%s LLM call failed",
                display_label,
                extra={**log_context, "error": str(exc)},
            )
            raise

        raw = str(response.content or "").strip()
        logger.info(
            "L3 temporal%s LLM call completed",
            display_label,
            extra={
                **log_context,
                "duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
                "response_char_count": len(raw),
            },
        )
        return raw

    def _parse_json_payload(self, raw: str, *, request_kind: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(raw)
        except Exception:
            logger.warning(
                "L3 temporal LLM returned invalid JSON", extra={"request_kind": request_kind}
            )
            return None
        return parsed if isinstance(parsed, dict) else None


__all__ = ["TemporalSummaryModelClient"]
