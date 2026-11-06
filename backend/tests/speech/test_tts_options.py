"""Catalog choices, external resources and reference audio through the public API."""

import hashlib

import httpx
import pytest
from fastapi import FastAPI

from magi.config.models import AppConfig, LLMProviderSettings
from magi.config.tts import TTSSettings, TTSVoicePreset
from magi.speech.tts.catalog import choices
from magi.speech.tts.engines import resolve_options, pcm_wav
from magi.speech.tts.models import TTSModelStore, VOX_ID, NANO_ID, QWEN_ID, MOSS_ID, MELO_ID
from magi.speech.tts.service import SynthesisService
from magi.speech.tts.voices import TTSReferenceStore


def test_default_and_catalog_capabilities(tmp_path):
    config = AppConfig()
    assert config.speech.tts.local_model == VOX_ID
    assert resolve_options(config).model == VOX_ID
    catalog = {m.model_id: m for m in choices(config, TTSModelStore(tmp_path))}
    assert {m.model_id for m in catalog.values() if m.recommended} == {VOX_ID, NANO_ID}
    assert catalog[NANO_ID].experimental and catalog[NANO_ID].reference_audio == "required"
    assert catalog[VOX_ID].voice_description and catalog[VOX_ID].speed_min is None
    assert len(catalog[QWEN_ID].voices) == 9 and catalog[QWEN_ID].reference_audio == "none"
    assert catalog[MOSS_ID].companion_model and not catalog[MOSS_ID].voice_description
    assert catalog[MELO_ID].speed_min == 0.5


@pytest.mark.parametrize("change,error", [
    ({"local_speed": 1.1}, "unsupported_parameter"),
    ({"local_voice": "zf_xiaobei"}, "invalid_voice"),
    ({"local_model": NANO_ID}, "reference_audio_required"),
    ({"local_model": NANO_ID, "reference_audio": "a" * 64, "voice_description": "calm"}, "unsupported_parameter"),
    ({"local_model": QWEN_ID, "local_voice": "serena", "reference_audio": "a" * 64}, "unsupported_parameter"),
    ({"local_codec_path": "/tmp/codec"}, "model_directory_invalid"),
])
def test_model_specific_options_fail_closed(change, error):
    config = AppConfig()
    config.speech.tts = TTSSettings(**change)
    with pytest.raises(ValueError, match=error):
        resolve_options(config)


def test_named_presets_validate_model_capabilities():
    config = AppConfig()
    config.speech.tts.voice_presets = [TTSVoicePreset(id="a" * 32, name="Calm", model_id=QWEN_ID,
                                                     voice="serena", description="Calm voice")]
    assert resolve_options(config).model == VOX_ID
    config.speech.tts.voice_presets[0].reference_audio = "a" * 64
    with pytest.raises(ValueError, match="unsupported_parameter"):
        resolve_options(config)
    with pytest.raises(ValueError, match="unique"):
        TTSSettings(voice_presets=config.speech.tts.voice_presets * 2)


@pytest.mark.parametrize("url,valid", [("http://192.168.1.8:8880/v1", True),
    ("http://localhost:8880/v1", True), ("https://tts.example/v1", True),
    ("http://8.8.8.8/v1", False), ("http://192.168.1.8/v1?key=secret", False)])
def test_self_hosted_transport_is_explicit(url, valid):
    config = AppConfig()
    provider = LLMProviderSettings(provider_type="custom")
    provider.services.tts.enabled = True
    provider.services.tts.protocol = "openai_compatible"
    provider.services.tts.base_url = url
    config.llm.providers["private"] = provider
    config.speech.tts = TTSSettings(engine="remote", provider_id="private", remote_model="my-model", remote_voice="my-voice")
    if valid:
        options = resolve_options(config)
        assert options.base_url == url and options.proxy_url is None
    else:
        with pytest.raises(ValueError, match="invalid_endpoint"):
            resolve_options(config)


def small_manifest(manager, monkeypatch):
    files = [("model.safetensors", b"model"), ("codec/model.safetensors", b"codec")]
    manifest = {"repo": "test/model", "revision": "fixed", "files": [
        {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
         **({"repo": "test/codec", "revision": "codec-fixed", "source_path": "model.safetensors"} if name.startswith("codec") else {})}
        for name, data in files
    ]}
    monkeypatch.setattr(manager, "manifest", lambda: manifest)
    return files


def test_external_directories_are_verified_in_place_and_never_deleted(tmp_path, monkeypatch):
    manager = TTSModelStore(tmp_path / "managed").get(NANO_ID)
    files = small_manifest(manager, monkeypatch)
    model, codec = tmp_path / "mine", tmp_path / "codec"
    model.mkdir()
    codec.mkdir()
    (model / "model.safetensors").write_bytes(files[0][1])
    (codec / "model.safetensors").write_bytes(files[1][1])
    assert manager.inspect_directory(str(model), str(codec)).state == "ready"
    assert not (model / "verified.json").exists()
    manager.delete()
    assert (model / "model.safetensors").read_bytes() == b"model"
    (codec / "model.safetensors").write_bytes(b"wrong")
    with pytest.raises(ValueError, match="model_checksum_failed"):
        manager.inspect_directory(str(model), str(codec))
    with pytest.raises(ValueError, match="model_directory_invalid"):
        manager.inspect_directory("test/model")


@pytest.mark.asyncio
async def test_companion_download_uses_its_own_pinned_revision(tmp_path, monkeypatch):
    manager = TTSModelStore(tmp_path).get(NANO_ID)
    files = small_manifest(manager, monkeypatch)
    requests = []
    def respond(request):
        requests.append(request.url.path)
        return httpx.Response(200, content=files[1 if '/codec/' in request.url.path else 0][1])
    factory = httpx.AsyncClient
    monkeypatch.setattr("magi.speech.tts.models.httpx.AsyncClient", lambda **kw: factory(transport=httpx.MockTransport(respond), **kw))
    manager.download()
    await manager.task
    assert manager.snapshot().state == "ready"
    assert set(requests) == {"/test/model/resolve/fixed/model.safetensors", "/test/codec/resolve/codec-fixed/model.safetensors"}
    manager.verify()


def test_reference_audio_validation_and_integrity(tmp_path):
    store = TTSReferenceStore(tmp_path)
    wav = pcm_wav(b"\x01\x00" * 24000 * 3, 24000).data
    info = store.add(wav, "My voice")
    assert info.seconds == 3
    assert store.add(wav, "Renamed").id == info.id and len(store.list()) == 1
    assert store.path(info.id).read_bytes() == wav
    with pytest.raises(ValueError, match="reference_audio_invalid"):
        store.add(wav[:100], "Broken")
    with pytest.raises(ValueError, match="reference_audio_missing"):
        store.path("../private")
    store.path(info.id).write_bytes(wav[:-2] + b"\x02\x00")
    with pytest.raises(ValueError, match="reference_audio_invalid"):
        store.path(info.id)


@pytest.mark.asyncio
async def test_public_routes_enforce_auth_reference_ownership_and_settings_revision(tmp_path, monkeypatch):
    from magi.api.routers import tts
    from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
    async def read(_):
        return "Hello"
    service = SynthesisService(tmp_path / "jobs", TTSModelStore(tmp_path / "models"), read)
    config = AppConfig()
    monkeypatch.setattr("magi.bootstrap.speech_runtime._service", service)
    monkeypatch.setattr(tts, "get_config", lambda: config)
    def save(values):
        config.speech.tts = TTSSettings.model_validate(values["speech.tts"])
        return True
    monkeypatch.setattr(tts, "save_config", save)
    app = FastAPI()
    app.include_router(_build_public_router(tts.tts_router, _PUBLIC_ROUTE_METHODS["tts"]))
    wav = pcm_wav(b"\x01\x00" * 24000 * 3, 24000).data
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        assert (await client.post("/references", content=wav)).status_code == 401
        assert (await client.post("/models/inspect", json={"model_id": VOX_ID, "path": "/missing"})).status_code == 401
        client.headers["x-magi-client-id"] = "desktop"
        response = await client.post("/references", content=wav, params={"name": "Voice"})
        assert response.status_code == 200
        reference = response.json()["id"]
        current = (await client.get("/settings")).json()
        assert current["reference_audio"][0]["id"] == reference
        new = {**current["settings"], "reference_audio": reference}
        assert (await client.put("/settings", json={"settings": new, "revision": "old"})).status_code == 409
        assert (await client.put("/settings", json={"settings": new, "revision": current["revision"]})).status_code == 200
        assert (await client.delete(f"/references/{reference}")).status_code == 409
        config.speech.tts.reference_audio = ""
        assert (await client.delete(f"/references/{reference}")).status_code == 204
        assert not service.references.list()
        assert (await client.post("/references", content=b"x" * (2 * 1024 * 1024 + 1))).status_code == 413
        assert (await client.post("/models/inspect", json={"model_id": VOX_ID, "path": "/missing"})).status_code == 422


def test_reference_upload_replaces_symlink_without_writing_its_target(tmp_path):
    store = TTSReferenceStore(tmp_path / "voices")
    data = pcm_wav(b"\x00\x00" * 24000 * 4, 24000).data
    identity = hashlib.sha256(data).hexdigest()
    target = tmp_path / "unrelated"
    target.write_bytes(b"preserve")
    (store.root / (identity + ".wav")).symlink_to(target)
    store.add(data, "Voice")
    assert target.read_bytes() == b"preserve"
    assert not store.path(identity).is_symlink()
    (store.root / "oversized.json").write_text("x" * 4097)
    assert len(store.list()) == 1


def test_reference_removal_can_repair_corrupt_files(tmp_path):
    store = TTSReferenceStore(tmp_path)
    item = store.add(pcm_wav(b"\x00\x00" * 24000 * 4, 24000).data, "Voice")
    (tmp_path / (item.id + ".wav")).write_bytes(b"broken")
    store.delete(item.id)
    store.delete(item.id)
    assert store.list() == []
    assert not list(tmp_path.glob("*.wav"))
