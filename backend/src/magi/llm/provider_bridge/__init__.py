"""
Provider bridge for provider-specific request/response handling.

This module centralizes API differences between OpenAI-compatible models
(OpenAI/GLM) and Anthropic, so business layers can use one unified interface.
"""

import time
from typing import Any, AsyncIterator, Dict, List, Optional

from ..base import LLMAdapter
from ..concurrency_limiter import (
    LLMConcurrencyLimiter,
    LLMRequestPriority,
    get_llm_concurrency_limiter,
)
from ..streaming_events import LLMStreamEvent
from .models import (
    ProviderResponse,
    ProviderToolCall as ProviderToolCall,
    ProviderUsage as ProviderUsage,
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


def _build_tool_call_preview(tool_calls: Any) -> str:
    names: list[str] = []
    for tool_call in list(tool_calls or []):
        name = getattr(tool_call, "name", None)
        if not name and isinstance(tool_call, dict):
            name = tool_call.get("name")
        text = str(name or "").strip()
        if text:
            names.append(text)
    if not names:
        return ""
    return f"Requested tools: {', '.join(names)}"


def _with_trace_previews(
    event_context: Optional[Dict[str, Any]],
    *,
    messages: List[Dict[str, Any]],
    response_text: Any = None,
    tool_calls: Any = None,
) -> Dict[str, Any]:
    context = dict(event_context or {})
    request_preview = _compact_trace_preview(
        context.get("request_preview")
    ) or _build_request_preview(messages)
    response_preview = (
        _compact_trace_preview(context.get("response_preview"))
        or _compact_trace_preview(response_text)
        or _build_tool_call_preview(tool_calls)
    )
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
        priority: LLMRequestPriority | str | int | None = LLMRequestPriority.HIGH,
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
            priority=priority,
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
        priority: LLMRequestPriority | str | int | None = LLMRequestPriority.HIGH,
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
            priority=priority,
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
        cache_system: bool = False,
        priority: LLMRequestPriority | str | int | None = LLMRequestPriority.HIGH,
    ) -> ProviderResponse:
        """
        Unified plain-chat call that still returns normalized ProviderResponse.

        ``cache_system=True`` marks the whole (byte-stable) system prompt as a
        cacheable block for marker vendors — for auxiliary calls (routing, memory
        extraction) whose system prompt is a constant but carries no renderer
        cache boundary.
        """
        depth = _coerce_thinking_depth(thinking_depth, disable_thinking)
        event_context = self._plain_chat_event_context(
            event_context,
            system_prompt=system_prompt,
            messages=messages,
            cache_system=cache_system,
        )
        started_at = time.time()
        try:
            provider_response = await self._run_plain_chat_response(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                thinking_depth=depth,
                json_mode=json_mode,
                timeout_seconds=timeout_seconds,
                event_context=event_context,
                cache_system=cache_system,
                priority=priority,
            )
            await self._record_plain_chat_success(
                provider_response, started_at, depth, event_context, messages
            )
            return provider_response
        except Exception as exc:
            await self._record_plain_chat_failure(
                exc, started_at, event_context, messages
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
        priority: LLMRequestPriority | str | int | None = LLMRequestPriority.HIGH,
    ) -> ProviderResponse:
        """Unified tool-calling chat call."""
        depth = _coerce_thinking_depth(thinking_depth, disable_thinking)
        event_context = self._tool_event_context(
            event_context,
            system_prompt,
            tools,
            messages,
        )
        started_at = time.time()
        try:
            if self._should_fallback_to_chat_response():
                return await self._chat_response_for_tool_fallback(
                    system_prompt=system_prompt,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout_seconds=timeout_seconds,
                    event_context=event_context,
                    thinking_depth=depth,
                    priority=priority,
                )

            provider_response = await self._run_chat_with_tools(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                thinking_depth=depth,
                timeout_seconds=timeout_seconds,
                event_context=event_context,
                priority=priority,
            )
            await self._record_chat_with_tools_success(
                provider_response, started_at, depth, event_context, messages
            )
            return provider_response
        except Exception as exc:
            await self._record_chat_with_tools_failure(
                exc, started_at, event_context, messages
            )
            raise

    def _should_fallback_to_chat_response(self) -> bool:
        if getattr(self.llm, "is_plugin_provider", False) is True:
            return False
        return (
            getattr(self.llm, "_client", None) is None
            and not self._operations.is_anthropic()
        )

    def _tool_event_context(
        self,
        event_context: Optional[Dict[str, Any]],
        system_prompt: str,
        tools: List[Dict[str, Any]],
        messages: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        return self._operations._with_cache_observation(
            event_context,
            system_prompt=system_prompt,
            tools=tools,
            messages=messages,
        )

    def _plain_chat_event_context(
        self,
        event_context: Optional[Dict[str, Any]],
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        cache_system: bool,
    ) -> Optional[Dict[str, Any]]:
        return self._operations._with_cache_observation(
            event_context,
            system_prompt=system_prompt,
            tools=[],
            messages=messages,
            cache_whole_system=cache_system,
        )

    async def _run_plain_chat_response(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        thinking_depth: ThinkingDepth,
        json_mode: bool,
        timeout_seconds: Optional[float],
        event_context: Optional[Dict[str, Any]],
        cache_system: bool,
        priority: LLMRequestPriority | str | int | None,
    ) -> ProviderResponse:
        return await self._operations._run_with_concurrency_limit(
            request_family="chat",
            limit=self._operations._resolve_chat_concurrency_limit(),
            priority=priority,
            operation=lambda: self._operations._chat_response_impl(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                thinking_depth=thinking_depth,
                json_mode=json_mode,
                timeout_seconds=timeout_seconds,
                event_context=event_context,
                cache_system=cache_system,
            ),
        )

    async def _record_plain_chat_success(
        self,
        provider_response: ProviderResponse,
        started_at: float,
        thinking_depth: ThinkingDepth,
        event_context: Optional[Dict[str, Any]],
        messages: List[Dict[str, Any]],
    ) -> None:
        latency_ms = int((time.time() - started_at) * 1000)
        self._operations._attach_trace_metrics(
            provider_response=provider_response,
            usage=provider_response.usage,
            latency_ms=latency_ms,
            thinking_depth=thinking_depth,
        )
        await self._operations._emit_usage_event(
            success=True,
            latency_ms=latency_ms,
            usage=provider_response.usage,
            event_context=_with_trace_previews(
                event_context,
                messages=messages,
                response_text=provider_response.content,
                tool_calls=provider_response.tool_calls,
            ),
        )

    async def _record_plain_chat_failure(
        self,
        exc: Exception,
        started_at: float,
        event_context: Optional[Dict[str, Any]],
        messages: List[Dict[str, Any]],
    ) -> None:
        await self._operations._emit_usage_event(
            success=False,
            latency_ms=int((time.time() - started_at) * 1000),
            usage=None,
            event_context=_with_trace_previews(event_context, messages=messages),
            error=str(exc),
        )

    async def _chat_response_for_tool_fallback(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        timeout_seconds: Optional[float],
        event_context: Optional[Dict[str, Any]],
        thinking_depth: ThinkingDepth,
        priority: LLMRequestPriority | str | int | None = LLMRequestPriority.HIGH,
    ) -> ProviderResponse:
        return await self.chat_response(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
            event_context=event_context,
            thinking_depth=thinking_depth,
            priority=priority,
        )

    async def _run_chat_with_tools(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        thinking_depth: ThinkingDepth,
        timeout_seconds: Optional[float],
        event_context: Optional[Dict[str, Any]],
        priority: LLMRequestPriority | str | int | None,
    ) -> ProviderResponse:
        return await self._operations._run_with_concurrency_limit(
            request_family="chat",
            limit=self._operations._resolve_chat_concurrency_limit(),
            priority=priority,
            operation=lambda: self._operations._chat_with_tools_impl(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                thinking_depth=thinking_depth,
                timeout_seconds=timeout_seconds,
                event_context=event_context,
            ),
        )

    async def _record_chat_with_tools_success(
        self,
        provider_response: ProviderResponse,
        started_at: float,
        thinking_depth: ThinkingDepth,
        event_context: Optional[Dict[str, Any]],
        messages: List[Dict[str, Any]],
    ) -> None:
        latency_ms = int((time.time() - started_at) * 1000)
        self._operations._attach_trace_metrics(
            provider_response=provider_response,
            usage=provider_response.usage,
            latency_ms=latency_ms,
            thinking_depth=thinking_depth,
        )
        await self._operations._emit_usage_event(
            success=True,
            latency_ms=latency_ms,
            usage=provider_response.usage,
            event_context=_with_trace_previews(
                event_context,
                messages=messages,
                response_text=provider_response.content,
                tool_calls=provider_response.tool_calls,
            ),
        )

    async def _record_chat_with_tools_failure(
        self,
        exc: Exception,
        started_at: float,
        event_context: Optional[Dict[str, Any]],
        messages: List[Dict[str, Any]],
    ) -> None:
        await self._operations._emit_usage_event(
            success=False,
            latency_ms=int((time.time() - started_at) * 1000),
            usage=None,
            event_context=_with_trace_previews(event_context, messages=messages),
            error=str(exc),
        )

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
        priority: LLMRequestPriority | str | int | None = LLMRequestPriority.HIGH,
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
        event_context = self._tool_event_context(
            event_context,
            system_prompt,
            tools,
            messages,
        )
        started_at = time.time()
        try:
            result = await self._run_chat_with_tools_stream(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                thinking_depth=depth,
                timeout_seconds=timeout_seconds,
                event_context=event_context,
                priority=priority,
            )
            await self._record_chat_with_tools_success(
                result.provider_response, started_at, depth, event_context, messages
            )
            return result
        except Exception as exc:
            await self._record_chat_with_tools_failure(
                exc, started_at, event_context, messages
            )
            raise

    async def _run_chat_with_tools_stream(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        thinking_depth: ThinkingDepth,
        timeout_seconds: Optional[float],
        event_context: Optional[Dict[str, Any]],
        priority: LLMRequestPriority | str | int | None,
    ) -> ToolStreamResult:
        return await self._operations._run_with_concurrency_limit(
            request_family="chat",
            limit=self._operations._resolve_chat_concurrency_limit(),
            priority=priority,
            operation=lambda: self._operations._chat_with_tools_stream_impl(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                thinking_depth=thinking_depth,
                timeout_seconds=timeout_seconds,
                event_context=event_context,
            ),
        )


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
