"""Verify raw SDK diagnostics remain distinct from normalized runtime output."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from anthropic.types import Message, RawMessageStreamEvent
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from pydantic import TypeAdapter

from magi.llm.provider_bridge import LLMProviderBridge
from magi.llm.provider_bridge import logging as provider_logging
from magi.llm.provider_bridge.logging import RawProviderResponseLogger
from magi.llm.streaming_events import stream_scope


@pytest.fixture
def raw_records(monkeypatch, caplog):
    logger = logging.getLogger("test.raw_provider")
    caplog.set_level(logging.DEBUG, logger=logger.name)
    monkeypatch.setattr(provider_logging, "get_llm_logger", lambda _: logger)
    monkeypatch.setattr(provider_logging, "full_content_logging_enabled", lambda: True)
    return caplog


def _payloads(records):
    return [
        json.loads(record.args[2])
        for record in records.records
        if record.name == "test.raw_provider" and record.msg == "%s [%s] %s"
    ]


def _bridge(response, protocol):
    create = AsyncMock(return_value=response)
    adapter = SimpleNamespace(
        provider_name=protocol,
        model_name="diagnostic-model",
        base_url=None,
        _client=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
            messages=SimpleNamespace(create=create),
        ),
    )
    bridge = LLMProviderBridge(adapter)
    bridge.is_anthropic = lambda: protocol == "anthropic"
    bridge._operations._apply_provider_options = lambda kwargs, _: kwargs
    bridge._operations._emit_usage_event = AsyncMock()
    return bridge


def _response(protocol, content):
    if protocol == "anthropic":
        return Message.model_validate({
            "id": "msg-raw", "type": "message", "role": "assistant",
            "model": "diagnostic-model", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": content}],
            "usage": {"input_tokens": 3, "output_tokens": 5},
        })
    return ChatCompletion.model_validate({
        "id": "completion-raw", "object": "chat.completion", "created": 1,
        "model": "diagnostic-model",
        "choices": [{
            "index": 0, "finish_reason": "stop",
            "message": {
                "role": "assistant", "content": content,
                "reasoning_content": "separate reasoning",
            },
        }],
        "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
@pytest.mark.parametrize("with_tools", [False, True])
async def test_native_response_logged_before_parsing_and_trace_preview(
    raw_records, protocol, with_tools,
):
    content = "<tool_result>protocol artifact</tool_result>\n" + "正文 " * 300 + "</think>"
    response = _response(protocol, content)
    original = response.model_dump()
    bridge = _bridge(response, protocol)
    parse_name = f"_parse_{protocol}_response"
    parse = getattr(bridge._operations, parse_name)

    def checked_parse(value):
        assert _payloads(raw_records)[0]["raw_response"] == original
        return parse(value)

    setattr(bridge._operations, parse_name, checked_parse)
    method = bridge.chat_with_tools if with_tools else bridge.chat_response
    result = await method(
        system_prompt="system", messages=[{"role": "user", "content": "hello"}],
        event_context={"request_id": "req-raw", "turn_id": "turn-raw"},
        **({"tools": []} if with_tools else {}),
    )
    payload = _payloads(raw_records)[0]
    assert payload["request_id"] == "req-raw"
    assert payload["turn_id"] == "turn-raw"
    assert payload["capture_stage"] == "sdk_before_normalization"
    assert payload["raw_response"] == original
    assert response.model_dump() == original
    preview = bridge._operations._emit_usage_event.await_args.kwargs["event_context"]["response_preview"]
    assert preview == " ".join(result.content.split())[:240]
    if protocol == "openai" or not with_tools:
        assert "protocol artifact" not in result.content
        assert result.content.endswith("</think>")


async def _stream(events):
    for event in events:
        yield event


def _stream_events(protocol):
    if protocol == "openai":
        deltas = [
            {"reasoning_content": "separate reasoning"},
            {"content": "<thi"}, {"content": "nk>inline reasoning</think>answer"},
        ]
        return [ChatCompletionChunk.model_validate({
            "id": "stream-raw", "object": "chat.completion.chunk",
            "created": 1, "model": "diagnostic-model",
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        }) for delta in deltas]
    event_parser = TypeAdapter(RawMessageStreamEvent)
    return [event_parser.validate_python(value) for value in [
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "thinking_delta", "thinking": "separate reasoning"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "text_delta", "text": "answer"}},
        {"type": "content_block_stop", "index": 1},
    ]]


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
@pytest.mark.parametrize("with_tools", [False, True])
async def test_stream_logs_sdk_chunks_before_reasoning_separation(
    raw_records, protocol, with_tools,
):
    events = _stream_events(protocol)
    bridge = _bridge(_stream(events), protocol)
    kwargs = {
        "system_prompt": "system", "messages": [{"role": "user", "content": "hello"}],
        "event_context": {"request_id": "req-stream", "session_id": "session-raw"},
    }
    emitted = []

    async def sink(event):
        emitted.append(event)

    async with stream_scope(sink, source="chat"):
        if with_tools:
            result = await bridge.chat_with_tools_stream(**kwargs, tools=[])
            assert result.provider_response.content == "answer"
        else:
            async for _ in bridge.chat_response_stream(**kwargs):
                pass
    payloads = _payloads(raw_records)
    assert len(payloads) == len(events)
    assert [p["chunk_index"] for p in payloads] == list(range(len(events)))
    assert len({p["capture_id"] for p in payloads}) == 1
    assert {p["request_id"] for p in payloads} == {"req-stream"}
    expected = [e.model_dump() for e in events]
    if protocol == "anthropic":
        expected[0]["content_block"]["signature"] = "[REDACTED]"
        assert events[0].content_block.signature == ""
    assert [p["raw_response"] for p in payloads] == expected
    assert "".join(e.text for e in emitted if e.kind == "text_delta") == "answer"


def test_disabled_logging_never_serializes_response(raw_records, monkeypatch):
    monkeypatch.setattr(provider_logging, "full_content_logging_enabled", lambda: False)

    class UnexpectedSerialization:
        def model_dump(self, **kwargs):
            pytest.fail("Disabled raw logging must not inspect response content")

    logger = RawProviderResponseLogger(_bridge(None, "openai").llm, None)
    logger.log_response(UnexpectedSerialization())
    logger.log_chunk(UnexpectedSerialization())
    assert _payloads(raw_records) == []


def test_raw_logging_redacts_credentials_and_binary_without_mutation(raw_records):
    raw = {
        "authorization": "Bearer private-credential",
        "content": "text " * 500 + "</think>",
        "audio": {"data": "encoded-audio", "transcript": "spoken text"},
        "image": {"type": "image", "source": {"data": "encoded-image"}},
    }
    logger = RawProviderResponseLogger(_bridge(None, "openai").llm, {"request_id": "req-redact"})
    logger.log_response(raw)
    captured = _payloads(raw_records)[0]["raw_response"]
    assert captured["authorization"] == "[REDACTED]"
    assert captured["content"] == raw["content"]
    assert "binary content omitted" in captured["audio"]["data"]
    assert "binary content omitted" in captured["image"]["source"]["data"]
    assert captured["audio"]["transcript"] == "spoken text"
    assert raw["audio"]["data"] == "encoded-audio"


def test_raw_capture_survives_serialization_failure(raw_records):
    class BrokenResponse:
        def __str__(self):
            raise ValueError("private serialization failure")

    logger = RawProviderResponseLogger(_bridge(None, "openai").llm, None)
    logger.log_response(BrokenResponse())
    messages = [r.getMessage() for r in raw_records.records if r.name == "test.raw_provider"]
    assert messages == ["LLM raw response logging failed: ValueError"]


@pytest.mark.asyncio
async def test_raw_response_available_even_when_parser_fails(raw_records):
    response = _response("openai", "malformed response")
    bridge = _bridge(response, "openai")

    def fail_parse(_):
        raise ValueError("parse failed")

    bridge._operations._parse_openai_response = fail_parse
    with pytest.raises(ValueError, match="parse failed"):
        await bridge.chat_with_tools(
            system_prompt="system", messages=[], tools=[],
            event_context={"request_id": "req-failure"},
        )
    assert _payloads(raw_records)[0]["raw_response"] == response.model_dump()
