"""Translate the SDK provider boundary into the existing host LLM adapter."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from magi_plugin_sdk.providers import ModelEvent, ModelRequest, ModelResult
from magi_plugin_sdk.runtime import PluginConnection

from .base import LLMAdapter
from .provider_bridge.models import (
    ProviderResponse,
    ProviderToolCall,
    ProviderUsage,
    ToolStreamResult,
)
from .streaming_events import LLMStreamEvent, emit_stream_event


class PluginModelAdapter(LLMAdapter):
    """A host adapter whose only plugin-facing data is typed SDK JSON."""

    is_plugin_provider = True

    def __init__(
        self,
        provider: Any,
        *,
        connection: PluginConnection,
        model: str,
        valid: Callable[[], bool],
        timeout: float = 60,
    ) -> None:
        self._provider = provider
        self._connection = connection
        self._model = model
        self._valid = valid
        self._timeout = timeout

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return self._connection.plugin_id

    def _request(
        self,
        *,
        messages: list[dict[str, Any]],
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        options: dict[str, Any] | None = None,
        event_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> ModelRequest:
        if not self._valid():
            raise RuntimeError("Model provider connection was revoked")
        from ..plugins.operation_authorization import build_host_invocation

        trace = event_context or {}
        identity = build_host_invocation(
            self._connection,
            trigger="model",
            task_id=trace.get("task_id"),
            session_id=trace.get("session_id"),
        )
        full_messages = (
            [{"role": "system", "content": system_prompt}] if system_prompt else []
        ) + messages
        request = ModelRequest(
            identity=identity,
            model=self._model,
            messages=full_messages,
            tools=tools or [],
            max_tokens=max_tokens,
            temperature=temperature,
            options=options or {},
        )
        json.dumps(request.model_dump(mode="json"), allow_nan=False)
        return request

    @staticmethod
    def to_response(result: ModelResult) -> ProviderResponse:
        calls = [
            ProviderToolCall(call.id, call.name, dict(call.arguments))
            for call in result.tool_calls
        ]
        assistant: dict[str, Any] = {"role": "assistant", "content": result.content}
        if calls:
            assistant["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in calls
            ]
        return ProviderResponse(
            content=result.content,
            tool_calls=calls,
            assistant_message=assistant,
            metadata={"finish_reason": result.finish_reason},
            usage=ProviderUsage(
                prompt_tokens=result.usage.input_tokens,
                completion_tokens=result.usage.output_tokens,
                total_tokens=result.usage.total_tokens,
            ),
        )

    async def invoke_response(self, **kwargs: Any) -> ProviderResponse:
        request = self._request(**kwargs)
        result = await asyncio.wait_for(
            self._provider.invoke(request),
            kwargs.get("timeout_seconds") or self._timeout,
        )
        return self.to_response(ModelResult.model_validate(result))

    async def _events(
        self, request: ModelRequest, timeout: float
    ) -> AsyncIterator[ModelEvent]:
        stream = self._provider.stream(request)
        completed = False
        count = 0
        deadline = asyncio.get_running_loop().time() + timeout
        try:
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    raw = await asyncio.wait_for(stream.__anext__(), remaining)
                except StopAsyncIteration:
                    break
                count += 1
                if count > 100000 or not self._valid():
                    raise RuntimeError("Model provider stream limit or revocation")
                event = ModelEvent.model_validate(raw)
                if completed:
                    raise ValueError("Model provider emitted after completion")
                if event.kind == "completed":
                    if event.result is None:
                        raise ValueError("Model completion requires a result")
                    completed = True
                yield event
            if not completed:
                raise ValueError("Model provider stream ended without a result")
        finally:
            await stream.aclose()

    async def stream_response(self, **kwargs: Any) -> AsyncIterator[LLMStreamEvent]:
        request = self._request(**kwargs)
        async for event in self._events(
            request, kwargs.get("timeout_seconds") or self._timeout
        ):
            if event.kind in {"text", "reasoning"}:
                yield LLMStreamEvent(
                    kind="text_delta" if event.kind == "text" else "reasoning_delta",
                    text=event.delta,
                )
            elif event.kind == "tool_call" and event.tool_call is not None:
                call = event.tool_call
                yield LLMStreamEvent(
                    kind="tool_call_end",
                    tool_call_id=call.id,
                    tool_name=call.name,
                    tool_arguments=dict(call.arguments),
                )
            elif event.kind == "completed":
                result = event.result
                yield LLMStreamEvent(
                    kind="usage",
                    usage={
                        "prompt_tokens": result.usage.input_tokens,
                        "completion_tokens": result.usage.output_tokens,
                        "total_tokens": result.usage.total_tokens,
                    },
                )
                yield LLMStreamEvent(kind="done")

    async def stream_tool_response(self, **kwargs: Any) -> ToolStreamResult:
        request = self._request(**kwargs)
        result = None
        chunks = 0
        async for event in self._events(
            request, kwargs.get("timeout_seconds") or self._timeout
        ):
            if event.kind in {"text", "reasoning"}:
                if event.kind == "text":
                    chunks += 1
                await emit_stream_event(
                    LLMStreamEvent(
                        kind=(
                            "text_delta" if event.kind == "text" else "reasoning_delta"
                        ),
                        text=event.delta,
                    )
                )
            if event.kind == "completed":
                result = event.result
        assert result is not None
        response = self.to_response(result)
        return ToolStreamResult(response, chunks, bool(response.tool_calls))

    async def chat(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        return (
            await self.invoke_response(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
        ).content

    async def generate(
        self,
        prompt: str,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        return await self.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        async for event in self.stream_response(
            messages=messages, max_tokens=max_tokens, temperature=temperature, **kwargs
        ):
            if event.kind == "text_delta":
                yield event.text or ""

    async def generate_stream(
        self,
        prompt: str,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        async for text in self.chat_stream(
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        ):
            yield text
