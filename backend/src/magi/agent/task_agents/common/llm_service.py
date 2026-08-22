"""Shared LLM invocation service for task agents."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, AsyncIterator, Awaitable, Callable

from magi.control.run_control import RunControl
from ....config import get_config
from ....config.models import LLMScenario, ThinkingDepth
from ....config.constants import DEFAULT_MAX_TOKENS, SYSTEM_PROMPT_CACHE_BOUNDARY
from ....core.logger import get_logger
from ....llm.cancellable_client import CancellableLLMClient, CancellationRaised, RetractRaised
from ....llm.provider_bridge import LLMProviderBridge, _coerce_thinking_depth
from ....llm.streaming_events import LLMStreamEvent
from ....utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response
from ...execution.task_budget import consume_task_llm_calls

logger = get_logger(__name__)

LLMTraceCallback = Callable[[dict[str, object]], Awaitable[None] | None]


@dataclass(slots=True)
class _LLMRequestContext:
    request_id: str
    start_time: float
    model_name: str
    thinking_depth: ThinkingDepth | None
    event_context: dict[str, Any]


class TaskAgentLLMService:
    """Centralizes task-agent LLM calls and logging."""

    def __init__(
        self,
        *,
        llm_adapter=None,
        llm_pool=None,
        scenario: LLMScenario = LLMScenario.CORE,
        logger_name: str,
    ) -> None:
        self._llm = llm_adapter
        self._llm_pool = llm_pool
        self._scenario = scenario
        self._provider_bridge = LLMProviderBridge(llm_adapter) if llm_adapter else None
        self._cancellable_client = (
            CancellableLLMClient(self._provider_bridge) if self._provider_bridge else None
        )
        self._llm_logger = get_llm_logger(logger_name)
        self._logger_name = logger_name

    def _resolve_llm(self):
        if self._llm_pool is not None:
            llm = self._llm_pool.get(self._scenario)
            if llm is not self._llm:
                self._llm = llm
                self._provider_bridge = LLMProviderBridge(llm)
                self._cancellable_client = CancellableLLMClient(self._provider_bridge)
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
        control: RunControl | None = None,
    ) -> str:
        request_context = self._begin_request(
            system_prompt=system_prompt,
            messages=messages,
            thinking_depth=thinking_depth,
            disable_thinking=disable_thinking,
            event_context=event_context,
        )
        try:
            await consume_task_llm_calls()
            provider_response = await self._call_provider_response(
                request_context=request_context,
                system_prompt=system_prompt,
                messages=messages,
                temperature=temperature,
                json_mode=json_mode,
                timeout_seconds=timeout_seconds,
                control=control,
            )
            response = provider_response.content
            self._log_call_success(
                request_context,
                response=response,
                provider_metadata=provider_response.metadata,
                disable_thinking=disable_thinking,
            )
            await _emit_trace_metrics(llm_trace_callback, provider_response.metadata)
            return response
        except (CancellationRaised, RetractRaised):
            # Signal-driven aborts are not LLM failures; re-raise without
            # logging as failure to keep metrics clean.
            raise
        except Exception as exc:
            self._log_failure(request_context, exc)
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
        control: RunControl | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Streaming variant of call(). Yields LLMStreamEvent instances; the
        final response text is logged on completion. Accepts an optional
        ``control: RunControl`` to enable cancel/retract via
        :class:`~magi.llm.cancellable_client.CancellableLLMClient`."""
        request_context = self._begin_request(
            system_prompt=system_prompt,
            messages=messages,
            thinking_depth=thinking_depth,
            disable_thinking=disable_thinking,
            event_context=event_context,
        )
        collected = ""
        try:
            await consume_task_llm_calls()
            stream_source = self._open_provider_stream(
                request_context=request_context,
                system_prompt=system_prompt,
                messages=messages,
                temperature=temperature,
                json_mode=json_mode,
                timeout_seconds=timeout_seconds,
                control=control,
            )
            async for event in stream_source:
                if event.kind == "text_delta" and event.text:
                    collected += event.text
                yield event
            self._log_stream_success(request_context, response=collected)
        except (CancellationRaised, RetractRaised):
            # Signal-driven aborts are not LLM failures; re-raise without
            # logging as failure to keep metrics clean.
            raise
        except Exception as exc:
            self._log_failure(request_context, exc)
            raise

    def _begin_request(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        thinking_depth: ThinkingDepth | None,
        disable_thinking: bool,
        event_context: dict[str, Any] | None,
    ) -> _LLMRequestContext:
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
            cache_boundary=SYSTEM_PROMPT_CACHE_BOUNDARY,
        )
        return _LLMRequestContext(
            request_id=request_id,
            start_time=start_time,
            model_name=model_name,
            thinking_depth=_coerce_thinking_depth(thinking_depth, disable_thinking),
            event_context=self._build_event_context(
                request_id=request_id,
                event_context=event_context,
            ),
        )

    async def _call_provider_response(
        self,
        *,
        request_context: _LLMRequestContext,
        system_prompt: str,
        messages: list[dict[str, str]],
        temperature: float,
        json_mode: bool,
        timeout_seconds: float | None,
        control: RunControl | None,
    ) -> Any:
        if control is not None and self._cancellable_client is not None:
            result = await self._cancellable_client.call(
                system_prompt=system_prompt,
                messages=messages,
                control=control,
                max_tokens=self._llm_max_tokens(),
                temperature=temperature,
                thinking_depth=request_context.thinking_depth,
                json_mode=json_mode,
                timeout_seconds=timeout_seconds,
                event_context=request_context.event_context,
            )
            return SimpleNamespace(content=result.content, metadata=result.metadata)
        return await self._provider_bridge.chat_response(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=self._llm_max_tokens(),
            temperature=temperature,
            thinking_depth=request_context.thinking_depth,
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
            event_context=request_context.event_context,
        )

    def _open_provider_stream(
        self,
        *,
        request_context: _LLMRequestContext,
        system_prompt: str,
        messages: list[dict[str, str]],
        temperature: float,
        json_mode: bool,
        timeout_seconds: float | None,
        control: RunControl | None,
    ) -> AsyncIterator[LLMStreamEvent]:
        if control is not None and self._cancellable_client is not None:
            return self._cancellable_client.stream(
                system_prompt=system_prompt,
                messages=messages,
                control=control,
                max_tokens=self._llm_max_tokens(),
                temperature=temperature,
                thinking_depth=request_context.thinking_depth,
                json_mode=json_mode,
                timeout_seconds=timeout_seconds,
                event_context=request_context.event_context,
            )
        return self._provider_bridge.chat_response_stream(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=self._llm_max_tokens(),
            temperature=temperature,
            thinking_depth=request_context.thinking_depth,
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
            event_context=request_context.event_context,
        )

    def _log_call_success(
        self,
        request_context: _LLMRequestContext,
        *,
        response: str,
        provider_metadata: dict[str, Any] | None,
        disable_thinking: bool,
    ) -> None:
        duration_ms = int((time.time() - request_context.start_time) * 1000)
        log_llm_response(
            self._llm_logger,
            request_id=request_context.request_id,
            response=response,
            success=True,
            duration_ms=duration_ms,
            provider_metadata=provider_metadata,
        )
        if not response.strip():
            logger.warning(
                "Task-agent LLM returned empty content | request_id=%s model=%s disable_thinking=%s metadata=%s",
                request_context.request_id,
                request_context.model_name,
                disable_thinking,
                provider_metadata,
            )

    def _log_stream_success(
        self,
        request_context: _LLMRequestContext,
        *,
        response: str,
    ) -> None:
        log_llm_response(
            self._llm_logger,
            request_id=request_context.request_id,
            response=response,
            success=True,
            duration_ms=int((time.time() - request_context.start_time) * 1000),
        )

    def _log_failure(self, request_context: _LLMRequestContext, exc: Exception) -> None:
        log_llm_response(
            self._llm_logger,
            request_id=request_context.request_id,
            response="",
            success=False,
            error=str(exc),
            duration_ms=int((time.time() - request_context.start_time) * 1000),
        )

    def _llm_max_tokens(self) -> int:
        try:
            return int(get_config().llm.max_tokens)
        except Exception:
            return DEFAULT_MAX_TOKENS


async def _emit_trace_metrics(
    llm_trace_callback: LLMTraceCallback | None,
    provider_metadata: dict[str, Any] | None,
) -> None:
    trace_metrics = dict((provider_metadata or {}).get("trace_metrics") or {})
    if llm_trace_callback is None or not trace_metrics:
        return
    callback_result = llm_trace_callback(trace_metrics)
    if hasattr(callback_result, "__await__"):
        await callback_result
