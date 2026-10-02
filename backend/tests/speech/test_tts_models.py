import hashlib
from unittest.mock import AsyncMock

import httpx
import pytest

from magi.speech.tts.engines import complete_provider_wav, pcm_wav, remote_voices
from magi.speech.tts.models import ModelManager


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False])
async def test_download_verifies_bytes_before_publishing(tmp_path, monkeypatch, valid):
    manager = ModelManager(tmp_path)
    expected = b"fixed model data"
    monkeypatch.setattr(manager, "manifest", lambda: {"repo": "fixture/repo", "revision": "fixed", "files": [
        {"path": "model.onnx", "size": len(expected), "sha256": hashlib.sha256(expected).hexdigest()},
    ]})
    factory = httpx.AsyncClient
    def serve(request):
        assert request.url.path == "/fixture/repo/resolve/fixed/model.onnx"
        return httpx.Response(200, content=expected if valid else b"x" * len(expected))
    monkeypatch.setattr("magi.speech.tts.models.httpx.AsyncClient", lambda **kw: factory(transport=httpx.MockTransport(serve), **kw))
    assert manager.download().state == "downloading"
    await manager.task
    assert manager.snapshot().state == ("ready" if valid else "failed")
    assert (manager.directory / "verified.json").exists() == valid
    assert not (tmp_path / (manager.directory.name + ".partial")).exists()
    if valid:
        manager.verify()
        (manager.directory / "model.onnx").write_bytes(b"bad")
        with pytest.raises(ValueError, match="model_missing"):
            manager.verify()


@pytest.mark.asyncio
async def test_model_busy_rejects_deletion_and_download(tmp_path):
    manager = ModelManager(tmp_path)
    manager.in_use = True
    with pytest.raises(ValueError, match="model_busy"):
        manager.download()
    with pytest.raises(ValueError, match="model_busy"):
        manager.delete()


@pytest.mark.asyncio
async def test_cancel_download_before_worker_starts(tmp_path):
    manager = ModelManager(tmp_path)
    manager.download()
    assert (await manager.cancel()).state == "cancelled"
    assert not manager.directory.exists()


def test_complete_streaming_wav_only_after_response_end():
    clip = pcm_wav(b"\x01\x00" * 100, 24000)
    data = bytearray(clip.data)
    data[4:8] = b"\xff" * 4
    data[40:44] = b"\xff" * 4
    assert complete_provider_wav(bytes(data)).data == clip.data
    with pytest.raises(ValueError):
        complete_provider_wav(clip.data[:-2])


def test_remote_voice_capabilities_belong_to_the_actual_endpoint_and_model():
    assert len(remote_voices("https://api.openai.com/v1", "gpt-4o-mini-tts")) == 13
    assert len(remote_voices("https://api.openai.com/v1", "tts-1")) == 9
    assert remote_voices("https://unverified.example/v1", "gpt-4o-mini-tts") == []


@pytest.mark.asyncio
async def test_message_source_requires_final_visible_assistant_and_exact_revision(monkeypatch):
    from types import SimpleNamespace
    from magi.api.routers import tts
    from magi.speech.tts.contracts import MessageSource
    message = SimpleNamespace(role="assistant", kind="assistant", message_kind="assistant_final", content="Hello")
    read = AsyncMock(return_value=message)
    monkeypatch.setattr(tts, "require_chat_read_service", lambda: SimpleNamespace(aget_display_message=read))
    source = MessageSource(kind="message", session_id="s", message_id="m", revision=hashlib.sha256(b"Hello").hexdigest())
    assert await tts.read_message(source) == "Hello"
    assert read.call_args.kwargs == {"final_only": True}
    for kind in ("assistant_interim", "ask_request", "status_note"):
        message.message_kind = kind
        with pytest.raises(ValueError, match="stale_message"):
            await tts.read_message(source)
