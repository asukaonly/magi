"""JSON-mode LLM client helpers for L2 prompt services."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional, Protocol, cast

from ...core.logger import get_logger
from ...llm import LLMProviderBridge, LLMScenario, ProviderResponse, ScenarioLLMPool

logger = get_logger("magi.memory.l2.llm_service")
_RATE_LIMIT_BACKOFF_SECONDS = (1.0, 2.0, 4.0)


class _L2LLMJsonClientHostProtocol(Protocol):
    _scenario_llm_pool: ScenarioLLMPool | None


class L2LLMJsonClientMixin:
    """Shared JSON-mode LLM execution and retry helpers."""

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
            logger.warning(
                "L2 LLM call skipped: no adapter available",
                request_kind=request_kind,
                scenario=scenario.value,
            )
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
                failure_context["duration_ms"] = round(
                    (time.perf_counter() - started_at) * 1000.0, 2
                )
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
        host = self._llm_json_client_host()
        if host._scenario_llm_pool is None:
            logger.warning("L2 LLM adapter unavailable: scenario_llm_pool is None")
            return None
        try:
            return host._scenario_llm_pool.get(scenario)
        except Exception as exc:
            logger.warning("L2 LLM adapter unavailable", error=str(exc), scenario=scenario.value)
            return None

    def _get_llm_target(
        self, *, scenario: LLMScenario = LLMScenario.CONTEXT_DECIDER
    ) -> Optional[tuple[Any, LLMProviderBridge]]:
        adapter = self._get_adapter(scenario=scenario)
        if adapter is None:
            return None
        return adapter, LLMProviderBridge(adapter)

    def _resolve_max_output_tokens(self, *, scenario: LLMScenario) -> int:
        default_limit = 4096
        host = self._llm_json_client_host()
        pool = host._scenario_llm_pool
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
        if max_output_tokens is None:
            return default_limit
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

    def _llm_json_client_host(self) -> _L2LLMJsonClientHostProtocol:
        return cast(_L2LLMJsonClientHostProtocol, self)


__all__ = ["L2LLMJsonClientMixin"]
