"""
Provider bridge for provider-specific request/response handling.

This module centralizes API differences between OpenAI-compatible models
(OpenAI/GLM) and Anthropic, so business layers can use one unified interface.
"""
import json
import time
from typing import Any, Dict, List, Optional

from .base import LLMAdapter
from .concurrency_limiter import LLMConcurrencyLimiter, get_llm_concurrency_limiter
from .streaming_events import LLMStreamEvent, emit_stream_event
from .usage_events import LLMUsageEventPublisher, publish_llm_call_event
from .provider_bridge_models import ProviderResponse, ProviderToolCall, ProviderUsage, ToolStreamResult
from .provider_bridge_options import ProviderBridgeOptionsMixin
from .provider_bridge_requests import ProviderBridgeRequestMixin
from .provider_bridge_responses import ProviderBridgeResponseMixin
from .provider_bridge_streaming import (
    ProviderBridgeChatStreamingMixin,
    ThinkTagScrubber as _ThinkTagScrubber,
)
from ..config.constants import DEFAULT_MAX_TOKENS, DEFAULT_THINKING_TOKENS
from ..config.models import ThinkingDepth


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


class LLMProviderBridge(
    ProviderBridgeOptionsMixin,
    ProviderBridgeResponseMixin,
    ProviderBridgeRequestMixin,
    ProviderBridgeChatStreamingMixin,
):
    """Unified entrypoint for provider-specific LLM calls."""

    def __init__(
        self,
        llm_adapter: LLMAdapter,
        usage_event_publisher: LLMUsageEventPublisher | None = None,
        concurrency_limiter: LLMConcurrencyLimiter | None = None,
    ):
        self.llm = llm_adapter
        self._usage_event_publisher = usage_event_publisher or getattr(
            llm_adapter,
            "_llm_usage_event_publisher",
            None,
        )
        self._concurrency_limiter = concurrency_limiter or get_llm_concurrency_limiter()

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
            provider_response = await self._run_with_concurrency_limit(
                request_family="chat",
                limit=self._resolve_chat_concurrency_limit(),
                operation=lambda: self._chat_response_impl(
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
            self._attach_trace_metrics(
                provider_response=provider_response,
                usage=provider_response.usage,
                latency_ms=latency_ms,
                thinking_depth=depth,
            )
            await self._emit_usage_event(
                success=True,
                latency_ms=latency_ms,
                usage=provider_response.usage,
                event_context=event_context,
            )
            return provider_response
        except Exception as exc:
            await self._emit_usage_event(
                success=False,
                latency_ms=int((time.time() - started_at) * 1000),
                usage=None,
                event_context=event_context,
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
            if getattr(self.llm, "_client", None) is None and not self.is_anthropic():
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

            provider_response = await self._run_with_concurrency_limit(
                request_family="chat",
                limit=self._resolve_chat_concurrency_limit(),
                operation=lambda: self._chat_with_tools_impl(
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
            self._attach_trace_metrics(
                provider_response=provider_response,
                usage=provider_response.usage,
                latency_ms=latency_ms,
                thinking_depth=depth,
            )
            await self._emit_usage_event(
                success=True,
                latency_ms=latency_ms,
                usage=provider_response.usage,
                event_context=event_context,
            )
            return provider_response
        except Exception as exc:
            await self._emit_usage_event(
                success=False,
                latency_ms=int((time.time() - started_at) * 1000),
                usage=None,
                event_context=event_context,
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
            result = await self._run_with_concurrency_limit(
                request_family="chat",
                limit=self._resolve_chat_concurrency_limit(),
                operation=lambda: self._chat_with_tools_stream_impl(
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
            self._attach_trace_metrics(
                provider_response=result.provider_response,
                usage=result.provider_response.usage,
                latency_ms=latency_ms,
                thinking_depth=depth,
            )
            await self._emit_usage_event(
                success=True,
                latency_ms=latency_ms,
                usage=result.provider_response.usage,
                event_context=event_context,
            )
            return result
        except Exception as exc:
            await self._emit_usage_event(
                success=False,
                latency_ms=int((time.time() - started_at) * 1000),
                usage=None,
                event_context=event_context,
                error=str(exc),
            )
            raise

    async def _chat_with_tools_stream_impl(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        thinking_depth: ThinkingDepth,
        timeout_seconds: Optional[float],
    ) -> ToolStreamResult:
        """Stream an LLM call with tools.

        All events (text, reasoning, tool-call lifecycle) are forwarded
        to the contextual stream sink via
        :func:`magi.llm.streaming_events.emit_stream_event`. The full
        assembled ``ProviderResponse`` (including any tool_calls) is
        returned inside ``ToolStreamResult``.
        """
        if self.is_anthropic():
            return await self._stream_anthropic_with_tools(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                thinking_depth=thinking_depth,
                timeout_seconds=timeout_seconds,
            )
        return await self._stream_openai_with_tools(
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            thinking_depth=thinking_depth,
            timeout_seconds=timeout_seconds,
        )

    async def _stream_anthropic_with_tools(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        thinking_depth: ThinkingDepth,
        timeout_seconds: Optional[float],
    ) -> ToolStreamResult:
        api_messages = self._convert_messages_to_anthropic(messages)
        anthropic_kwargs: Dict[str, Any] = {
            "model": self.llm.model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": api_messages,
            "tools": tools if tools else None,
            "timeout": timeout_seconds,
            "stream": True,
        }
        anthropic_kwargs = self._apply_provider_options(anthropic_kwargs, thinking_depth)
        stream = await self.llm._client.messages.create(**anthropic_kwargs)

        tool_calls: List[ProviderToolCall] = []
        content_parts: List[str] = []
        assistant_blocks: List[Dict[str, Any]] = []
        has_tool_calls = False
        chunks_emitted = 0
        in_thinking = False
        # Track current tool_use block being streamed
        current_tool_id: str | None = None
        current_tool_name: str | None = None
        current_tool_json_parts: List[str] = []
        usage_data: Any = None

        async for event in stream:
            event_type = getattr(event, "type", None)
            if event_type == "content_block_start":
                block = getattr(event, "content_block", None)
                block_type = getattr(block, "type", None) if block is not None else None
                if block_type == "tool_use":
                    has_tool_calls = True
                    current_tool_id = block.id
                    current_tool_name = block.name
                    current_tool_json_parts = []
                    await emit_stream_event(LLMStreamEvent(
                        kind="tool_call_start",
                        tool_call_id=block.id,
                        tool_name=block.name,
                    ))
                elif block_type == "thinking":
                    in_thinking = True
            elif event_type == "content_block_delta":
                delta = event.delta
                delta_type = getattr(delta, "type", None)
                if delta_type == "thinking_delta":
                    text = getattr(delta, "thinking", None) or getattr(delta, "text", None)
                    if text:
                        await emit_stream_event(LLMStreamEvent(kind="reasoning_delta", text=text))
                elif in_thinking and getattr(delta, "text", None):
                    await emit_stream_event(LLMStreamEvent(kind="reasoning_delta", text=delta.text))
                elif hasattr(delta, "text") and not has_tool_calls:
                    text = delta.text
                    if text:
                        content_parts.append(text)
                        await emit_stream_event(LLMStreamEvent(kind="text_delta", text=text))
                        chunks_emitted += 1
                elif hasattr(delta, "text") and has_tool_calls:
                    # Text arriving after tool_use detected — collect but don't emit
                    if delta.text:
                        content_parts.append(delta.text)
                elif delta_type == "input_json_delta":
                    partial = getattr(delta, "partial_json", "")
                    if partial:
                        current_tool_json_parts.append(partial)
                        await emit_stream_event(LLMStreamEvent(
                            kind="tool_call_args",
                            tool_call_id=current_tool_id,
                            tool_name=current_tool_name,
                            tool_args_delta=partial,
                        ))
            elif event_type == "content_block_stop":
                if current_tool_id is not None:
                    raw_json = "".join(current_tool_json_parts)
                    try:
                        arguments = json.loads(raw_json) if raw_json else {}
                    except json.JSONDecodeError:
                        arguments = {"raw": raw_json}
                    tool_calls.append(ProviderToolCall(
                        id=current_tool_id,
                        name=current_tool_name or "",
                        arguments=arguments,
                    ))
                    assistant_blocks.append({
                        "type": "tool_use",
                        "id": current_tool_id,
                        "name": current_tool_name,
                        "input": arguments,
                    })
                    await emit_stream_event(LLMStreamEvent(
                        kind="tool_call_end",
                        tool_call_id=current_tool_id,
                        tool_name=current_tool_name,
                        tool_arguments=arguments,
                    ))
                    current_tool_id = None
                    current_tool_name = None
                    current_tool_json_parts = []
                in_thinking = False
            elif event_type == "message_delta":
                usage_data = getattr(event, "usage", usage_data)
            elif event_type == "message_start":
                msg = getattr(event, "message", None)
                if msg is not None:
                    usage_data = getattr(msg, "usage", usage_data)

        content_text = "".join(content_parts)
        if content_text:
            assistant_blocks.insert(0, {"type": "text", "text": content_text})

        usage = self._extract_anthropic_stream_usage(stream, usage_data)
        usage_payload = self._anthropic_usage_to_wire(usage_data)
        if usage_payload is not None:
            await emit_stream_event(LLMStreamEvent(kind="usage", usage=usage_payload))

        if tool_calls:
            provider_response = ProviderResponse(
                content=content_text,
                tool_calls=tool_calls,
                assistant_message={"role": "assistant", "content": assistant_blocks},
                usage=usage,
            )
        else:
            provider_response = ProviderResponse(content=content_text, usage=usage)

        return ToolStreamResult(
            provider_response=provider_response,
            text_chunks_emitted=chunks_emitted,
            has_tool_calls=has_tool_calls,
        )
    async def _stream_openai_with_tools(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        thinking_depth: ThinkingDepth,
        timeout_seconds: Optional[float],
    ) -> ToolStreamResult:
        full_messages = [{"role": "system", "content": system_prompt}] + self._convert_messages_to_openai(messages)
        kwargs: Dict[str, Any] = {
            "model": self.llm.model_name,
            "messages": full_messages,
            "tools": tools if tools else None,
            "tool_choice": "auto" if tools else None,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if timeout_seconds is not None:
            kwargs["timeout"] = timeout_seconds
        kwargs = self._apply_provider_options(kwargs, thinking_depth)

        stream = await self.llm._client.chat.completions.create(**kwargs)

        tool_calls_by_index: Dict[int, Dict[str, Any]] = {}
        content_parts: List[str] = []
        has_tool_calls = False
        chunks_emitted = 0
        usage_data: Any = None
        scrubber = _ThinkTagScrubber()

        async for chunk in stream:
            if not chunk.choices:
                # usage-only final chunk
                if hasattr(chunk, "usage") and chunk.usage is not None:
                    usage_data = chunk.usage
                continue
            delta = chunk.choices[0].delta

            # Detect tool_calls
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                has_tool_calls = True
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    existing = tool_calls_by_index.get(idx)
                    if existing is None:
                        entry = {
                            "id": getattr(tc_delta, "id", None) or "",
                            "name": "",
                            "arguments_parts": [],
                            "start_emitted": False,
                        }
                        tool_calls_by_index[idx] = entry
                    else:
                        entry = existing
                    if tc_delta.id:
                        entry["id"] = tc_delta.id
                    if hasattr(tc_delta, "function") and tc_delta.function:
                        if tc_delta.function.name:
                            entry["name"] = tc_delta.function.name
                        args_fragment = tc_delta.function.arguments
                        if args_fragment:
                            entry["arguments_parts"].append(args_fragment)
                    # Emit tool_call_start once we have both id and name
                    if not entry["start_emitted"] and entry["id"] and entry["name"]:
                        entry["start_emitted"] = True
                        await emit_stream_event(LLMStreamEvent(
                            kind="tool_call_start",
                            tool_call_id=entry["id"],
                            tool_name=entry["name"],
                        ))
                    # Emit tool_call_args for any fragment seen this chunk
                    if (
                        entry["start_emitted"]
                        and hasattr(tc_delta, "function")
                        and tc_delta.function
                        and tc_delta.function.arguments
                    ):
                        await emit_stream_event(LLMStreamEvent(
                            kind="tool_call_args",
                            tool_call_id=entry["id"],
                            tool_name=entry["name"],
                            tool_args_delta=tc_delta.function.arguments,
                        ))

            # Reasoning (GLM / compatible providers)
            reasoning_text = (
                getattr(delta, "reasoning_content", None)
                or getattr(delta, "reasoning", None)
            )
            if reasoning_text:
                await emit_stream_event(LLMStreamEvent(
                    kind="reasoning_delta",
                    text=reasoning_text,
                ))

            # Visible text
            if hasattr(delta, "content") and delta.content:
                if not has_tool_calls:
                    visible, reasoning_leak = scrubber.feed(delta.content)
                    if reasoning_leak:
                        await emit_stream_event(LLMStreamEvent(
                            kind="reasoning_delta",
                            text=reasoning_leak,
                        ))
                    if visible:
                        content_parts.append(visible)
                        await emit_stream_event(LLMStreamEvent(
                            kind="text_delta",
                            text=visible,
                        ))
                        chunks_emitted += 1
                else:
                    # Tool-call branch already collects post-tool text raw.
                    content_parts.append(delta.content)

            if hasattr(chunk, "usage") and chunk.usage is not None:
                usage_data = chunk.usage

        tail_visible, tail_reasoning = scrubber.flush()
        if tail_reasoning:
            await emit_stream_event(LLMStreamEvent(
                kind="reasoning_delta",
                text=tail_reasoning,
            ))
        if tail_visible and not has_tool_calls:
            content_parts.append(tail_visible)
            await emit_stream_event(LLMStreamEvent(
                kind="text_delta",
                text=tail_visible,
            ))
            chunks_emitted += 1

        content_text = "".join(content_parts)

        # Build tool_calls
        tool_calls: List[ProviderToolCall] = []
        raw_tool_calls: List[Dict[str, Any]] = []
        for idx in sorted(tool_calls_by_index.keys()):
            entry = tool_calls_by_index[idx]
            raw_args = "".join(entry["arguments_parts"])
            try:
                arguments = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                arguments = {"raw": raw_args}
            tool_calls.append(ProviderToolCall(
                id=entry["id"],
                name=entry["name"],
                arguments=arguments,
            ))
            raw_tool_calls.append({
                "id": entry["id"],
                "type": "function",
                "function": {
                    "name": entry["name"],
                    "arguments": raw_args or "{}",
                },
            })
            await emit_stream_event(LLMStreamEvent(
                kind="tool_call_end",
                tool_call_id=entry["id"],
                tool_name=entry["name"],
                tool_arguments=arguments,
            ))

        usage = self._extract_openai_stream_usage(usage_data)
        usage_payload = self._openai_usage_to_wire(usage_data)
        if usage_payload is not None:
            await emit_stream_event(LLMStreamEvent(kind="usage", usage=usage_payload))

        if tool_calls:
            provider_response = ProviderResponse(
                content=content_text,
                tool_calls=tool_calls,
                assistant_message={
                    "role": "assistant",
                    "content": content_text or "",
                    "tool_calls": raw_tool_calls,
                },
                usage=usage,
            )
        else:
            provider_response = ProviderResponse(content=content_text, usage=usage)

        return ToolStreamResult(
            provider_response=provider_response,
            text_chunks_emitted=chunks_emitted,
            has_tool_calls=has_tool_calls,
        )
