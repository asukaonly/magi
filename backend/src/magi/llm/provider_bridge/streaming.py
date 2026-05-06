"""Streaming helpers for provider bridge responses."""

from __future__ import annotations

import time
from typing import Any, AsyncIterator, Dict, List, Optional, cast

from ..streaming_events import LLMStreamEvent, emit_stream_event
from .streaming_core import ProviderBridgeStreamingHostProtocol, ThinkTagScrubber
from .tool_streaming import ProviderBridgeToolStreamingMixin
from ...config.constants import DEFAULT_THINKING_TOKENS
from ...config.models import ThinkingDepth
from ...events.tracing import current_trace_context
from ...runtime_trace import enrich_event_context_with_turn_trace


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
    ) -> AsyncIterator[LLMStreamEvent]:
        """Streaming variant of chat_response()."""
        host = cast(ProviderBridgeStreamingHostProtocol, self)
        event_context = enrich_event_context_with_turn_trace(event_context)
        depth = thinking_depth if thinking_depth is not None else ThinkingDepth.MEDIUM
        started_at = time.time()
        usage_data: Any = None
        usage_payload: dict[str, int] | None = None
        if host.is_anthropic():
            api_messages = host._convert_messages_to_anthropic(messages)
            anthropic_kwargs: Dict[str, Any] = {
                "model": host.llm.model_name,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_prompt,
                "messages": api_messages,
                "stream": True,
            }
            if timeout_seconds is not None:
                anthropic_kwargs["timeout"] = timeout_seconds
            anthropic_kwargs = host._apply_provider_options(anthropic_kwargs, depth)
            stream = await host.llm._client.messages.create(**anthropic_kwargs)
            in_thinking = False
            async for event in stream:
                event_type = getattr(event, "type", None)
                if event_type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    block_type = getattr(block, "type", None) if block is not None else None
                    in_thinking = block_type == "thinking"
                elif event_type == "content_block_delta":
                    delta = event.delta
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "thinking_delta":
                        text = getattr(delta, "thinking", None) or getattr(delta, "text", None)
                        if text:
                            event_payload = LLMStreamEvent(kind="reasoning_delta", text=text)
                            await emit_stream_event(event_payload)
                            yield event_payload
                    elif in_thinking and getattr(delta, "text", None):
                        event_payload = LLMStreamEvent(kind="reasoning_delta", text=delta.text)
                        await emit_stream_event(event_payload)
                        yield event_payload
                    elif getattr(delta, "text", None):
                        event_payload = LLMStreamEvent(kind="text_delta", text=delta.text)
                        await emit_stream_event(event_payload)
                        yield event_payload
                elif event_type == "content_block_stop":
                    in_thinking = False
                elif event_type == "message_delta":
                    usage_data = getattr(event, "usage", usage_data)
                elif event_type == "message_start":
                    message = getattr(event, "message", None)
                    if message is not None:
                        usage_data = getattr(message, "usage", usage_data)
            usage_payload = host._anthropic_usage_to_wire(usage_data)
            if usage_payload is not None:
                usage_event = LLMStreamEvent(kind="usage", usage=usage_payload)
                await emit_stream_event(usage_event)
                yield usage_event
        else:
            full_messages = [{"role": "system", "content": system_prompt}] + host._convert_messages_to_openai(messages)
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
            chat_kwargs = host._apply_provider_options(chat_kwargs, depth)
            if getattr(host.llm, "_client", None) is not None:
                chat_kwargs["model"] = host.llm.model_name
                stream = await host.llm._client.chat.completions.create(**chat_kwargs)
                scrubber = ThinkTagScrubber()
                async for chunk in stream:
                    if not getattr(chunk, "choices", None):
                        if hasattr(chunk, "usage") and chunk.usage is not None:
                            usage_data = chunk.usage
                        continue
                    delta = chunk.choices[0].delta
                    if delta is None:
                        continue
                    reasoning_text = (
                        getattr(delta, "reasoning_content", None)
                        or getattr(delta, "reasoning", None)
                    )
                    if reasoning_text:
                        event_payload = LLMStreamEvent(kind="reasoning_delta", text=reasoning_text)
                        await emit_stream_event(event_payload)
                        yield event_payload
                    content = getattr(delta, "content", None)
                    if content:
                        visible, reasoning_leak = scrubber.feed(content)
                        if reasoning_leak:
                            event_payload = LLMStreamEvent(kind="reasoning_delta", text=reasoning_leak)
                            await emit_stream_event(event_payload)
                            yield event_payload
                        if visible:
                            event_payload = LLMStreamEvent(kind="text_delta", text=visible)
                            await emit_stream_event(event_payload)
                            yield event_payload
                    if hasattr(chunk, "usage") and chunk.usage is not None:
                        usage_data = chunk.usage
                tail_visible, tail_reasoning = scrubber.flush()
                if tail_reasoning:
                    event_payload = LLMStreamEvent(kind="reasoning_delta", text=tail_reasoning)
                    await emit_stream_event(event_payload)
                    yield event_payload
                if tail_visible:
                    event_payload = LLMStreamEvent(kind="text_delta", text=tail_visible)
                    await emit_stream_event(event_payload)
                    yield event_payload
                usage_payload = host._openai_usage_to_wire(usage_data)
                if usage_payload is not None:
                    usage_event = LLMStreamEvent(kind="usage", usage=usage_payload)
                    await emit_stream_event(usage_event)
                    yield usage_event
            else:
                content = await host.llm.chat(**chat_kwargs)
                if content:
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
                        event_payload = LLMStreamEvent(kind="text_delta", text=visible)
                        await emit_stream_event(event_payload)
                        yield event_payload
        if current_trace_context() is not None or event_context.get("trace_id"):
            await host._emit_usage_event(
                success=True,
                latency_ms=int((time.time() - started_at) * 1000),
                usage=usage_payload,
                event_context=event_context,
            )
        done_event = LLMStreamEvent(kind="done")
        await emit_stream_event(done_event)
        yield done_event

__all__ = [
    "ProviderBridgeChatStreamingMixin",
    "ProviderBridgeToolStreamingMixin",
    "ThinkTagScrubber",
]
