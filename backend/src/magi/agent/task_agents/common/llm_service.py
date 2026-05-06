"""Shared LLM invocation service for task agents."""
from __future__ import annotations

import time
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable

from ....config import get_config
from ....config.models import LLMScenario, ThinkingDepth
from ....config.constants import DEFAULT_MAX_TOKENS
from ....core.logger import get_logger
from ....llm.provider_bridge import LLMProviderBridge, _coerce_thinking_depth
from ....llm.streaming_events import LLMStreamEvent
from ....utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response

logger = get_logger(__name__)

LLMTraceCallback = Callable[[dict[str, object]], Awaitable[None] | None]


class TaskAgentLLMService:
    """Centralizes task-agent LLM calls and logging."""

    def __init__(self, *, llm_adapter=None, llm_pool=None, scenario: LLMScenario = LLMScenario.CORE, logger_name: str) -> None:
        self._llm = llm_adapter
        self._llm_pool = llm_pool
        self._scenario = scenario
        self._provider_bridge = LLMProviderBridge(llm_adapter) if llm_adapter else None
        self._llm_logger = get_llm_logger(logger_name)
        self._logger_name = logger_name

    def _resolve_llm(self):
        if self._llm_pool is not None:
            llm = self._llm_pool.get(self._scenario)
            if llm is not self._llm:
                self._llm = llm
                self._provider_bridge = LLMProviderBridge(llm)
        return self._llm

    def _build_event_context(
        self,
        *,
        request_id: str,
        event_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        context = dict(event_context or {})
        context.setdefault("request_id", request_id)
        context.setdefault("request_kind", f"task_agent:{self._logger_name}")
        context.setdefault("agent_id", self._logger_name)
        return context

    async def call(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        disable_thinking: bool = True,
        thinking_depth: ThinkingDepth | None = None,
        temperature: float = 0.7,
        json_mode: bool = False,
        timeout_seconds: float | None = None,
        llm_trace_callback: LLMTraceCallback | None = None,
        event_context: dict[str, Any] | None = None,
    ) -> str:
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        llm = self._resolve_llm()
        model_name = getattr(llm, "model_name", "unknown")
        log_llm_request(
            self._llm_logger,
            request_id=request_id,
            model=model_name,
            system_prompt=system_prompt,
            messages=messages,
        )
        depth = _coerce_thinking_depth(thinking_depth, disable_thinking)
        try:
            provider_response = await self._provider_bridge.chat_response(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=self._llm_max_tokens(),
                temperature=temperature,
                thinking_depth=depth,
                json_mode=json_mode,
                timeout_seconds=timeout_seconds,
                event_context=self._build_event_context(
                    request_id=request_id,
                    event_context=event_context,
                ),
            )
            response = provider_response.content
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                self._llm_logger,
                request_id=request_id,
                response=response,
                success=True,
                duration_ms=duration_ms,
                provider_metadata=provider_response.metadata,
            )
            if not response.strip():
                logger.warning(
                    "Task-agent LLM returned empty content | request_id=%s model=%s disable_thinking=%s metadata=%s",
                    request_id,
                    model_name,
                    disable_thinking,
                    provider_response.metadata,
                )
            trace_metrics = dict((provider_response.metadata or {}).get("trace_metrics") or {})
            if llm_trace_callback is not None and trace_metrics:
                callback_result = llm_trace_callback(trace_metrics)
                if hasattr(callback_result, "__await__"):
                    await callback_result
            return response
        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                self._llm_logger,
                request_id=request_id,
                response="",
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )
            raise

    async def call_stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        disable_thinking: bool = True,
        thinking_depth: ThinkingDepth | None = None,
        temperature: float = 0.7,
        json_mode: bool = False,
        timeout_seconds: float | None = None,
        event_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Streaming variant of call().

        Yields :class:`LLMStreamEvent` instances — typically one
        ``text_delta`` per visible fragment plus optional
        ``reasoning_delta`` / ``usage`` / ``done`` events. Each event is
        also forwarded to the contextual stream sink by the underlying
        provider bridge, so UI consumers do not need to re-wire.
        """
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        llm = self._resolve_llm()
        model_name = getattr(llm, "model_name", "unknown")
        log_llm_request(
            self._llm_logger,
            request_id=request_id,
            model=model_name,
            system_prompt=system_prompt,
            messages=messages,
        )
        depth = _coerce_thinking_depth(thinking_depth, disable_thinking)
        collected = ""
        try:
            async for event in self._provider_bridge.chat_response_stream(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=self._llm_max_tokens(),
                temperature=temperature,
                thinking_depth=depth,
                json_mode=json_mode,
                timeout_seconds=timeout_seconds,
                event_context=self._build_event_context(
                    request_id=request_id,
                    event_context=event_context,
                ),
            ):
                if event.kind == "text_delta" and event.text:
                    collected += event.text
                yield event
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                self._llm_logger,
                request_id=request_id,
                response=collected,
                success=True,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                self._llm_logger,
                request_id=request_id,
                response="",
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )
            raise

    def _llm_max_tokens(self) -> int:
        try:
            return int(get_config().llm.max_tokens)
        except Exception:
            return DEFAULT_MAX_TOKENS
