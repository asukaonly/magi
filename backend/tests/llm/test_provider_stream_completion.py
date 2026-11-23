"""SDK-backed stream completion and refusal boundaries without network calls."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from magi.config.models import ThinkingDepth
from magi.llm.anthropic import AnthropicAdapter
from magi.llm.error_classifier import classify_exception
from magi.llm.openai import OpenAIAdapter
from magi.llm.provider_bridge import LLMProviderBridge
from magi.llm.stream_errors import IncompleteStreamError
from magi.llm.streaming_events import stream_scope


def _bridge(client, provider):
    adapter_type = AnthropicAdapter if provider == "anthropic" else OpenAIAdapter
    adapter = adapter_type.__new__(adapter_type)
    adapter._model = "claude-sonnet-4-6" if provider == "anthropic" else "gpt-4.1"
    adapter._provider = provider
    adapter._provider_plan = adapter._provider_instance_id = adapter._base_url = None
    adapter._client = client
    bridge = LLMProviderBridge(adapter)
    bridge._operations._emit_usage_event = AsyncMock()
    return bridge


def _client(provider, payload):
    def handler(request):
        if isinstance(payload, list):
            body = "".join(
                (f"event: {item['type']}\n" if provider == "anthropic" else "")
                + f"data: {json.dumps(item)}\n\n"
                for item in payload
            )
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=payload)

    client_type = AsyncAnthropic if provider == "anthropic" else AsyncOpenAI
    return client_type(
        api_key="test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def _openai_chunk(delta, finish_reason=None):
    return {
        "id": "cmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4.1",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


async def _invoke(bridge, *, streaming=True, tools=False):
    params = dict(
        system_prompt="system", messages=[{"role": "user", "content": "hello"}],
        thinking_depth=ThinkingDepth.NONE,
    )
    if tools:
        params["tools"] = []
        if streaming:
            return (await bridge.chat_with_tools_stream(**params)).provider_response
        return await bridge.chat_with_tools(**params)
    if streaming:
        return [event async for event in bridge.chat_response_stream(**params)]
    return await bridge.chat_response(**params)


@pytest.mark.asyncio
@pytest.mark.parametrize("tools", [False, True])
@pytest.mark.parametrize("completed", [False, True])
async def test_openai_requires_finish_reason_before_accepting_stream(tools, completed):
    delta = ({"tool_calls": [{"index": 0, "id": "call-1", "type": "function",
                             "function": {"name": "write", "arguments": '{"path":"file"}'}}]}
             if tools else {"content": "partial answer"})
    payload = [_openai_chunk(delta)]
    if completed:
        payload.append(_openai_chunk({}, "tool_calls" if tools else "stop"))
    emitted = []

    async def record(event):
        emitted.append(event)

    async with _client("openai", payload) as client, stream_scope(record):
        bridge = _bridge(client, "openai")
        if completed:
            result = await _invoke(bridge, tools=tools)
            if tools:
                assert result.tool_calls[0].arguments == {"path": "file"}
            else:
                assert "".join(event.text or "" for event in result) == "partial answer"
        else:
            with pytest.raises(IncompleteStreamError) as caught:
                await _invoke(bridge, tools=tools)
            assert classify_exception(caught.value).retryable
            assert not any(event.kind in {"tool_call_end", "done"} for event in emitted)


@pytest.mark.asyncio
@pytest.mark.parametrize("tools", [False, True])
@pytest.mark.parametrize("missing", [None, "message_stop", "stop_reason"])
async def test_anthropic_requires_terminal_message_before_accepting_stream(tools, missing):
    block = ({"type": "tool_use", "id": "toolu-1", "name": "write", "input": {}}
             if tools else {"type": "text", "text": ""})
    delta = ({"type": "input_json_delta", "partial_json": '{"path":"file"}'}
             if tools else {"type": "text_delta", "text": "partial answer"})
    payload = [
        {"type": "content_block_start", "index": 0, "content_block": block},
        {"type": "content_block_delta", "index": 0, "delta": delta},
        {"type": "content_block_stop", "index": 0},
    ]
    if missing != "stop_reason":
        payload.append({"type": "message_delta", "delta": {
            "stop_reason": "tool_use" if tools else "end_turn", "stop_sequence": None,
        }, "usage": {"output_tokens": 5}})
    if missing != "message_stop":
        payload.append({"type": "message_stop"})
    emitted = []

    async def record(event):
        emitted.append(event)

    async with _client("anthropic", payload) as client, stream_scope(record):
        bridge = _bridge(client, "anthropic")
        if missing is None:
            result = await _invoke(bridge, tools=tools)
            if tools:
                assert result.tool_calls[0].arguments == {"path": "file"}
            else:
                assert "".join(event.text or "" for event in result) == "partial answer"
        else:
            with pytest.raises(IncompleteStreamError):
                await _invoke(bridge, tools=tools)
            assert not any(event.kind in {"tool_call_end", "done"} for event in emitted)


@pytest.mark.asyncio
@pytest.mark.parametrize("tools", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
async def test_openai_preserves_refusal_as_response_text(tools, streaming):
    refusal = "I cannot assist with that request."
    payload = ([_openai_chunk({"refusal": refusal}), _openai_chunk({}, "stop")]
               if streaming else {
                   "id": "cmpl-1", "object": "chat.completion", "created": 1, "model": "gpt-4.1",
                   "choices": [{"index": 0, "finish_reason": "stop", "message": {
                       "role": "assistant", "content": None, "refusal": refusal,
                   }}],
               })
    async with _client("openai", payload) as client:
        result = await _invoke(_bridge(client, "openai"), tools=tools, streaming=streaming)
    if streaming and not tools:
        assert "".join(event.text or "" for event in result) == refusal
    else:
        assert result.content == refusal
        assert not result.tool_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("tools", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
async def test_anthropic_refusal_terminates_without_executing_partial_tools(tools, streaming):
    block = {"type": "tool_use", "id": "partial", "name": "lookup", "input": {}}
    payload = ([
        {"type": "content_block_start", "index": 0, "content_block": block},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "refusal"}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ] if streaming else {
        "id": "msg", "model": "claude-fable-5-2", "role": "assistant", "type": "message",
        "content": [block], "stop_reason": "refusal", "usage": {"input_tokens": 1, "output_tokens": 5},
    })
    async with _client("anthropic", payload) as client:
        result = await _invoke(_bridge(client, "anthropic"), streaming=streaming, tools=tools)
    if streaming and not tools:
        assert "declined" in "".join(event.text or "" for event in result)
    else:
        assert "declined" in result.content
        assert result.tool_calls == []
        assert result.metadata["finish_reason"] == "refusal"


@pytest.mark.asyncio
@pytest.mark.parametrize("base,path", [
    ("https://api.anthropic.com", "/v1/messages"),
    ("https://api.anthropic.com/v1/", "/v1/messages"),
    ("https://gateway.test/apps/anthropic", "/apps/anthropic/v1/messages"),
])
async def test_anthropic_adapter_sends_single_versioned_messages_path(monkeypatch, base, path):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"id": "msg", "role": "assistant", "type": "message",
            "model": "claude-fable-5-2", "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}})
    monkeypatch.setattr("magi.llm.anthropic.DefaultAsyncHttpxClient",
                        lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    adapter = AnthropicAdapter(api_key="fixture", model="claude-fable-5-2", base_url=base)
    try:
        assert await adapter.generate("hi", max_tokens=32) == "ok"
        assert paths == [path]
    finally:
        await adapter._client.close()
