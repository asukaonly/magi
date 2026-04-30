"""LLM invocation helpers for function-calling execution."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Dict, List, Optional, Protocol, cast

from ....config.constants import DEFAULT_MAX_TOKENS
from ....config.models import ThinkingDepth
from ....llm.base import LLMAdapter
from ....llm.provider_bridge import LLMProviderBridge, ToolStreamResult
from ....llm.streaming_events import get_stream_sink
from ....utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response
from ..context_compactor import ContextCompactor
from .types import ToolCall

logger = logging.getLogger(__name__)
llm_logger = get_llm_logger("function_calling")

THINKING_LLM_TIMEOUT_SECONDS = 180.0


class _LlmHostProtocol(Protocol):
    provider_bridge: LLMProviderBridge
    _context_compactor: ContextCompactor

    def _resolve_llm(self) -> LLMAdapter: ...

    async def _invoke_with_rate_limit_backoff(
        self,
        factory: Callable[[], Awaitable[Any]],
        *,
        label: str,
    ) -> Any: ...


class FunctionCallingLlmMixin:
    """Call the configured LLM for tool and final-response turns."""

    async def _call_llm_with_tools(
        self,
        system_prompt: str,
        messages: List[Dict],
        tools: List[Dict],
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
        timeout_seconds: Optional[float] = None,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        intent: str = "unknown",
        execution_agent_id: str = "chat_agent",
    ) -> Dict[str, Any]:
        """
        Call LLM with tools parameter

        Returns dict with either:
        - content: str (text response)
        - tool_calls: List[ToolCall] (tool calls to execute)
        """
        host = cast(_LlmHostProtocol, self)
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        llm = host._resolve_llm()
        model_name = llm.model_name

        log_llm_request(
            llm_logger,
            request_id=request_id,
            model=model_name,
            system_prompt=system_prompt,
            messages=messages,
            tool_count=len(tools),
            tool_names=[str(t.get("function", {}).get("name", "")) for t in tools],
        )

        try:
            streamed = False
            if get_stream_sink() is not None:
                stream_result: ToolStreamResult = await host._invoke_with_rate_limit_backoff(
                    lambda: host.provider_bridge.chat_with_tools_stream(
                        system_prompt=system_prompt,
                        messages=messages,
                        tools=tools,
                        max_tokens=DEFAULT_MAX_TOKENS,
                        temperature=0.7,
                        thinking_depth=thinking_depth,
                        timeout_seconds=self._resolve_llm_timeout(timeout_seconds, thinking_depth=thinking_depth),
                        event_context={
                            "request_id": request_id,
                            "request_kind": "function_calling:tools",
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "agent_id": execution_agent_id,
                            "correlation_id": turn_id,
                            "intent": intent,
                        },
                    ),
                    label="chat_with_tools_stream",
                )
                provider_response = stream_result.provider_response
                streamed = not stream_result.has_tool_calls and stream_result.text_chunks_emitted > 0
            else:
                provider_response = await host._invoke_with_rate_limit_backoff(
                    lambda: host.provider_bridge.chat_with_tools(
                        system_prompt=system_prompt,
                        messages=messages,
                        tools=tools,
                        max_tokens=DEFAULT_MAX_TOKENS,
                        temperature=0.7,
                        thinking_depth=thinking_depth,
                        timeout_seconds=self._resolve_llm_timeout(timeout_seconds, thinking_depth=thinking_depth),
                        event_context={
                            "request_id": request_id,
                            "request_kind": "function_calling:tools",
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "agent_id": execution_agent_id,
                            "correlation_id": turn_id,
                            "intent": intent,
                        },
                    ),
                    label="chat_with_tools",
                )

            duration_ms = int((time.time() - start_time) * 1000)
            result: Dict[str, Any] = {"content": provider_response.content}
            result["llm_trace"] = self._build_llm_trace(
                metadata=provider_response.metadata,
                thinking_depth=thinking_depth,
                duration_ms=duration_ms,
                model_name=model_name,
                provider_name=llm.provider_name,
            )
            host._context_compactor.record_input_tokens(
                int(result["llm_trace"].get("input_tokens") or 0)
            )
            context_usage = host._context_compactor.get_usage()
            if context_usage is not None:
                result["context_usage"] = context_usage
            if provider_response.assistant_message:
                result["assistant_message"] = provider_response.assistant_message
            if provider_response.tool_calls:
                result["tool_calls"] = [
                    ToolCall(
                        id=tc.id,
                        name=tc.name,
                        arguments=tc.arguments,
                    )
                    for tc in provider_response.tool_calls
                ]
            if streamed:
                result["streamed"] = True

            log_llm_response(
                llm_logger,
                request_id=request_id,
                response=json.dumps(result, ensure_ascii=False, default=str),
                success=True,
                duration_ms=duration_ms,
            )
            return result

        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response="",
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )
            logger.error(f"[FunctionCalling] LLM call failed: {exc}")
            try:
                tools_blob = json.dumps(tools, ensure_ascii=False, default=str)
                logger.error(
                    "[FunctionCalling] LLM call failed | request_id=%s | model=%s | tools=%s",
                    request_id,
                    model_name,
                    tools_blob if len(tools_blob) <= 8000 else tools_blob[:8000] + "...",
                )
            except Exception:  # pragma: no cover - logging must not mask the original error
                pass
            raise

    async def _call_llm_without_tools(
        self,
        system_prompt: str,
        messages: List[Dict],
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
        json_mode: bool = False,
        timeout_seconds: Optional[float] = None,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        intent: str = "unknown",
        execution_agent_id: str = "chat_agent",
    ) -> Dict[str, Any]:
        """Call LLM without tools for final response"""
        host = cast(_LlmHostProtocol, self)
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        llm = host._resolve_llm()
        model_name = llm.model_name

        log_llm_request(
            llm_logger,
            request_id=request_id,
            model=model_name,
            system_prompt=system_prompt,
            messages=messages,
        )

        try:
            streamed = False
            if get_stream_sink() is not None and not json_mode:
                chunks: List[str] = []
                async for event in host.provider_bridge.chat_response_stream(
                    system_prompt=system_prompt,
                    messages=messages,
                    max_tokens=DEFAULT_MAX_TOKENS,
                    temperature=0.7,
                    thinking_depth=thinking_depth,
                    timeout_seconds=self._resolve_llm_timeout(timeout_seconds, thinking_depth=thinking_depth),
                ):
                    if event.kind == "text_delta" and event.text:
                        chunks.append(event.text)
                content = "".join(chunks)
                streamed = True
                provider_response = None
            else:
                provider_response = await host._invoke_with_rate_limit_backoff(
                    lambda: host.provider_bridge.chat_response(
                        system_prompt=system_prompt,
                        messages=messages,
                        max_tokens=DEFAULT_MAX_TOKENS,
                        temperature=0.7,
                        thinking_depth=thinking_depth,
                        json_mode=json_mode,
                        timeout_seconds=self._resolve_llm_timeout(timeout_seconds, thinking_depth=thinking_depth),
                        event_context={
                            "request_id": request_id,
                            "request_kind": "function_calling:final_response",
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "agent_id": execution_agent_id,
                            "correlation_id": turn_id,
                            "intent": intent,
                        },
                    ),
                    label="chat_response",
                )
                content = provider_response.content

            duration_ms = int((time.time() - start_time) * 1000)
            metadata = dict((provider_response.metadata if provider_response else None) or {})
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response=content,
                success=True,
                duration_ms=duration_ms,
                fallback_reason="function_calling_final_response_without_tools",
                **metadata,
            )
            result: Dict[str, Any] = {"content": content}
            result["llm_trace"] = self._build_llm_trace(
                metadata=provider_response.metadata if provider_response else None,
                thinking_depth=thinking_depth,
                duration_ms=duration_ms,
                model_name=model_name,
                provider_name=llm.provider_name,
            )
            host._context_compactor.record_input_tokens(
                int(result["llm_trace"].get("input_tokens") or 0)
            )
            context_usage = host._context_compactor.get_usage()
            if context_usage is not None:
                result["context_usage"] = context_usage
            if provider_response is not None and provider_response.assistant_message:
                result["assistant_message"] = provider_response.assistant_message
            if provider_response is not None and provider_response.tool_calls:
                result["tool_calls"] = [
                    ToolCall(
                        id=tc.id,
                        name=tc.name,
                        arguments=tc.arguments,
                    )
                    for tc in provider_response.tool_calls
                ]
            if streamed:
                result["streamed"] = True
            return result
        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response="",
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
                fallback_reason="function_calling_final_response_without_tools",
            )
            raise

    @staticmethod
    def _resolve_llm_timeout(
        timeout_seconds: Optional[float],
        *,
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
    ) -> Optional[float]:
        if timeout_seconds is not None:
            return timeout_seconds
        if thinking_depth not in (ThinkingDepth.NONE, ThinkingDepth.LOW):
            return THINKING_LLM_TIMEOUT_SECONDS
        return None

    def _build_llm_trace(
        self,
        *,
        metadata: Dict[str, Any] | None,
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
        duration_ms: int,
        model_name: str,
        provider_name: str,
    ) -> Dict[str, Any]:
        trace_metrics = dict((metadata or {}).get("trace_metrics") or {})
        trace_metrics.setdefault("provider", provider_name)
        trace_metrics.setdefault("model", model_name)
        trace_metrics.setdefault("input_tokens", 0)
        trace_metrics.setdefault("output_tokens", 0)
        trace_metrics.setdefault("total_tokens", 0)
        trace_metrics.setdefault("reasoning_tokens", 0)
        trace_metrics.setdefault("cache_read_tokens", 0)
        trace_metrics.setdefault("cache_write_tokens", 0)
        trace_metrics.setdefault("thinking_enabled", thinking_depth not in (ThinkingDepth.NONE, ThinkingDepth.LOW))
        trace_metrics.setdefault("thinking_depth", thinking_depth.value)
        trace_metrics.setdefault("duration_ms", duration_ms)
        return trace_metrics
