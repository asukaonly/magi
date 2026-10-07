import json
import threading
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from magi.config.models import AppConfig, LLMProviderSettings
from magi.config.tts import TTSSettings
from magi.speech.tts.catalog import choices
from magi.speech.tts.contracts import SynthesisRequest
from magi.speech.tts.engines import EngineOptions, TTSEngine, dashscope_audio_url, pcm_wav, resolve_options
from magi.speech.tts.models import MELO_ID, MODEL_ID, TTSModelStore
from magi.speech.tts.service import SynthesisService


def remote_config(protocol, model, voice):
    config = AppConfig()
    provider = LLMProviderSettings(api_key="fixture-key", provider_type="custom")
    provider.services.tts.enabled = True
    provider.services.tts.protocol = protocol
    provider.services.tts.base_url = "https://provider.test/v1"
    config.llm.providers["speech"] = provider
    config.speech.tts = TTSSettings(engine="remote", provider_id="speech", remote_model=model, remote_voice=voice)
    return config


def test_catalog_and_validation_agree_on_model_specific_capabilities(tmp_path):
    config = remote_config("dashscope", "qwen3-tts-flash", "Cherry")
    catalog = choices(config, TTSModelStore(tmp_path))
    melo = next(item for item in catalog if item.model_id == MELO_ID)
    assert len(melo.voices) == 1 and melo.download_bytes == 177481452
    assert all(item.speed_min is None for item in catalog if item.engine == "remote")
    config.speech.tts.remote_speed = 1.2
    with pytest.raises(ValueError, match="unsupported_parameter"):
        resolve_options(config)
    config.speech.tts.remote_speed = 1
    config.speech.tts.instructions = "Calm and clear"
    with pytest.raises(ValueError, match="unsupported_parameter"):
        resolve_options(config)
    config.speech.tts.remote_model = "qwen3-tts-instruct-flash"
    assert resolve_options(config).instructions == "Calm and clear"
    config.speech.tts.remote_model = "cosyvoice-v3.5-plus"
    with pytest.raises(ValueError, match="invalid_model"):
        resolve_options(config)
    config.speech.tts = TTSSettings(local_model=MELO_ID, local_voice="zf_xiaobei")
    with pytest.raises(ValueError, match="invalid_voice"):
        resolve_options(config)
    config.speech.tts.local_voice = "zh_en"
    assert resolve_options(config).model == MELO_ID


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["minimax", "dashscope"])
async def test_native_protocol_complete_wav_and_private_resource_headers(tmp_path, monkeypatch, protocol):
    clip = pcm_wav(b"\x01\x00" * 100, 24000)
    requests = []
    def serve(request):
        requests.append(request)
        if request.method == "GET":
            assert "Authorization" not in request.headers
            assert request.url.scheme == "https"
            return httpx.Response(200, content=clip.data)
        assert request.headers["Authorization"] == "Bearer fixture-key"
        payload = json.loads(request.content)
        if protocol == "minimax":
            assert request.url.path == "/v1/t2a_v2"
            assert payload["audio_setting"] == {"format": "wav", "sample_rate": 24000, "channel": 1}
            assert payload["voice_setting"]["emotion"] == "calm"
            assert payload["stream"] is False and payload["output_format"] == "hex"
            return httpx.Response(200, json={"base_resp": {"status_code": 0}, "data": {"status": 2, "audio": clip.data.hex()}})
        assert request.url.path == "/v1/services/aigc/multimodal-generation/generation"
        assert payload["input"] == {"text": "Hi", "voice": "Cherry", "language_type": "Auto", "instructions": "Calm"}
        assert "speed" not in payload
        return httpx.Response(200, json={"output": {"finish_reason": "stop", "audio": {
            "url": "http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/test.wav?signature=fixture"}}})
    factory = httpx.AsyncClient
    monkeypatch.setattr("magi.speech.tts.engines.httpx.AsyncClient", lambda **kw: factory(transport=httpx.MockTransport(serve), **kw))
    config = remote_config(protocol, "speech-2.8-hd" if protocol == "minimax" else "qwen3-tts-instruct-flash", "Cherry")
    config.speech.tts.emotion = "calm" if protocol == "minimax" else ""
    config.speech.tts.instructions = "Calm" if protocol == "dashscope" else ""
    result = await TTSEngine(TTSModelStore(tmp_path)).synthesize("Hi", resolve_options(config), threading.Event())
    assert result.data == clip.data
    assert len(requests) == (1 if protocol == "minimax" else 2)


@pytest.mark.parametrize("value", [None, "http://127.0.0.1/a.wav", "https://evil.test/a.wav",
    "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com.evil.test/a.wav",
    "https://secret@dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a.wav",
    "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com:8080/a.wav"])
def test_provider_cannot_redirect_resource_fetch_to_an_arbitrary_host(value):
    with pytest.raises(ValueError, match="provider_invalid_response"):
        dashscope_audio_url(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    {"base_resp": {"status_code": 1008}, "data": None},
    {"base_resp": {"status_code": 0}, "data": None},
    {"base_resp": {"status_code": 0}, "data": {"status": 1, "audio": ""}},
    {"base_resp": {"status_code": 0}, "data": {"status": 2, "audio": b"not a wav".hex()}},
])
async def test_native_service_errors_and_partial_or_invalid_audio_fail_closed(tmp_path, monkeypatch, response):
    factory = httpx.AsyncClient
    calls = []
    def serve(request):
        calls.append(request)
        return httpx.Response(200, json=response)
    monkeypatch.setattr("magi.speech.tts.engines.httpx.AsyncClient", lambda **kw: factory(transport=httpx.MockTransport(serve), **kw))
    options = resolve_options(remote_config("minimax", "speech-2.8-hd", "voice"))
    with pytest.raises(ValueError):
        await TTSEngine(TTSModelStore(tmp_path)).synthesize("Hi", options, threading.Event())
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_selected_model_resource_routes_and_shorter_melo_segments(tmp_path, monkeypatch):
    from magi.api.routers import tts
    from magi.api.routes import _build_public_router, _PUBLIC_ROUTE_METHODS
    async def read_message(_source):
        return "Hello"
    service = SynthesisService(tmp_path / "receipts", TTSModelStore(tmp_path / "models"), read_message)
    monkeypatch.setattr(tts, "_service", service)
    monkeypatch.setattr(tts, "get_config", AppConfig)
    app = FastAPI()
    app.include_router(_build_public_router(tts.tts_router, _PUBLIC_ROUTE_METHODS["tts"]))
    body = SynthesisRequest(request_id=uuid4(), source={"kind": "text", "text": "中" * 200})
    job = await service.create("a", body, EngineOptions("local", MELO_ID, "zh_en", 0.5))
    assert all(len(part) <= 40 for part in service.receipts[job.job_id].segments)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test",
                                headers={"x-magi-client-id": "desktop"}) as client:
        catalog = await client.get("/settings")
        assert catalog.status_code == 200 and len(catalog.json()["models"]) == 2
        assert (await client.get("/models", params={"model_id": MELO_ID})).json()["model_id"] == MELO_ID
        assert (await client.delete("/models", params={"model_id": MELO_ID})).status_code == 409
        assert (await client.delete("/models", params={"model_id": MODEL_ID})).status_code == 200
        assert (await client.get("/models", params={"model_id": "../unknown"})).status_code == 422
        service.receipts[job.job_id].job.expires_at = 0
        assert (await client.delete("/models", params={"model_id": MELO_ID})).status_code == 200


@pytest.mark.asyncio
async def test_resource_deletion_does_not_mutate_an_active_engine_cache(tmp_path):
    engine = TTSEngine(TTSModelStore(tmp_path))
    cached = object()
    engine._local, engine._local_model = cached, MODEL_ID
    async with engine._lock:
        engine.unload_if_idle(MODEL_ID)
        assert engine._local is cached
    engine.unload_if_idle(MELO_ID)
    assert engine._local is cached
    engine.unload_if_idle(MODEL_ID)
    assert engine._local is None


@pytest.mark.asyncio
async def test_slow_remote_speech_uses_shorter_complete_segments(tmp_path):
    async def read_message(_source):
        return "Hello"
    service = SynthesisService(tmp_path / "receipts", TTSModelStore(tmp_path / "models"), read_message)
    text = "中" * 300
    request = SynthesisRequest(request_id=uuid4(), source={"kind": "text", "text": text})
    job = await service.create("a", request, EngineOptions("remote", "tts-1", "alloy", 0.25))
    segments = service.receipts[job.job_id].segments
    assert "".join(segments) == text
    assert max(map(len, segments)) <= 35
