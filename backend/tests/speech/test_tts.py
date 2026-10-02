import asyncio
import hashlib
import threading
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from magi.config.models import AppConfig, LLMProviderSettings
from magi.speech.tts.contracts import MessageSource, SynthesisRequest, TextSource
from magi.speech.tts.engines import EngineOptions, TTSEngine, pcm_wav, resolve_options
from magi.speech.tts.models import ModelManager
from magi.speech.tts.service import SynthesisService
from magi.speech.tts.text import clean_segments


@pytest.mark.parametrize("source,expected", [
    ("# Hello\n\nA **good** [link](https://example.com).", "Hello A good link."),
    ("Read `Magi` and `rm -rf /very/long/path`.", "Read Magi and ."),
    ("Before\n```python\nsecret()\n```\nAfter", "Before After"),
    ("| Key | Value |\n|---|---|\n| hide | me |\n\nVisible", "Visible"),
    ("中文。English! 2026年10月2日，15:30。", "中文。 English! 2026年10月2日，15:30。"),
    ("Version 1.13.8.中文。", "Version 1.13.8. 中文。"),
])
def test_clean_prose(source, expected):
    assert " ".join(clean_segments(source)) == expected


@pytest.mark.parametrize("source", ["```sh\nexit\n```", "https://example.com", "<script>hidden</script>", "   "])
def test_no_readable_text(source):
    with pytest.raises(ValueError, match="no_readable_text"):
        clean_segments(source)


def test_unicode_limits():
    assert all(len(x) <= 200 for x in clean_segments("中文" * 1000))
    with pytest.raises(ValueError, match="text_too_long"):
        clean_segments("中" * 4097)


def test_provider_configuration():
    config = AppConfig()
    assert resolve_options(config).engine == "local"
    config.speech.tts.engine = "remote"
    config.speech.tts.provider_id = "openai"
    with pytest.raises(ValueError, match="provider_not_configured"):
        resolve_options(config)
    provider = LLMProviderSettings(api_key="private")
    config.llm.providers["openai"] = provider
    provider.services.tts.enabled = True
    provider.services.tts.model = "gpt-4o-mini-tts"
    provider.services.tts.voice = "coral"
    provider.services.tts.response_format = "wav"
    assert resolve_options(config).api_key == "private"
    provider.services.tts.base_url = "https://user:secret@bad.test"
    with pytest.raises(ValueError, match="invalid_endpoint"):
        resolve_options(config)


@pytest.fixture
def synth(tmp_path):
    models = ModelManager(tmp_path / "models")
    service = SynthesisService(tmp_path / "receipts", models, AsyncMock(return_value="Hello"))
    service.engine.synthesize = AsyncMock(return_value=pcm_wav(b"\x01\x00" * 1600, 16000))
    return service


def request(text="Hello. Another sentence.", request_id=None):
    return SynthesisRequest(request_id=request_id or uuid4(), source=TextSource(kind="text", text=text))


OPTIONS = EngineOptions("local", "kokoro", "zf_xiaobei", 1)


async def complete_segment(service, owner, job, seq):
    await service.advance(owner, job.job_id, seq)
    await service.receipts[job.job_id].task


@pytest.mark.asyncio
async def test_pull_order_idempotency_and_no_playback(synth):
    body = request()
    job = await synth.create("owner", body, OPTIONS)
    synth.engine.synthesize.assert_not_called()
    assert (await synth.create("owner", body, OPTIONS)).job_id == job.job_id
    with pytest.raises(ValueError, match="sequence_error"):
        await synth.advance("owner", job.job_id, 1)
    await complete_segment(synth, "owner", job, 0)
    assert (await synth.get("owner", job.job_id)).state == "ready"
    assert (await synth.segment("owner", job.job_id, 0)).data.startswith(b"RIFF")
    await synth.advance("owner", job.job_id, 0)
    assert synth.engine.synthesize.call_count == 1
    await complete_segment(synth, "owner", job, 1)
    assert (await synth.get("owner", job.job_id)).state == "completed"


@pytest.mark.asyncio
async def test_synthesized_clip_can_be_delivered_without_resynthesis(synth):
    from magi.channels.audio_delivery import AudioDeliveryRouter
    from magi.channels.registry import ChannelRegistry
    from magi_plugin_sdk.audio import AudioOutputChannel, AudioOutputTarget, AudioPlaybackReceipt, AudioPlaybackState

    channel = AsyncMock(spec=AudioOutputChannel)
    channel.channel_type = "test-audio"
    target = AudioOutputTarget("test-audio", "speaker")
    channel.play_audio.side_effect = lambda target, clip, request_id: AudioPlaybackReceipt(
        target, request_id, "accepted", AudioPlaybackState.ACCEPTED)
    registry = ChannelRegistry()
    registry.register(channel)
    job = await synth.create("owner", request("Hello"), OPTIONS)
    await complete_segment(synth, "owner", job, 0)
    clip = await synth.segment("owner", job.job_id, 0)
    router = AudioDeliveryRouter(registry)
    for request_id in ("one", "two"):
        assert (await router.play(target, clip, request_id)).state == AudioPlaybackState.ACCEPTED
    assert channel.play_audio.await_count == 2
    assert channel.play_audio.call_args.args[1] is clip
    synth.engine.synthesize.assert_awaited_once()


@pytest.mark.asyncio
async def test_owner_and_request_conflicts(synth):
    body = request()
    job = await synth.create("a", body, OPTIONS)
    with pytest.raises(ValueError, match="not_found"):
        await synth.get("b", job.job_id)
    with pytest.raises(ValueError, match="request_conflict"):
        await synth.create("a", request("Changed", body.request_id), OPTIONS)
    assert (await synth.create("b", body, OPTIONS)).job_id != job.job_id


@pytest.mark.asyncio
async def test_cancel_discards_late_audio(synth):
    release = asyncio.Event()
    async def delayed(*_):
        await release.wait()
        return pcm_wav(b"\x00\x00" * 100, 16000)
    synth.engine.synthesize.side_effect = delayed
    job = await synth.create("a", request(), OPTIONS)
    await synth.advance("a", job.job_id, 0)
    await asyncio.sleep(0)
    assert synth.cancel("a", job.job_id).state == "cancelling"
    release.set()
    await synth.receipts[job.job_id].task
    assert (await synth.get("a", job.job_id)).state == "cancelled"
    assert not list(synth.root.glob("*/*.wav"))


@pytest.mark.asyncio
async def test_restart_does_not_repeat_inference(synth):
    job = await synth.create("a", request(), OPTIONS)
    restored = SynthesisService(synth.root, synth.models, synth.read_message)
    assert (await restored.get("a", job.job_id)).state == "unknown"
    with pytest.raises(ValueError, match="synthesis_closed"):
        await restored.advance("a", job.job_id, 0)


@pytest.mark.asyncio
async def test_expiry_does_not_regenerate(synth, monkeypatch):
    job = await synth.create("a", request(), OPTIONS)
    await complete_segment(synth, "a", job, 0)
    monkeypatch.setattr("magi.speech.tts.service.time.time", lambda: job.expires_at + 1)
    with pytest.raises(ValueError, match="audio_expired"):
        await synth.segment("a", job.job_id, 0)
    assert synth.engine.synthesize.call_count == 1


@pytest.mark.asyncio
async def test_clear_seals_admission_and_drops_late_result(synth):
    release = asyncio.Event()
    async def delayed(*_):
        await release.wait()
        return pcm_wav(b"\x00\x00" * 100, 16000)
    synth.engine.synthesize.side_effect = delayed
    job = await synth.create("a", request(), OPTIONS)
    await synth.advance("a", job.job_id, 0)
    task = synth.receipts[job.job_id].task
    await asyncio.sleep(0)
    async with synth.clear_boundary():
        with pytest.raises(ValueError, match="content_clearing"):
            await synth.create("a", request(), OPTIONS)
    release.set()
    await task
    assert not list(synth.root.iterdir())


@pytest.mark.asyncio
async def test_revised_message_blocks_audio(synth):
    source = MessageSource(kind="message", session_id="s", message_id="m", revision="a" * 64)
    job = await synth.create("a", SynthesisRequest(request_id=uuid4(), source=source), OPTIONS)
    await complete_segment(synth, "a", job, 0)
    synth.read_message.side_effect = ValueError("stale_message")
    with pytest.raises(ValueError, match="stale_message"):
        await synth.segment("a", job.job_id, 0)
    assert not list(synth.root.glob("*/*.wav"))


@pytest.mark.asyncio
async def test_cancel_before_admission_prevents_generation(synth):
    body = request()
    cancelled = await synth.cancel_request("a", str(body.request_id))
    job = await synth.create("a", body, OPTIONS)
    assert job.job_id == cancelled.job_id and job.state == "cancelled"
    synth.engine.synthesize.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ReadTimeout("private provider details"), asyncio.TimeoutError()])
async def test_remote_unknown_is_not_retried(synth, error):
    synth.engine.synthesize.side_effect = error
    job = await synth.create("a", request(), EngineOptions("remote", "model", "voice", 1))
    await complete_segment(synth, "a", job, 0)
    result = await synth.get("a", job.job_id)
    assert result.state == "unknown" and result.error == "provider_outcome_unknown"
    with pytest.raises(ValueError, match="synthesis_closed"):
        await synth.advance("a", job.job_id, 0)
    assert synth.engine.synthesize.call_count == 1


@pytest.mark.asyncio
async def test_remote_validates_complete_wav_and_no_retry(tmp_path, monkeypatch):
    clip = pcm_wav(b"\x01\x00" * 1000, 24000)
    calls = []
    def respond(req):
        calls.append(req)
        return httpx.Response(200, content=clip.data)
    factory = httpx.AsyncClient
    monkeypatch.setattr("magi.speech.tts.engines.httpx.AsyncClient", lambda **kw: factory(transport=httpx.MockTransport(respond), **kw))
    engine = TTSEngine(ModelManager(tmp_path))
    result = await engine.synthesize("Hi", EngineOptions("remote", "tts-1", "alloy", 1, "https://service.test/v1", "secret"), threading.Event())
    assert result.data == clip.data
    assert len(calls) == 1
    assert calls[0].url.path == "/v1/audio/speech"


@pytest.mark.asyncio
async def test_public_router_requires_gateway_identity_and_reaches_audio(synth, monkeypatch):
    from magi.api.routers import tts
    from magi.api.routes import _build_public_router, _PUBLIC_ROUTE_METHODS
    monkeypatch.setattr(tts, "_service", synth)
    app = FastAPI()
    app.include_router(_build_public_router(tts.tts_router, _PUBLIC_ROUTE_METHODS["tts"]), prefix="/api/speech/tts")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        assert (await client.get("/api/speech/tts/models")).status_code == 401
        client.headers["x-magi-client-id"] = "desktop"
        assert (await client.get("/api/speech/tts/models")).status_code == 200
        monkeypatch.setattr(tts, "get_config", lambda: AppConfig())
        assert (await client.delete("/api/speech/tts/models")).status_code == 200
        body = request("Hello")
        response = await client.post("/api/speech/tts/syntheses", json=body.model_dump(mode="json"))
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert (await client.delete("/api/speech/tts/models")).status_code == 409
        assert (await client.post(f"/api/speech/tts/syntheses/{job_id}/segments/0")).status_code == 202
        await synth.receipts[job_id].task
        audio = await client.get(f"/api/speech/tts/syntheses/{job_id}/segments/0")
        assert audio.status_code == 200 and audio.content.startswith(b"RIFF")
        client.headers["x-magi-client-id"] = "other"
        assert (await client.get(f"/api/speech/tts/syntheses/{job_id}")).status_code == 404
