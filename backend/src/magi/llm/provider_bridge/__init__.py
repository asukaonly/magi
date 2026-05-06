"""
Provider bridge for provider-specific request/response handling.

This module centralizes API differences between OpenAI-compatible models
(OpenAI/GLM) and Anthropic, so business layers can use one unified interface.
"""

import time
from typing import Any, AsyncIterator, Dict, List, Optional

from ..base import LLMAdapter
from ..concurrency_limiter import LLMConcurrencyLimiter, get_llm_concurrency_limiter
from ..streaming_events import LLMStreamEvent
from .models import (
    ProviderResponse,
    ProviderToolCall,
    ProviderUsage,
    ToolStreamResult,
)
from .options import ProviderBridgeOptionsMixin
from .requests import ProviderBridgeRequestMixin
from .responses import ProviderBridgeResponseMixin
from .streaming import (
    ProviderBridgeChatStreamingMixin,
    ProviderBridgeToolStreamingMixin,
)
from ...config.constants import DEFAULT_MAX_TOKENS, DEFAULT_THINKING_TOKENS
from ...config.models import ThinkingDepth


def _coerce_thinking_depth(
    thinking_depth: ThinkingDepth | None,
    disable_thinking: bool | None,
) -> ThinkingDepth:
    """Resolve a ThinkingDepth from the new or legacy parameter.

    If the caller passed an explicit ``thinking_depth``, use it directly.
    Otherwise fall back to the legacy ``disable_thinking`` boolean:
    ``True`` → NONE, ``False`` / ``None`` → MEDIUM.
    """
    if thinking_depth is not None:
        return thinking_depth
    if disable_thinking is True:
        return ThinkingDepth.NONE
    return ThinkingDepth.MEDIUM


def _compact_trace_preview(value: Any, *, limit: int = 240) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return " ".join(text.split())[:limit]


def _build_request_preview(messages: List[Dict[str, Any]]) -> str:
    for message in reversed(messages or []):
        content = message.get("content") if isinstance(message, dict) else None
        preview = _compact_trace_preview(content)
        if preview:
            return preview
    return ""


def _with_trace_previews(
    event_context: Optional[Dict[str, Any]],
    *,
    messages: List[Dict[str, Any]],
    response_text: Any = None,
) -> Dict[str, Any]:
    context = dict(event_context or {})
    request_preview = _compact_trace_preview(
        context.get("request_preview")
    ) or _build_request_preview(messages)
    response_preview = _compact_trace_preview(
        context.get("response_preview")
    ) or _compact_trace_preview(response_text)
    if request_preview:
        context.setdefault("request_preview", request_preview)
        context.setdefault("input_preview", request_preview)
    if response_preview:
        context.setdefault("response_preview", response_preview)
        context.setdefault("output_preview", response_preview)
    return context


class LLMProviderBridge:
    """Unified entrypoint for provider-specific LLM calls."""

    def __init__(
        self,
        llm_adapter: LLMAdapter,
        concurrency_limiter: LLMConcurrencyLimiter | None = None,
    ):
        self.llm = llm_adapter
        self._concurrency_limiter = concurrency_limiter or get_llm_concurrency_limiter()
        self._operations = _ProviderBridgeOperations(self)

    def is_anthropic(self) -> bool:
        return self._operations.is_anthropic()

    def is_glm(self) -> bool:
        return self._operations.is_glm()

    def normalize_content_response(self, content: Any) -> ProviderResponse:
        return self._operations.normalize_content_response(content)

    def chat_response_stream(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = DEFAULT_THINKING_TOKENS,
        temperature: float = 0.7,
        json_mode: bool = False,
        timeout_seconds: Optional[float] = None,
        event_context: Optional[Dict[str, Any]] = None,
        thinking_depth: ThinkingDepth | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        return self._operations.chat_response_stream(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
            event_context=event_context,
            thinking_depth=thinking_depth,
        )

    async def chat(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = DEFAULT_THINKING_TOKENS,
        temperature: float = 0.7,
        disable_thinking: Optional[bool] = None,
        json_mode: bool = False,
        timeout_seconds: Optional[float] = None,
        event_context: Optional[Dict[str, Any]] = None,
        thinking_depth: ThinkingDepth | None = None,
    ) -> str:
        """
        Unified non-tool chat call with system prompt.
        """
        depth = _coerce_thinking_depth(thinking_depth, disable_thinking)
        response = await self.chat_response(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
            event_context=event_context,
            thinking_depth=depth,
        )
        return response.content

    async def chat_response(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = DEFAULT_THINKING_TOKENS,
        temperature: float = 0.7,
        disable_thinking: Optional[bool] = None,
        json_mode: bool = False,
        timeout_seconds: Optional[float] = None,
        event_context: Optional[Dict[str, Any]] = None,
        thinking_depth: ThinkingDepth | None = None,
    ) -> ProviderResponse:
        """
        Unified plain-chat call that still returns normalized ProviderResponse.
        """
        depth = _coerce_thinking_depth(thinking_depth, disable_thinking)
        started_at = time.time()
        try:
            provider_response = await self._operations._run_with_concurrency_limit(
                request_family="chat",
                limit=self._operations._resolve_chat_concurrency_limit(),
                operation=lambda: self._operations._chat_response_impl(
                    system_prompt=system_prompt,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    thinking_depth=depth,
                    json_mode=json_mode,
                    timeout_seconds=timeout_seconds,
                    event_context=event_context,
                ),
            )

            latency_ms = int((time.time() - started_at) * 1000)
            self._operations._attach_trace_metrics(
                provider_response=provider_response,
                usage=provider_response.usage,
                latency_ms=latency_ms,
                thinking_depth=depth,
            )
            await self._operations._emit_usage_event(
                success=True,
                latency_ms=latency_ms,
                usage=provider_response.usage,
                event_context=_with_trace_previews(
                    event_context,
                    messages=messages,
                    response_text=provider_response.content,
                ),
            )
            return provider_response
        except Exception as exc:
            await self._operations._emit_usage_event(
                success=False,
                latency_ms=int((time.time() - started_at) * 1000),
                usage=None,
                event_context=_with_trace_previews(event_context, messages=messages),
                error=str(exc),
            )
            raise

    async def chat_with_tools(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.7,
        disable_thinking: Optional[bool] = None,
        timeout_seconds: Optional[float] = None,
        event_context: Optional[Dict[str, Any]] = None,
        thinking_depth: ThinkingDepth | None = None,
    ) -> ProviderResponse:
        """
        Unified tool-calling chat call.
        """
        depth = _coerce_thinking_depth(thinking_depth, disable_thinking)
        started_at = time.time()
        try:
            if getattr(self.llm, "_client", None) is None and not self._operations.is_anthropic():
                provider_response = await self.chat_response(
                    system_prompt=system_prompt,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout_seconds=timeout_seconds,
                    event_context=event_context,
                    thinking_depth=depth,
                )
                return provider_response

            provider_response = await self._operations._run_with_concurrency_limit(
                request_family="chat",
                limit=self._operations._resolve_chat_concurrency_limit(),
                operation=lambda: self._operations._chat_with_tools_impl(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=tools,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    thinking_depth=depth,
                    timeout_seconds=timeout_seconds,
                ),
            )

            latency_ms = int((time.time() - started_at) * 1000)
            self._operations._attach_trace_metrics(
                provider_response=provider_response,
                usage=provider_response.usage,
                latency_ms=latency_ms,
                thinking_depth=depth,
            )
            await self._operations._emit_usage_event(
                success=True,
                latency_ms=latency_ms,
                usage=provider_response.usage,
                event_context=_with_trace_previews(
                    event_context,
                    messages=messages,
                    response_text=provider_response.content,
                ),
            )
            return provider_response
        except Exception as exc:
            await self._operations._emit_usage_event(
                success=False,
                latency_ms=int((time.time() - started_at) * 1000),
                usage=None,
                event_context=_with_trace_previews(event_context, messages=messages),
                error=str(exc),
            )
            raise

    async def chat_with_tools_stream(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.7,
        timeout_seconds: Optional[float] = None,
        event_context: Optional[Dict[str, Any]] = None,
        thinking_depth: ThinkingDepth | None = None,
    ) -> ToolStreamResult:
        """Streaming variant of chat_with_tools().

        All events (text deltas, reasoning deltas, tool-call lifecycle,
        usage) are forwarded to the stream sink bound via
        :func:`magi.llm.streaming_events.stream_scope`. If no sink is
        set this behaves like a silent aggregator — the returned
        ``ToolStreamResult`` still contains the complete assembled
        response.
        """
        depth = _coerce_thinking_depth(thinking_depth, None)
        started_at = time.time()
        try:
            result = await self._operations._run_with_concurrency_limit(
                request_family="chat",
                limit=self._operations._resolve_chat_concurrency_limit(),
                operation=lambda: self._operations._chat_with_tools_stream_impl(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=tools,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    thinking_depth=depth,
                    timeout_seconds=timeout_seconds,
                ),
            )

            latency_ms = int((time.time() - started_at) * 1000)
            self._operations._attach_trace_metrics(
                provider_response=result.provider_response,
                usage=result.provider_response.usage,
                latency_ms=latency_ms,
                thinking_depth=depth,
            )
            await self._operations._emit_usage_event(
                success=True,
                latency_ms=latency_ms,
                usage=result.provider_response.usage,
                event_context=_with_trace_previews(
                    event_context,
                    messages=messages,
                    response_text=result.provider_response.content,
                ),
            )
            return result
        except Exception as exc:
            await self._operations._emit_usage_event(
                success=False,
                latency_ms=int((time.time() - started_at) * 1000),
                usage=None,
                event_context=_with_trace_previews(event_context, messages=messages),
                error=str(exc),
            )
            raise


class _ProviderBridgeOperations(
    ProviderBridgeOptionsMixin,
    ProviderBridgeResponseMixin,
    ProviderBridgeRequestMixin,
    ProviderBridgeChatStreamingMixin,
    ProviderBridgeToolStreamingMixin,
):
    def __init__(self, host: LLMProviderBridge):
        self._host = host

    @property
    def llm(self) -> LLMAdapter:
        return self._host.llm

    @property
    def _concurrency_limiter(self) -> LLMConcurrencyLimiter:
        return self._host._concurrency_limiter

    def is_anthropic(self) -> bool:
        override = self._host.__dict__.get("is_anthropic")
        if override is not None:
            return bool(override())
        return super().is_anthropic()

    def is_glm(self) -> bool:
        override = self._host.__dict__.get("is_glm")
        if override is not None:
            return bool(override())
        return super().is_glm()
