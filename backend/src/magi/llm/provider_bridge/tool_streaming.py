"""Tool-call streaming implementation for provider bridge responses."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, cast

from ..streaming_events import LLMStreamEvent, emit_stream_event
from .models import ProviderResponse, ProviderToolCall, ToolStreamResult
from .streaming_core import ProviderBridgeStreamingHostProtocol, ThinkTagScrubber
from ...config.models import ThinkingDepth


class _ToolStreamingHostProtocol(ProviderBridgeStreamingHostProtocol, Protocol):
    def _extract_anthropic_stream_usage(self, stream: Any, usage_data: Any) -> Any: ...

    def _extract_openai_stream_usage(self, usage_data: Any) -> Any: ...


@dataclass
class _AnthropicToolStreamState:
    tool_calls: List[ProviderToolCall] = field(default_factory=list)
    content_parts: List[str] = field(default_factory=list)
    assistant_blocks: List[Dict[str, Any]] = field(default_factory=list)
    thinking_blocks: List[Dict[str, Any]] = field(default_factory=list)
    thinking_text_parts: List[str] = field(default_factory=list)
    thinking_signature: str | None = None
    redacted_data: str | None = None
    has_tool_calls: bool = False
    chunks_emitted: int = 0
    in_thinking: bool = False
    current_tool_id: str | None = None
    current_tool_name: str | None = None
    current_tool_json_parts: List[str] = field(default_factory=list)
    usage_data: Any = None


@dataclass
class _OpenAIToolStreamState:
    tool_calls_by_index: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    content_parts: List[str] = field(default_factory=list)
    has_tool_calls: bool = False
    chunks_emitted: int = 0
    usage_data: Any = None
    scrubber: ThinkTagScrubber = field(default_factory=ThinkTagScrubber)


class ProviderBridgeToolStreamingMixin:
    """Stream tool-calling requests and assemble normalized provider responses."""

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
        event_context: Optional[Dict[str, Any]] = None,
    ) -> ToolStreamResult:
        """Stream an LLM call with tools."""
        host = cast(_ToolStreamingHostProtocol, self)
        if getattr(host.llm, "is_plugin_provider", False) is True:
            return await host.llm.stream_tool_response(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
                event_context=event_context,
                options={"thinking_depth": thinking_depth.value},
            )
        if host.is_anthropic():
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
            event_context=event_context,
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
        host = cast(_ToolStreamingHostProtocol, self)
        anthropic_kwargs = self._build_anthropic_tool_stream_kwargs(
            host,
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            thinking_depth=thinking_depth,
            timeout_seconds=timeout_seconds,
        )
        stream = await host.llm._client.messages.create(**anthropic_kwargs)
        state = _AnthropicToolStreamState()

        async for event in stream:
            await self._handle_anthropic_tool_stream_event(event, state)

        return await self._build_anthropic_tool_stream_result(host, stream, state)

    @staticmethod
    def _build_anthropic_tool_stream_kwargs(
        host: _ToolStreamingHostProtocol,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        thinking_depth: ThinkingDepth,
        timeout_seconds: Optional[float],
    ) -> Dict[str, Any]:
        api_messages = host._convert_messages_to_anthropic(messages)
        api_messages = host._mark_message_cache_breakpoints(messages, api_messages)
        anthropic_kwargs: Dict[str, Any] = {
            "model": host.llm.model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": host._cache_marked_system(system_prompt),
            "messages": api_messages,
            "tools": tools if tools else None,
            "timeout": timeout_seconds,
            "stream": True,
        }
        return host._apply_provider_options(anthropic_kwargs, thinking_depth)

    async def _handle_anthropic_tool_stream_event(
        self,
        event: Any,
        state: _AnthropicToolStreamState,
    ) -> None:
        event_type = getattr(event, "type", None)
        if event_type == "content_block_start":
            await self._handle_anthropic_tool_block_start(event, state)
        elif event_type == "content_block_delta":
            await self._handle_anthropic_tool_block_delta(event.delta, state)
        elif event_type == "content_block_stop":
            await self._handle_anthropic_tool_block_stop(state)
        elif event_type == "message_delta":
            state.usage_data = getattr(event, "usage", state.usage_data)
        elif event_type == "message_start":
            message = getattr(event, "message", None)
            if message is not None:
                state.usage_data = getattr(message, "usage", state.usage_data)

    async def _handle_anthropic_tool_block_start(
        self,
        event: Any,
        state: _AnthropicToolStreamState,
    ) -> None:
        block = getattr(event, "content_block", None)
        block_type = getattr(block, "type", None) if block is not None else None
        if block is not None and block_type == "tool_use":
            state.has_tool_calls = True
            state.current_tool_id = block.id
            state.current_tool_name = block.name
            state.current_tool_json_parts = []
            await emit_stream_event(
                LLMStreamEvent(
                    kind="tool_call_start",
                    tool_call_id=block.id,
                    tool_name=block.name,
                )
            )
        elif block_type == "thinking":
            self._start_anthropic_thinking_block(state)
        elif block_type == "redacted_thinking":
            self._start_anthropic_thinking_block(
                state, redacted_data=getattr(block, "data", None)
            )

    @staticmethod
    def _start_anthropic_thinking_block(
        state: _AnthropicToolStreamState,
        *,
        redacted_data: str | None = None,
    ) -> None:
        state.in_thinking = True
        state.thinking_text_parts = []
        state.thinking_signature = None
        state.redacted_data = redacted_data

    async def _handle_anthropic_tool_block_delta(
        self,
        delta: Any,
        state: _AnthropicToolStreamState,
    ) -> None:
        delta_type = getattr(delta, "type", None)
        if delta_type == "thinking_delta":
            await self._record_anthropic_thinking_delta(delta, state)
        elif delta_type == "signature_delta":
            state.thinking_signature = (
                getattr(delta, "signature", None) or state.thinking_signature
            )
        elif state.in_thinking and getattr(delta, "text", None):
            await emit_stream_event(
                LLMStreamEvent(kind="reasoning_delta", text=delta.text)
            )
        elif hasattr(delta, "text"):
            await self._record_anthropic_text_delta(delta.text, state)
        elif delta_type == "input_json_delta":
            await self._record_anthropic_tool_args_delta(delta, state)

    @staticmethod
    async def _record_anthropic_thinking_delta(
        delta: Any,
        state: _AnthropicToolStreamState,
    ) -> None:
        text = getattr(delta, "thinking", None) or getattr(delta, "text", None)
        if not text:
            return
        state.thinking_text_parts.append(text)
        await emit_stream_event(LLMStreamEvent(kind="reasoning_delta", text=text))

    @staticmethod
    async def _record_anthropic_text_delta(
        text: str,
        state: _AnthropicToolStreamState,
    ) -> None:
        if not text:
            return
        state.content_parts.append(text)
        if state.has_tool_calls:
            return
        await emit_stream_event(LLMStreamEvent(kind="text_delta", text=text))
        state.chunks_emitted += 1

    @staticmethod
    async def _record_anthropic_tool_args_delta(
        delta: Any,
        state: _AnthropicToolStreamState,
    ) -> None:
        partial = getattr(delta, "partial_json", "")
        if not partial:
            return
        state.current_tool_json_parts.append(partial)
        await emit_stream_event(
            LLMStreamEvent(
                kind="tool_call_args",
                tool_call_id=state.current_tool_id,
                tool_name=state.current_tool_name,
                tool_args_delta=partial,
            )
        )

    async def _handle_anthropic_tool_block_stop(
        self,
        state: _AnthropicToolStreamState,
    ) -> None:
        if state.current_tool_id is not None:
            await self._finish_anthropic_tool_call(state)
        elif state.in_thinking:
            self._finish_anthropic_thinking_block(state)
        state.in_thinking = False

    @staticmethod
    async def _finish_anthropic_tool_call(
        state: _AnthropicToolStreamState,
    ) -> None:
        tool_id = state.current_tool_id
        if tool_id is None:
            return
        raw_json = "".join(state.current_tool_json_parts)
        arguments = _parse_tool_arguments(raw_json)
        state.tool_calls.append(
            ProviderToolCall(
                id=tool_id,
                name=state.current_tool_name or "",
                arguments=arguments,
            )
        )
        state.assistant_blocks.append(
            {
                "type": "tool_use",
                "id": tool_id,
                "name": state.current_tool_name,
                "input": arguments,
            }
        )
        await emit_stream_event(
            LLMStreamEvent(
                kind="tool_call_end",
                tool_call_id=state.current_tool_id,
                tool_name=state.current_tool_name,
                tool_arguments=arguments,
            )
        )
        state.current_tool_id = None
        state.current_tool_name = None
        state.current_tool_json_parts = []

    @staticmethod
    def _finish_anthropic_thinking_block(
        state: _AnthropicToolStreamState,
    ) -> None:
        if state.redacted_data is not None:
            state.thinking_blocks.append(
                {"type": "redacted_thinking", "data": state.redacted_data}
            )
        elif state.thinking_text_parts or state.thinking_signature is not None:
            state.thinking_blocks.append(
                {
                    "type": "thinking",
                    "thinking": "".join(state.thinking_text_parts),
                    "signature": state.thinking_signature,
                }
            )
        state.thinking_text_parts = []
        state.thinking_signature = None
        state.redacted_data = None

    async def _build_anthropic_tool_stream_result(
        self,
        host: _ToolStreamingHostProtocol,
        stream: Any,
        state: _AnthropicToolStreamState,
    ) -> ToolStreamResult:
        content_text = "".join(state.content_parts)
        if content_text:
            state.assistant_blocks.insert(0, {"type": "text", "text": content_text})
        for thinking_block in reversed(state.thinking_blocks):
            state.assistant_blocks.insert(0, thinking_block)

        usage = host._extract_anthropic_stream_usage(stream, state.usage_data)
        usage_payload = host._anthropic_usage_to_wire(state.usage_data)
        if usage_payload is not None:
            await emit_stream_event(LLMStreamEvent(kind="usage", usage=usage_payload))

        if state.tool_calls:
            provider_response = ProviderResponse(
                content=content_text,
                tool_calls=state.tool_calls,
                assistant_message={
                    "role": "assistant",
                    "content": state.assistant_blocks,
                },
                usage=usage,
            )
        else:
            provider_response = ProviderResponse(content=content_text, usage=usage)

        return ToolStreamResult(
            provider_response=provider_response,
            text_chunks_emitted=state.chunks_emitted,
            has_tool_calls=state.has_tool_calls,
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
        event_context: Optional[Dict[str, Any]] = None,
    ) -> ToolStreamResult:
        host = cast(_ToolStreamingHostProtocol, self)
        kwargs = self._build_openai_tool_stream_kwargs(
            host,
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            thinking_depth=thinking_depth,
            timeout_seconds=timeout_seconds,
            event_context=event_context,
        )
        stream = await host.llm._client.chat.completions.create(**kwargs)
        state = _OpenAIToolStreamState()

        async for chunk in stream:
            await self._handle_openai_tool_stream_chunk(chunk, state)

        await self._flush_openai_tool_scrubber(state)
        return await self._build_openai_tool_stream_result(host, state)

    @staticmethod
    def _build_openai_tool_stream_kwargs(
        host: _ToolStreamingHostProtocol,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        thinking_depth: ThinkingDepth,
        timeout_seconds: Optional[float],
        event_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        openai_messages = host._mark_message_cache_breakpoints(
            messages, host._convert_messages_to_openai(messages)
        )
        full_messages = [
            {"role": "system", "content": host._cache_marked_system(system_prompt)}
        ] + openai_messages
        kwargs: Dict[str, Any] = {
            "model": host.llm.model_name,
            "messages": full_messages,
            "tools": tools if tools else None,
            "tool_choice": "auto" if tools else None,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if timeout_seconds is not None:
            kwargs["timeout"] = timeout_seconds
        kwargs = host._apply_provider_options(kwargs, thinking_depth)
        return host._apply_cache_routing(kwargs, event_context)

    async def _handle_openai_tool_stream_chunk(
        self,
        chunk: Any,
        state: _OpenAIToolStreamState,
    ) -> None:
        if not chunk.choices:
            if hasattr(chunk, "usage") and chunk.usage is not None:
                state.usage_data = chunk.usage
            return
        delta = chunk.choices[0].delta

        if hasattr(delta, "tool_calls") and delta.tool_calls:
            await self._handle_openai_tool_call_deltas(delta.tool_calls, state)
        await self._emit_openai_reasoning_delta(delta)
        await self._handle_openai_content_delta(delta, state)
        if hasattr(chunk, "usage") and chunk.usage is not None:
            state.usage_data = chunk.usage

    async def _handle_openai_tool_call_deltas(
        self,
        tool_call_deltas: List[Any],
        state: _OpenAIToolStreamState,
    ) -> None:
        state.has_tool_calls = True
        for tc_delta in tool_call_deltas:
            entry = self._openai_tool_call_entry(tc_delta, state)
            if tc_delta.id:
                entry["id"] = tc_delta.id
            if hasattr(tc_delta, "function") and tc_delta.function:
                self._record_openai_tool_function_delta(tc_delta.function, entry)
            await self._maybe_emit_openai_tool_start(entry)
            await self._maybe_emit_openai_tool_args_delta(tc_delta, entry)

    @staticmethod
    def _openai_tool_call_entry(
        tc_delta: Any,
        state: _OpenAIToolStreamState,
    ) -> Dict[str, Any]:
        existing = state.tool_calls_by_index.get(tc_delta.index)
        if existing is not None:
            return existing
        entry: Dict[str, Any] = {
            "id": getattr(tc_delta, "id", None) or "",
            "name": "",
            "arguments_parts": [],
            "start_emitted": False,
        }
        state.tool_calls_by_index[tc_delta.index] = entry
        return entry

    @staticmethod
    def _record_openai_tool_function_delta(
        function_delta: Any,
        entry: Dict[str, Any],
    ) -> None:
        if function_delta.name:
            entry["name"] = function_delta.name
        args_fragment = function_delta.arguments
        if args_fragment:
            entry["arguments_parts"].append(args_fragment)

    @staticmethod
    async def _maybe_emit_openai_tool_start(entry: Dict[str, Any]) -> None:
        if entry["start_emitted"] or not entry["id"] or not entry["name"]:
            return
        entry["start_emitted"] = True
        await emit_stream_event(
            LLMStreamEvent(
                kind="tool_call_start",
                tool_call_id=entry["id"],
                tool_name=entry["name"],
            )
        )

    @staticmethod
    async def _maybe_emit_openai_tool_args_delta(
        tc_delta: Any,
        entry: Dict[str, Any],
    ) -> None:
        if not (
            entry["start_emitted"]
            and hasattr(tc_delta, "function")
            and tc_delta.function
            and tc_delta.function.arguments
        ):
            return
        await emit_stream_event(
            LLMStreamEvent(
                kind="tool_call_args",
                tool_call_id=entry["id"],
                tool_name=entry["name"],
                tool_args_delta=tc_delta.function.arguments,
            )
        )

    @staticmethod
    async def _emit_openai_reasoning_delta(delta: Any) -> None:
        reasoning_text = getattr(delta, "reasoning_content", None) or getattr(
            delta, "reasoning", None
        )
        if reasoning_text:
            await emit_stream_event(
                LLMStreamEvent(kind="reasoning_delta", text=reasoning_text)
            )

    @staticmethod
    async def _handle_openai_content_delta(
        delta: Any,
        state: _OpenAIToolStreamState,
    ) -> None:
        if not (hasattr(delta, "content") and delta.content):
            return
        if state.has_tool_calls:
            state.content_parts.append(delta.content)
            return
        visible, reasoning_leak = state.scrubber.feed(delta.content)
        if reasoning_leak:
            await emit_stream_event(
                LLMStreamEvent(kind="reasoning_delta", text=reasoning_leak)
            )
        if visible:
            state.content_parts.append(visible)
            await emit_stream_event(LLMStreamEvent(kind="text_delta", text=visible))
            state.chunks_emitted += 1

    @staticmethod
    async def _flush_openai_tool_scrubber(state: _OpenAIToolStreamState) -> None:
        tail_visible, tail_reasoning = state.scrubber.flush()
        if tail_reasoning:
            await emit_stream_event(
                LLMStreamEvent(kind="reasoning_delta", text=tail_reasoning)
            )
        if tail_visible and not state.has_tool_calls:
            state.content_parts.append(tail_visible)
            await emit_stream_event(
                LLMStreamEvent(kind="text_delta", text=tail_visible)
            )
            state.chunks_emitted += 1

    async def _build_openai_tool_stream_result(
        self,
        host: _ToolStreamingHostProtocol,
        state: _OpenAIToolStreamState,
    ) -> ToolStreamResult:
        content_text = "".join(state.content_parts)

        tool_calls: List[ProviderToolCall] = []
        raw_tool_calls: List[Dict[str, Any]] = []
        for idx in sorted(state.tool_calls_by_index.keys()):
            entry = state.tool_calls_by_index[idx]
            raw_args = "".join(entry["arguments_parts"])
            arguments = _parse_tool_arguments(raw_args)
            tool_calls.append(
                ProviderToolCall(
                    id=entry["id"],
                    name=entry["name"],
                    arguments=arguments,
                )
            )
            raw_tool_calls.append(
                {
                    "id": entry["id"],
                    "type": "function",
                    "function": {
                        "name": entry["name"],
                        "arguments": raw_args or "{}",
                    },
                }
            )
            await emit_stream_event(
                LLMStreamEvent(
                    kind="tool_call_end",
                    tool_call_id=entry["id"],
                    tool_name=entry["name"],
                    tool_arguments=arguments,
                )
            )

        usage = host._extract_openai_stream_usage(state.usage_data)
        usage_payload = host._openai_usage_to_wire(state.usage_data)
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
            text_chunks_emitted=state.chunks_emitted,
            has_tool_calls=state.has_tool_calls,
        )


def _parse_tool_arguments(raw_json: str) -> Dict[str, Any]:
    try:
        return json.loads(raw_json) if raw_json else {}
    except json.JSONDecodeError:
        return {"raw": raw_json}


__all__ = ["ProviderBridgeToolStreamingMixin"]
