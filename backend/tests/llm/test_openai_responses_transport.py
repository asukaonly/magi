"""Native Responses requests, continuation and stream failure boundaries."""
import json
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI

from magi.config.models import ThinkingDepth
from magi.llm.openai import OpenAIAdapter
from magi.llm.openai_transport import create_completion, _responses_kwargs
from magi.llm.provider_bridge import LLMProviderBridge


def response(*, tools=False, status="completed"):
    output = [{"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque"}]
    output += ([{"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "lookup", "arguments": '{"q":"hello"}', "status": "completed"}]
               if tools else [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "hello", "annotations": []}]}])
    return {"id": "resp_1", "object": "response", "created_at": 1, "status": status,
            "model": "gpt-6.1-sol", "output": output,
            "usage": {"input_tokens": 10, "output_tokens": 7, "total_tokens": 17,
                      "input_tokens_details": {"cached_tokens": 5}, "output_tokens_details": {"reasoning_tokens": 2}}}


def events(*, tools=False, terminal="completed"):
    if tools:
        yield {"type": "response.output_item.added", "output_index": 1,
               "item": {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "lookup", "arguments": "", "status": "in_progress"}}
        yield {"type": "response.function_call_arguments.delta", "item_id": "fc_1", "output_index": 1, "delta": '{"q":"hello"}'}
    else:
        yield {"type": "response.output_text.delta", "item_id": "msg_1", "output_index": 1, "content_index": 0, "delta": "hello"}
    if terminal:
        yield {"type": f"response.{terminal}", "response": response(tools=tools, status=terminal)}


def client_for(payloads, requests):
    def handler(request):
        requests.append((request.url.path, json.loads(request.content)))
        payload = payloads.pop(0)
        if isinstance(payload, list):
            text = "".join(f"event: {event['type']}\ndata: {json.dumps({**event, 'sequence_number': i})}\n\n" for i, event in enumerate(payload))
            return httpx.Response(200, text=text, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=payload)
    return AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def bridge_for(client):
    adapter = OpenAIAdapter.__new__(OpenAIAdapter)
    adapter._model = "gpt-6.1-sol"
    adapter._provider = "openai"
    adapter._provider_plan = None
    adapter._provider_instance_id = None
    adapter._base_url = "https://api.openai.com/v1"
    adapter._client = client
    return LLMProviderBridge(adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_native_tool_roundtrip_retains_reasoning_and_usage(stream):
    requests = []
    payload = list(events(tools=True)) if stream else response(tools=True)
    async with client_for([payload, response()], requests) as client:
        bridge = bridge_for(client)
        params = dict(system_prompt="sys", messages=[{"role": "user", "content": "find"}],
                      tools=[{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}}],
                      thinking_depth=ThinkingDepth.NONE)
        if stream:
            result = (await bridge.chat_with_tools_stream(**params)).provider_response
        else:
            result = await bridge.chat_with_tools(**params)
        assert result.tool_calls[0].arguments == {"q": "hello"}
        assert result.usage.cache_read_tokens == 5
        assert result.usage.reasoning_tokens == 2
        assert result.metadata["trace_metrics"]["thinking_depth"] == "low"
        await bridge.chat_response("sys", [params["messages"][0], result.assistant_message,
                                           {"role": "tool", "tool_call_id": "call_1", "content": "found"}])
    path, request = requests[0]
    assert path == "/v1/responses"
    assert request["reasoning"]["effort"] == "low"
    assert request["store"] is False
    assert "temperature" not in request and "max_tokens" not in request
    assert request["tools"][0]["name"] == "lookup"
    assert request["tools"][0]["strict"] is False
    continuation = requests[1][1]["input"]
    assert any(item.get("encrypted_content") == "opaque" for item in continuation)
    assert any(item.get("type") == "function_call_output" and item["call_id"] == "call_1" for item in continuation)


@pytest.mark.asyncio
async def test_plain_stream_and_direct_adapter_share_responses_transport():
    requests = []
    async with client_for([list(events()), response()], requests) as client:
        bridge = bridge_for(client)
        output = [event async for event in bridge.chat_response_stream("sys", [{"role": "user", "content": "hello"}], json_mode=True)]
        assert "".join(event.text or "" for event in output if event.kind == "text_delta") == "hello"
        assert requests[0][1]["text"]["format"] == {"type": "json_object"}
        assert await bridge.llm.generate("hello") == "hello"
        assert all(path.endswith("/responses") for path, _ in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", [None, "failed", "incomplete"])
async def test_stream_failure_never_returns_partial_tools(terminal):
    async with client_for([list(events(tools=True, terminal=terminal))], []) as client:
        bridge = bridge_for(client)
        with pytest.raises(RuntimeError):
            await bridge.chat_with_tools_stream("sys", [{"role": "user", "content": "hello"}], [])


@pytest.mark.asyncio
async def test_responses_stream_closes_when_cancelled():
    closed = []
    class Stream:
        async def __aiter__(self):
            yield SimpleNamespace(type="response.output_text.delta", delta="hello")
            raise AssertionError("Consumer should stop after one chunk")
        async def close(self):
            closed.append(True)
    async def create(**kwargs):
        return Stream()
    stream = await create_completion(SimpleNamespace(responses=SimpleNamespace(create=create)), model="gpt-6-luna", messages=[], stream=True)
    await anext(stream)
    await stream.aclose()
    assert closed == [True]


def test_multimodal_and_optional_reasoning_request():
    request = _responses_kwargs({"model": "gpt-6-luna", "reasoning_effort": "none", "temperature": 0.5,
                                "messages": [{"role": "user", "content": [{"type": "text", "text": "describe"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}}]}]})
    assert request["temperature"] == 0.5
    assert request["input"][0]["content"][1]["type"] == "input_image"
