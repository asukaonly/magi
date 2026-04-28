"""Streaming helpers for provider bridge responses."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, cast

from .provider_bridge_models import ProviderResponse, ProviderToolCall, ToolStreamResult
from .streaming_events import LLMStreamEvent, emit_stream_event
from ..config.constants import DEFAULT_THINKING_TOKENS
from ..config.models import ThinkingDepth


class ThinkTagScrubber:
    """Strip ``<think>...</think>`` blocks from streaming text content."""

    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self) -> None:
        self._inside = False
        self._pending = ""

    def feed(self, chunk: str) -> tuple[str, str]:
        """Process ``chunk`` and return ``(visible_text, reasoning_text)``."""
        if not chunk:
            return "", ""
        text = self._pending + chunk
        self._pending = ""
        visible: list[str] = []
        reasoning: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            if self._inside:
                close_idx = text.find(self.CLOSE, i)
                if close_idx == -1:
                    tail = len(self.CLOSE) - 1
                    if n - i <= tail:
                        self._pending = text[i:]
                        i = n
                    else:
                        safe_end = n - tail
                        reasoning.append(text[i:safe_end])
                        self._pending = text[safe_end:]
                        i = n
                    break
                if close_idx > i:
                    reasoning.append(text[i:close_idx])
                i = close_idx + len(self.CLOSE)
                self._inside = False
            else:
                open_idx = text.find(self.OPEN, i)
                if open_idx == -1:
                    tail = len(self.OPEN) - 1
                    if n - i <= tail:
                        self._pending = text[i:]
                        i = n
                    else:
                        safe_end = n - tail
                        visible.append(text[i:safe_end])
                        self._pending = text[safe_end:]
                        i = n
                    break
                if open_idx > i:
                    visible.append(text[i:open_idx])
                i = open_idx + len(self.OPEN)
                self._inside = True
        return "".join(visible), "".join(reasoning)

    def flush(self) -> tuple[str, str]:
        """Return any leftover buffered text when the stream ends."""
        if not self._pending:
            return "", ""
        leftover = self._pending
        self._pending = ""
        if self._inside:
            return "", leftover
        return leftover, ""


class _ChatStreamingHostProtocol(Protocol):
    llm: Any

    def is_anthropic(self) -> bool:
        ...

    def _convert_messages_to_anthropic(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ...

    def _convert_messages_to_openai(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ...

    def _apply_provider_options(
        self,
        kwargs: Dict[str, Any],
        thinking_depth: ThinkingDepth,
    ) -> Dict[str, Any]:
        ...

    def _anthropic_usage_to_wire(self, usage_data: Any) -> dict[str, int] | None:
        ...

    def _openai_usage_to_wire(self, usage_data: Any) -> dict[str, int] | None:
        ...


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
        thinking_depth: ThinkingDepth | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Streaming variant of chat_response()."""
        host = cast(_ChatStreamingHostProtocol, self)
        depth = thinking_depth if thinking_depth is not None else ThinkingDepth.MEDIUM
        usage_data: Any = None
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
        done_event = LLMStreamEvent(kind="done")
        await emit_stream_event(done_event)
        yield done_event


class _ToolStreamingHostProtocol(_ChatStreamingHostProtocol, Protocol):
    def _extract_anthropic_stream_usage(self, stream: Any, usage_data: Any) -> Any:
        ...

    def _extract_openai_stream_usage(self, usage_data: Any) -> Any:
        ...


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
    ) -> ToolStreamResult:
        """Stream an LLM call with tools."""
        host = cast(_ToolStreamingHostProtocol, self)
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
        api_messages = host._convert_messages_to_anthropic(messages)
        anthropic_kwargs: Dict[str, Any] = {
            "model": host.llm.model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": api_messages,
            "tools": tools if tools else None,
            "timeout": timeout_seconds,
            "stream": True,
        }
        anthropic_kwargs = host._apply_provider_options(anthropic_kwargs, thinking_depth)
        stream = await host.llm._client.messages.create(**anthropic_kwargs)

        tool_calls: List[ProviderToolCall] = []
        content_parts: List[str] = []
        assistant_blocks: List[Dict[str, Any]] = []
        has_tool_calls = False
        chunks_emitted = 0
        in_thinking = False
        current_tool_id: str | None = None
        current_tool_name: str | None = None
        current_tool_json_parts: List[str] = []
        usage_data: Any = None

        async for event in stream:
            event_type = getattr(event, "type", None)
            if event_type == "content_block_start":
                block = getattr(event, "content_block", None)
                block_type = getattr(block, "type", None) if block is not None else None
                if block is not None and block_type == "tool_use":
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
                message = getattr(event, "message", None)
                if message is not None:
                    usage_data = getattr(message, "usage", usage_data)

        content_text = "".join(content_parts)
        if content_text:
            assistant_blocks.insert(0, {"type": "text", "text": content_text})

        usage = host._extract_anthropic_stream_usage(stream, usage_data)
        usage_payload = host._anthropic_usage_to_wire(usage_data)
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
        host = cast(_ToolStreamingHostProtocol, self)
        full_messages = [{"role": "system", "content": system_prompt}] + host._convert_messages_to_openai(messages)
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

        stream = await host.llm._client.chat.completions.create(**kwargs)

        tool_calls_by_index: Dict[int, Dict[str, Any]] = {}
        content_parts: List[str] = []
        has_tool_calls = False
        chunks_emitted = 0
        usage_data: Any = None
        scrubber = ThinkTagScrubber()

        async for chunk in stream:
            if not chunk.choices:
                if hasattr(chunk, "usage") and chunk.usage is not None:
                    usage_data = chunk.usage
                continue
            delta = chunk.choices[0].delta

            if hasattr(delta, "tool_calls") and delta.tool_calls:
                has_tool_calls = True
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    existing = tool_calls_by_index.get(idx)
                    if existing is None:
                        entry: Dict[str, Any] = {
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
                    if not entry["start_emitted"] and entry["id"] and entry["name"]:
                        entry["start_emitted"] = True
                        await emit_stream_event(LLMStreamEvent(
                            kind="tool_call_start",
                            tool_call_id=entry["id"],
                            tool_name=entry["name"],
                        ))
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

            reasoning_text = (
                getattr(delta, "reasoning_content", None)
                or getattr(delta, "reasoning", None)
            )
            if reasoning_text:
                await emit_stream_event(LLMStreamEvent(
                    kind="reasoning_delta",
                    text=reasoning_text,
                ))

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

        usage = host._extract_openai_stream_usage(usage_data)
        usage_payload = host._openai_usage_to_wire(usage_data)
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
