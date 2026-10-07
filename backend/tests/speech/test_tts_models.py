import asyncio
import hashlib
from unittest.mock import AsyncMock

import httpx
import pytest

from magi.speech.tts.catalog import remote_voices
from magi.speech.tts.engines import complete_provider_wav, pcm_wav
from magi.speech.tts.models import MODEL_ID, MELO_ID, ModelManager


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False])
@pytest.mark.parametrize("model_id", [MODEL_ID, MELO_ID])
async def test_download_verifies_bytes_before_publishing(tmp_path, monkeypatch, valid, model_id):
    manager = ModelManager(tmp_path, model_id)
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
    assert manager.snapshot().model_id == model_id
    assert (manager.directory / "verified.json").exists() == valid
    assert (tmp_path / (manager.directory.name + ".partial")).exists() == (not valid)
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


@pytest.mark.asyncio
async def test_transfer_deadline_is_a_retryable_failed_model(tmp_path, monkeypatch):
    manager = ModelManager(tmp_path)
    monkeypatch.setattr("magi.speech.tts.models.download_files", AsyncMock(side_effect=asyncio.TimeoutError))
    manager.download()
    await manager.task
    assert manager.snapshot().state == "failed"
    assert manager.snapshot().download.phase == "failed"
    assert manager.snapshot().error == "model_download_failed"
    assert not manager.directory.exists()


def test_complete_streaming_wav_only_after_response_end():
    clip = pcm_wav(b"\x01\x00" * 100, 24000)
    data = bytearray(clip.data)
    data[4:8] = b"\xff" * 4
    data[40:44] = b"\xff" * 4
    assert complete_provider_wav(bytes(data)).data == clip.data
    with pytest.raises(ValueError):
        complete_provider_wav(clip.data[:-2])


def test_dashscope_observed_streaming_sentinels_are_provider_scoped():
    clip = pcm_wav(b"\x01\x00" * 100, 24000)
    data = bytearray(clip.data)
    data[4:8] = (0x7FFFFFBF).to_bytes(4, "little")
    data[40:44] = (0x7FFFFF9B).to_bytes(4, "little")
    assert complete_provider_wav(bytes(data), "dashscope").data == clip.data
    with pytest.raises(ValueError):
        complete_provider_wav(bytes(data), "openai")
    with pytest.raises(ValueError):
        complete_provider_wav(bytes(data[:-1]), "dashscope")
    data[40:44] = (999999).to_bytes(4, "little")
    with pytest.raises(ValueError):
        complete_provider_wav(bytes(data), "dashscope")


@pytest.mark.parametrize(
    "endpoint,model,expected",
    [
        (
            "https://api.openai.com/v1",
            "gpt-4o-mini-tts",
            "alloy ash ballad coral echo fable nova onyx sage shimmer verse marin cedar",
        ),
        ("https://api.openai.com/v1", "tts-1", "alloy ash coral echo fable nova onyx sage shimmer"),
        (
            "https://api.openai.com/v1",
            "tts-1-hd",
            "alloy ash coral echo fable nova onyx sage shimmer",
        ),
        ("https://unverified.example/v1", "gpt-4o-mini-tts", ""),
        ("https://api.openai.com.unverified.example/v1", "gpt-4o-mini-tts", ""),
        ("https://api.openai.com/v1", "unknown", ""),
    ],
)
def test_remote_voice_capabilities_belong_to_the_actual_endpoint_and_model(
    endpoint, model, expected
):
    assert remote_voices(endpoint, model) == expected.split()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        None,
        {"message_kind": "assistant_rhythm_segment"},
        {"content": "Hello edited"},
        {"role": "user"},
        {"kind": "user"},
        {"message_kind": "assistant_interim"},
        {"message_kind": "ask_request"},
        {"message_kind": "status_note"},
        "hidden",
    ],
)
async def test_message_source_requires_final_visible_assistant_and_exact_revision(
    monkeypatch, change
):
    from types import SimpleNamespace
    from magi.api.routers import tts
    from magi.speech.tts.contracts import MessageSource

    fields = dict(
        role="assistant", kind="assistant", message_kind="assistant_final", content="Hello"
    )
    if isinstance(change, dict):
        fields.update(change)
    read = AsyncMock(return_value=None if change == "hidden" else SimpleNamespace(**fields))
    monkeypatch.setattr(
        tts, "require_chat_read_service", lambda: SimpleNamespace(aget_display_message=read)
    )
    source = MessageSource(
        kind="message",
        session_id="s",
        message_id="m",
        revision=hashlib.sha256(b"Hello").hexdigest(),
    )
    if change is None or change == {"message_kind": "assistant_rhythm_segment"}:
        assert await tts.read_message(source) == "Hello"
    else:
        with pytest.raises(ValueError, match="^stale_message$"):
            await tts.read_message(source)
    read.assert_awaited_once_with(tts.CANONICAL_LOCAL_USER, "s", "m", final_only=True)
