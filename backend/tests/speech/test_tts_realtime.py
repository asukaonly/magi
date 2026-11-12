"""Realtime speech transport completion, cancellation and bounds."""
import base64
import json
import threading
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.events.domain_payloads import SpanCompleted
from magi.events.events import EventTypes
from magi.speech.tts.engines import EngineOptions, TTSEngine
from magi.speech.tts.models import TTSModelStore
from magi.speech.tts.realtime import synthesize_pcm


OPTIONS = EngineOptions("remote", "gpt-realtime-2.1-mini", "marin", 1,
                        "https://api.openai.com/v1", "test-key", proxy_url="http://proxy.test:8080")


def connection(monkeypatch, events, cancellation=None):
    sent, closed, options = [], [], {}
    class Socket:
        async def send(self, value):
            sent.append(json.loads(value))
        async def recv(self):
            if cancellation is not None:
                cancellation.set()
            return json.dumps(events.pop(0))
    @asynccontextmanager
    async def connect(url, **kwargs):
        options.update(url=url, **kwargs)
        try:
            yield Socket()
        finally:
            closed.append(True)
    monkeypatch.setattr("magi.speech.tts.realtime.connect", connect)
    return sent, closed, options


@pytest.mark.asyncio
async def test_realtime_speech_returns_complete_wav_and_closes(tmp_path, monkeypatch):
    pcm = b"\x01\x00" * 100
    sent, closed, options = connection(monkeypatch, [
        {"type": "session.updated"},
        {"type": "response.output_audio.delta", "delta": base64.b64encode(pcm).decode()},
        {"type": "response.done", "response": {"status": "completed"}},
    ])
    clip = await TTSEngine(TTSModelStore(tmp_path)).synthesize("Read me", OPTIONS, threading.Event())
    assert clip.data.startswith(b"RIFF") and clip.data.endswith(pcm)
    assert options["url"] == "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1-mini"
    assert options["proxy"] == OPTIONS.proxy_url
    assert options["additional_headers"] == {"Authorization": "Bearer test-key"}
    assert sent[0]["session"]["audio"]["output"]["voice"] == "marin"
    assert sent[1]["response"]["input"][0]["content"][0]["text"] == "Read me"
    assert closed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "incomplete"])
async def test_realtime_usage_reaches_trace_bus_on_success_and_failure(tmp_path, monkeypatch, status):
    bus = MagicMock(publish=AsyncMock(return_value=True))
    monkeypatch.setattr("magi.runtime_trace.span_publisher.resolve_event_bus", lambda **_: bus)
    connection(monkeypatch, [
        {"type": "response.output_audio.delta", "delta": base64.b64encode(b"\x01\x00" * 100).decode()},
        {"type": "response.done", "response": {"status": status, "usage": {
            "input_tokens": 120, "output_tokens": 110,
            "input_token_details": {"text_tokens": 100, "audio_tokens": 20, "cached_tokens": 55,
                                    "cached_tokens_details": {"text_tokens": 50, "audio_tokens": 5}},
            "output_token_details": {"text_tokens": 10, "audio_tokens": 100},
        }}},
    ])
    engine = TTSEngine(TTSModelStore(tmp_path))
    if status == "completed":
        await engine.synthesize("Private speech", OPTIONS, threading.Event())
    else:
        with pytest.raises(ValueError, match="provider_rejected"):
            await engine.synthesize("Private speech", OPTIONS, threading.Event())

    bus.publish.assert_awaited_once()
    event = bus.publish.await_args.args[0]
    assert event.type == EventTypes.SPAN_COMPLETED
    assert isinstance(event.data, SpanCompleted)
    span = event.data
    assert span.node_type == "llm_call"
    assert span.status == ("ok" if status == "completed" else "error")
    assert (span.error.message if span.error else None) == (None if status == "completed" else "provider_rejected")
    assert span.attributes["provider"] == "openai"
    assert span.attributes["model"] == OPTIONS.model
    assert span.attributes["request_kind"] == "tts"
    assert span.attributes["usage_available"] is True
    assert span.attributes["prompt_tokens"] == 120
    assert span.attributes["completion_tokens"] == 110
    assert span.attributes["total_tokens"] == 230
    usage = span.attributes["billing"]["media_usage"]
    assert usage["cached_text_input_tokens"] == 50
    assert usage["cached_audio_input_tokens"] == 5
    assert usage["audio_output_tokens"] == 100
    assert "Private speech" not in str(span)
    assert OPTIONS.api_key not in str(span)


@pytest.mark.asyncio
@pytest.mark.parametrize("event,error", [
    ({"type": "response.done", "response": {"status": "incomplete"}}, "provider_rejected"),
    ({"type": "response.done", "response": {"status": "completed"}}, "provider_invalid_response"),
    ({"type": "error"}, "provider_rejected"),
    ({"type": "response.output_audio.delta", "delta": "not base64"}, "provider_invalid_response"),
    ({"type": "response.output_audio.delta", "delta": base64.b64encode(b"a" * (2 * 1024 * 1024 + 2)).decode()}, "audio_too_large"),
])
async def test_realtime_rejects_partial_invalid_and_excess_audio(monkeypatch, event, error):
    _, closed, _ = connection(monkeypatch, [event])
    with pytest.raises(ValueError, match=error):
        await synthesize_pcm("hello", OPTIONS, threading.Event(), {})
    assert closed == [True]


@pytest.mark.asyncio
async def test_realtime_cancellation_closes_socket(monkeypatch):
    cancelled = threading.Event()
    _, closed, _ = connection(monkeypatch, [{"type": "session.created"}], cancelled)
    with pytest.raises(ValueError, match="cancelled"):
        await synthesize_pcm("hello", OPTIONS, cancelled, {})
    assert closed == [True]
