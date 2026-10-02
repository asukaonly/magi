"""ASR boundary, ownership, cancellation and privacy invariants."""

import asyncio
import io
import threading
import time
import uuid
import wave

import httpx
import pytest
from fastapi import FastAPI

from magi.config.models import AppConfig, LLMProviderSettings, LLMProviderASRSettings
from magi.speech.asr.contracts import ASRError, TranscriptResult
from magi.speech.asr.engines import ASROptions, remote_transcribe, resolve_options
from magi.speech.asr.models import ASRModelStore
from magi.speech.asr.service import ASRService, MAX_ACTIVE


def wav(rate=16000, channels=1):
    output = io.BytesIO()
    with wave.open(output, "wb") as f:
        f.setnchannels(channels)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"\x01\x00" * rate * channels)
    return output.getvalue()


def request_id():
    return f"{int(time.time() * 1000)}-{uuid.uuid4()}"


@pytest.fixture
async def service(tmp_path, monkeypatch):
    config = AppConfig()
    config.speech.asr.enabled = True
    models = ASRModelStore(tmp_path)

    async def ready():
        return True

    monkeypatch.setattr(models, "ready", ready)
    s = ASRService(models, lambda: config)
    yield s
    await s.close()


async def terminal(s, owner, identity):
    for _ in range(100):
        result = s.get(owner, s.runtime_id, identity)
        if result.state not in {"running", "queued"}:
            return result
        await asyncio.sleep(0.01)
    pytest.fail("Transcription did not terminate")


async def test_dedup_scoped_to_device_and_same_audio(service, monkeypatch):
    calls = []

    def transcribe(*args):
        calls.append(1)
        return TranscriptResult(text="你好", no_speech=False, engine="local", model="test")

    monkeypatch.setattr(service.local, "transcribe", transcribe)
    identity = request_id()
    await service.submit(
        "a", service.runtime_id, identity, wav(), config_revision=service.revision()
    )
    result = await terminal(service, "a", identity)
    assert result.result.text == "你好"
    assert (
        await service.submit(
            "a", service.runtime_id, identity, wav(), config_revision=service.revision()
        )
    ).state == "succeeded"
    assert len(calls) == 1
    with pytest.raises(ASRError, match="request_not_found"):
        service.get("b", service.runtime_id, identity)
    changed = wav()[:-2] + b"\x02\x00"
    with pytest.raises(ASRError, match="request_conflict"):
        await service.submit(
            "a", service.runtime_id, identity, changed, config_revision=service.revision()
        )


async def test_cancel_tombstone_wins_late_upload(service):
    identity = request_id()
    service.cancel("a", service.runtime_id, identity)
    result = await service.submit(
        "a", service.runtime_id, identity, wav(), config_revision=service.revision()
    )
    assert result.state == "cancelled"
    assert not service.local_in_use()


async def test_cancel_native_call_keeps_compute_lease(service, monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []

    def transcribe(*args):
        calls.append(1)
        started.set()
        release.wait(3)
        return TranscriptResult(text="stale", no_speech=False, engine="local", model="test")

    monkeypatch.setattr(service.local, "transcribe", transcribe)
    first, second = request_id(), request_id()
    try:
        await service.submit(
            "a", service.runtime_id, first, wav(), config_revision=service.revision()
        )
        assert await asyncio.to_thread(started.wait, 1)
        service.cancel("a", service.runtime_id, first)
        await service.submit(
            "a", service.runtime_id, second, wav(), config_revision=service.revision()
        )
        await asyncio.sleep(0.03)
        assert len(calls) == 1 and service.local_in_use()
        assert service.get("a", service.runtime_id, first).result is None
        release.set()
        assert (await terminal(service, "a", second)).state == "succeeded"
        assert service.get("a", service.runtime_id, first).state == "cancelled"
    finally:
        release.set()


async def test_bound_queue_and_clear_rotates_runtime(service, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(service.local, "transcribe", lambda *args: release.wait(2))
    try:
        for _ in range(MAX_ACTIVE):
            await service.submit(
                "a", service.runtime_id, request_id(), wav(), config_revision=service.revision()
            )
        with pytest.raises(ASRError, match="engine_busy"):
            await service.submit(
                "a", service.runtime_id, request_id(), wav(), config_revision=service.revision()
            )
        old = service.runtime_id
        release.set()
        await service.clear()
        assert not service.entries
        with pytest.raises(ASRError, match="runtime_changed"):
            await service.submit("a", old, request_id(), wav(), config_revision=service.revision())
    finally:
        release.set()


@pytest.mark.parametrize(
    "audio", [b"bad", wav(8000), wav(channels=2), b"x" * (2 * 1024 * 1024 + 1)]
)
async def test_invalid_audio_never_admitted(service, audio):
    with pytest.raises(ASRError):
        await service.submit(
            "a", service.runtime_id, request_id(), audio, config_revision=service.revision()
        )
    assert not service.entries


async def test_expired_request_cannot_restart_paid_work(service):
    with pytest.raises(ASRError, match="request_expired"):
        await service.submit(
            "a",
            service.runtime_id,
            f"{int((time.time()-121)*1000)}-{uuid.uuid4()}",
            wav(),
            config_revision=service.revision(),
        )


def test_remote_options_are_explicit_and_frozen():
    config = AppConfig()
    config.speech.asr.enabled, config.speech.asr.mode = True, "remote"
    config.speech.asr.provider_id = "audio"
    provider = LLMProviderSettings(api_key="private", base_url="https://audio.example/v1")
    provider.services.asr = LLMProviderASRSettings(enabled=True, model="transcriber")
    config.llm.providers["audio"] = provider
    options = resolve_options(config)
    provider.api_key = "changed"
    assert options.api_key == "private" and "private" not in repr(options)
    assert options.endpoint == "https://audio.example/v1/audio/transcriptions"
    provider.services.asr.enabled = False
    with pytest.raises(ASRError, match="provider_not_configured"):
        resolve_options(config)


async def test_remote_protocol_and_bounded_response(monkeypatch):
    real_client = httpx.AsyncClient
    calls = []

    async def respond(request):
        calls.append(request)
        assert request.url.path == "/v1/audio/transcriptions"
        assert b'name="file"' in request.content and b"RIFF" in request.content
        return httpx.Response(200, json={"text": "Hello 世界"})

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)
    )
    options = ASROptions(
        "remote", "model", "auto", "https://test/v1/audio/transcriptions", "secret"
    )
    result = await remote_transcribe(wav(), options)
    assert result.text == "Hello 世界" and result.language is None
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status,body,code",
    [
        (401, {}, "provider_auth_failed"),
        (429, {}, "provider_busy"),
        (200, {"text": 3}, "provider_invalid_response"),
        (200, {"text": "x" * 140000}, "provider_invalid_response"),
    ],
)
async def test_remote_errors_are_sanitized(monkeypatch, status, body, code):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(lambda req: httpx.Response(status, json=body)), **kw
        ),
    )
    with pytest.raises(ASRError, match=code):
        await remote_transcribe(
            wav(), ASROptions("remote", "m", "auto", "https://test/transcriptions")
        )


async def test_public_routes_authenticate_and_reconcile(service, monkeypatch):
    from magi.api.routers import asr
    from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router

    monkeypatch.setenv("MAGI_DATA_EPOCH", "epoch")
    monkeypatch.setattr(asr, "get_asr_service", lambda: service)
    app = FastAPI()
    app.include_router(
        _build_public_router(asr.asr_router, _PUBLIC_ROUTE_METHODS["asr"]), prefix="/api/speech/asr"
    )
    headers = {
        "x-magi-client-id": "a",
        "x-magi-data-epoch": "epoch",
        "x-magi-asr-runtime": service.runtime_id,
        "x-magi-asr-config": service.revision(),
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/speech/asr/models")).status_code == 401
        assert (await client.get("/api/speech/asr/models", headers=headers)).status_code == 200
        identity = request_id()
        path = f"/api/speech/asr/transcriptions/{identity}"
        assert (await client.post(path + "/cancel", headers=headers)).status_code == 200
        response = await client.post(
            path, headers={**headers, "content-type": "audio/wav"}, content=wav()
        )
        assert response.status_code == 202 and response.json()["state"] == "cancelled"
        assert (await client.get(path, headers=headers)).json()["state"] == "cancelled"
        assert (
            await client.get(path, headers={**headers, "x-magi-client-id": "b"})
        ).status_code == 404
        assert (
            await client.get(path, headers={**headers, "x-magi-data-epoch": "old"})
        ).status_code == 409


def test_config_roundtrip_masks_asr_credentials():
    from magi.api.routers.config_schemas import SystemConfigModel, LLMProviderConfigModel
    from magi.api.services.config_secrets import (
        mask_system_config_secrets,
        normalize_masked_secrets,
    )

    config = AppConfig()
    config.llm.providers["audio"] = LLMProviderSettings()
    config.llm.providers["audio"].services.asr.api_key = "private-asr"
    response = SystemConfigModel()
    response.llm.providers["audio"] = LLMProviderConfigModel.model_validate(
        config.llm.providers["audio"].model_dump()
    )
    masked = mask_system_config_secrets(response)
    assert masked.llm.providers["audio"].services.asr.api_key == "***"
    assert (
        normalize_masked_secrets(masked, config).llm.providers["audio"].services.asr.api_key
        == "private-asr"
    )


async def test_configuration_changed_during_capture_never_uploads(service):
    revision = service.revision()
    service.config().speech.asr.mode = "remote"
    with pytest.raises(ASRError, match="configuration_changed"):
        await service.submit("a", service.runtime_id, request_id(), wav(), config_revision=revision)
    assert not service.entries


async def test_cancel_during_model_verification_wins(service, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def ready():
        entered.set()
        await release.wait()
        return True

    monkeypatch.setattr(service.models, "ready", ready)
    identity = request_id()
    pending = asyncio.create_task(
        service.submit("a", service.runtime_id, identity, wav(), config_revision=service.revision())
    )
    await entered.wait()
    service.cancel("a", service.runtime_id, identity)
    release.set()
    assert (await pending).state == "cancelled"
    assert not service.local_in_use()
