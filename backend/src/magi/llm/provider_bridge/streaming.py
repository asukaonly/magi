"""Streaming helpers for provider bridge responses."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, cast

from ..streaming_events import LLMStreamEvent, emit_stream_event
from ..concurrency_limiter import LLMRequestPriority
from .streaming_core import ProviderBridgeStreamingHostProtocol, ThinkTagScrubber
from .tool_streaming import ProviderBridgeToolStreamingMixin
from ...config.constants import DEFAULT_THINKING_TOKENS
from ...config.models import ThinkingDepth
from ...runtime_trace import enrich_event_context_with_turn_trace


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


@dataclass
class _ChatStreamState:
    started_at: float
    usage_data: Any = None
    usage_payload: dict[str, int] | None = None
    usage_for_trace: Any = None
    response_preview_parts: list[str] = field(default_factory=list)


class ProviderBridgeChatStreamingMixin:
    """Stream plain chat responses as normalized LLM stream events."""

    async def chat_response_stream(
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
        """Streaming variant of chat_response()."""
        host = cast(ProviderBridgeStreamingHostProtocol, self)
        event_context = host._with_cache_observation(
            event_context,
            system_prompt=system_prompt,
            tools=[],
        )
        event_context = enrich_event_context_with_turn_trace(event_context)
        depth = thinking_depth if thinking_depth is not None else ThinkingDepth.MEDIUM
        state = _ChatStreamState(started_at=time.time())

        async with host._limit_concurrency(
            request_family="chat",
            limit=host._resolve_chat_concurrency_limit(),
            priority=priority,
        ):
            if host.is_anthropic():
                async for event_payload in self._stream_anthropic_chat_response(
                    host,
                    system_prompt=system_prompt,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout_seconds=timeout_seconds,
                    thinking_depth=depth,
                    state=state,
                ):
                    yield event_payload
            else:
                async for event_payload in self._stream_openai_chat_response(
                    host,
                    system_prompt=system_prompt,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    json_mode=json_mode,
                    timeout_seconds=timeout_seconds,
                    thinking_depth=depth,
                    event_context=event_context,
                    state=state,
                ):
                    yield event_payload

            await self._finish_chat_response_stream(
                host,
                messages=messages,
                event_context=event_context,
                state=state,
            )
            done_event = LLMStreamEvent(kind="done")
            await emit_stream_event(done_event)
            yield done_event

    async def _stream_anthropic_chat_response(
        self,
        host: ProviderBridgeStreamingHostProtocol,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        timeout_seconds: Optional[float],
        thinking_depth: ThinkingDepth,
        state: _ChatStreamState,
    ) -> AsyncIterator[LLMStreamEvent]:
        anthropic_kwargs = self._build_anthropic_chat_stream_kwargs(
            host,
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
            thinking_depth=thinking_depth,
        )
        stream = await host.llm._client.messages.create(**anthropic_kwargs)
        in_thinking = False
        async for event in stream:
            event_payload, in_thinking = self._anthropic_chat_event_to_payload(
                event,
                state=state,
                in_thinking=in_thinking,
            )
            if event_payload is not None:
                await emit_stream_event(event_payload)
                yield event_payload

        state.usage_for_trace = host._extract_anthropic_stream_usage(stream, state.usage_data)
        state.usage_payload = host._anthropic_usage_to_wire(state.usage_data)
        if state.usage_payload is not None:
            usage_event = LLMStreamEvent(kind="usage", usage=state.usage_payload)
            await emit_stream_event(usage_event)
            yield usage_event

    @staticmethod
    def _build_anthropic_chat_stream_kwargs(
        host: ProviderBridgeStreamingHostProtocol,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        timeout_seconds: Optional[float],
        thinking_depth: ThinkingDepth,
    ) -> Dict[str, Any]:
        api_messages = host._convert_messages_to_anthropic(messages)
        api_messages = host._mark_message_cache_breakpoints(messages, api_messages)
        anthropic_kwargs: Dict[str, Any] = {
            "model": host.llm.model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": host._cache_marked_system(system_prompt),
            "messages": api_messages,
            "stream": True,
        }
        if timeout_seconds is not None:
            anthropic_kwargs["timeout"] = timeout_seconds
        return host._apply_provider_options(anthropic_kwargs, thinking_depth)

    @staticmethod
    def _anthropic_chat_event_to_payload(
        event: Any,
        *,
        state: _ChatStreamState,
        in_thinking: bool,
    ) -> tuple[LLMStreamEvent | None, bool]:
        event_type = getattr(event, "type", None)
        if event_type == "content_block_start":
            block = getattr(event, "content_block", None)
            block_type = getattr(block, "type", None) if block is not None else None
            return None, block_type == "thinking"
        if event_type == "content_block_delta":
            return (
                _anthropic_delta_to_payload(event.delta, state, in_thinking),
                in_thinking,
            )
        if event_type == "content_block_stop":
            return None, False
        if event_type == "message_delta":
            state.usage_data = getattr(event, "usage", state.usage_data)
            return None, in_thinking
        if event_type == "message_start":
            message = getattr(event, "message", None)
            if message is not None:
                state.usage_data = getattr(message, "usage", state.usage_data)
        return None, in_thinking

    async def _stream_openai_chat_response(
        self,
        host: ProviderBridgeStreamingHostProtocol,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        json_mode: bool,
        timeout_seconds: Optional[float],
        thinking_depth: ThinkingDepth,
        event_context: Optional[Dict[str, Any]],
        state: _ChatStreamState,
    ) -> AsyncIterator[LLMStreamEvent]:
        chat_kwargs = self._build_openai_chat_stream_kwargs(
            host,
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
            thinking_depth=thinking_depth,
            event_context=event_context,
        )
        if getattr(host.llm, "_client", None) is not None:
            chat_kwargs["model"] = host.llm.model_name
            async for event_payload in self._stream_openai_client_chat(host, chat_kwargs, state):
                yield event_payload
            return

        async for event_payload in self._stream_openai_adapter_chat(host, chat_kwargs, state):
            yield event_payload

    @staticmethod
    def _build_openai_chat_stream_kwargs(
        host: ProviderBridgeStreamingHostProtocol,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        json_mode: bool,
        timeout_seconds: Optional[float],
        thinking_depth: ThinkingDepth,
        event_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        openai_messages = host._mark_message_cache_breakpoints(
            messages, host._convert_messages_to_openai(messages)
        )
        full_messages = [
            {"role": "system", "content": host._cache_marked_system(system_prompt)}
        ] + openai_messages
        chat_kwargs: Dict[str, Any] = {
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if json_mode:
            chat_kwargs["response_format"] = {"type": "json_object"}
        if timeout_seconds is not None:
            chat_kwargs["timeout"] = timeout_seconds
        chat_kwargs = host._apply_provider_options(chat_kwargs, thinking_depth)
        return host._apply_cache_routing(chat_kwargs, event_context)

    async def _stream_openai_client_chat(
        self,
        host: ProviderBridgeStreamingHostProtocol,
        chat_kwargs: Dict[str, Any],
        state: _ChatStreamState,
    ) -> AsyncIterator[LLMStreamEvent]:
        stream = await host.llm._client.chat.completions.create(**chat_kwargs)
        scrubber = ThinkTagScrubber()
        async for chunk in stream:
            for event_payload in self._openai_chunk_to_payloads(
                chunk, state=state, scrubber=scrubber
            ):
                await emit_stream_event(event_payload)
                yield event_payload

        for event_payload in _flush_openai_scrubber(scrubber, state):
            await emit_stream_event(event_payload)
            yield event_payload
        state.usage_for_trace = host._extract_openai_stream_usage(state.usage_data)
        state.usage_payload = host._openai_usage_to_wire(state.usage_data)
        if state.usage_payload is not None:
            usage_event = LLMStreamEvent(kind="usage", usage=state.usage_payload)
            await emit_stream_event(usage_event)
            yield usage_event

    @staticmethod
    def _openai_chunk_to_payloads(
        chunk: Any,
        *,
        state: _ChatStreamState,
        scrubber: ThinkTagScrubber,
    ) -> list[LLMStreamEvent]:
        if not getattr(chunk, "choices", None):
            if hasattr(chunk, "usage") and chunk.usage is not None:
                state.usage_data = chunk.usage
            return []
        delta = chunk.choices[0].delta
        if delta is None:
            return []

        events = _openai_reasoning_payloads(delta)
        content = getattr(delta, "content", None)
        if content:
            events.extend(_openai_visible_content_payloads(content, state, scrubber))
        if hasattr(chunk, "usage") and chunk.usage is not None:
            state.usage_data = chunk.usage
        return events

    @staticmethod
    async def _stream_openai_adapter_chat(
        host: ProviderBridgeStreamingHostProtocol,
        chat_kwargs: Dict[str, Any],
        state: _ChatStreamState,
    ) -> AsyncIterator[LLMStreamEvent]:
        content = await host.llm.chat(**chat_kwargs)
        if not content:
            return
        scrubber = ThinkTagScrubber()
        visible, reasoning_leak = scrubber.feed(content)
        tail_visible, tail_reasoning = scrubber.flush()
        visible = visible + tail_visible
        reasoning_leak = reasoning_leak + tail_reasoning
        if reasoning_leak:
            event_payload = LLMStreamEvent(kind="reasoning_delta", text=reasoning_leak)
            await emit_stream_event(event_payload)
            yield event_payload
        if visible:
            state.response_preview_parts.append(visible)
            event_payload = LLMStreamEvent(kind="text_delta", text=visible)
            await emit_stream_event(event_payload)
            yield event_payload

    async def _finish_chat_response_stream(
        self,
        host: ProviderBridgeStreamingHostProtocol,
        *,
        messages: List[Dict[str, Any]],
        event_context: Optional[Dict[str, Any]],
        state: _ChatStreamState,
    ) -> Dict[str, Any]:
        event_context = dict(event_context or {})
        request_preview = _compact_trace_preview(
            event_context.get("request_preview")
        ) or _build_request_preview(messages)
        response_preview = _compact_trace_preview(
            event_context.get("response_preview")
        ) or _compact_trace_preview("".join(state.response_preview_parts))
        if request_preview:
            event_context.setdefault("request_preview", request_preview)
            event_context.setdefault("input_preview", request_preview)
        if response_preview:
            event_context.setdefault("response_preview", response_preview)
            event_context.setdefault("output_preview", response_preview)
        await host._emit_usage_event(
            success=True,
            latency_ms=int((time.time() - state.started_at) * 1000),
            usage=state.usage_for_trace or state.usage_payload,
            event_context=event_context,
        )
        return event_context


def _anthropic_delta_to_payload(
    delta: Any,
    state: _ChatStreamState,
    in_thinking: bool,
) -> LLMStreamEvent | None:
    delta_type = getattr(delta, "type", None)
    if delta_type == "thinking_delta":
        text = getattr(delta, "thinking", None) or getattr(delta, "text", None)
        return LLMStreamEvent(kind="reasoning_delta", text=text) if text else None
    if in_thinking and getattr(delta, "text", None):
        return LLMStreamEvent(kind="reasoning_delta", text=delta.text)
    if getattr(delta, "text", None):
        state.response_preview_parts.append(delta.text)
        return LLMStreamEvent(kind="text_delta", text=delta.text)
    return None


def _openai_reasoning_payloads(delta: Any) -> list[LLMStreamEvent]:
    reasoning_text = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
    if not reasoning_text:
        return []
    return [LLMStreamEvent(kind="reasoning_delta", text=reasoning_text)]


def _openai_visible_content_payloads(
    content: str,
    state: _ChatStreamState,
    scrubber: ThinkTagScrubber,
) -> list[LLMStreamEvent]:
    visible, reasoning_leak = scrubber.feed(content)
    events: list[LLMStreamEvent] = []
    if reasoning_leak:
        events.append(LLMStreamEvent(kind="reasoning_delta", text=reasoning_leak))
    if visible:
        state.response_preview_parts.append(visible)
        events.append(LLMStreamEvent(kind="text_delta", text=visible))
    return events


def _flush_openai_scrubber(
    scrubber: ThinkTagScrubber,
    state: _ChatStreamState,
) -> list[LLMStreamEvent]:
    tail_visible, tail_reasoning = scrubber.flush()
    events: list[LLMStreamEvent] = []
    if tail_reasoning:
        events.append(LLMStreamEvent(kind="reasoning_delta", text=tail_reasoning))
    if tail_visible:
        state.response_preview_parts.append(tail_visible)
        events.append(LLMStreamEvent(kind="text_delta", text=tail_visible))
    return events


__all__ = [
    "ProviderBridgeChatStreamingMixin",
    "ProviderBridgeToolStreamingMixin",
    "ThinkTagScrubber",
]
