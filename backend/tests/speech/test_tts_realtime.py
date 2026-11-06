"""Realtime speech transport completion, cancellation and bounds."""
import base64
import json
import threading
from contextlib import asynccontextmanager

import pytest

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
