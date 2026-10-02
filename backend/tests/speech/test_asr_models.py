import hashlib
import httpx
import pytest
from magi.speech.asr import models
from magi.speech.asr.catalog import ModelFile


@pytest.fixture
def assets(tmp_path, monkeypatch):
    data = b"model-data"
    monkeypatch.setattr(
        models, "FILES", (ModelFile("model.onnx", len(data), hashlib.sha256(data).hexdigest()),)
    )
    return models.ASRModelStore(tmp_path), data


async def finish(store):
    assert store.task
    await store.task
    return await store.snapshot()


async def test_download_verifies_before_atomic_publish(assets, monkeypatch):
    store, data = assets
    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, content=data)), **kw
        ),
    )
    assert (await store.download()).state == "downloading"
    assert (await finish(store)).state == "ready"
    (store.directory / "model.onnx").write_bytes(b"wrong-data")
    assert not await store.ready()


async def test_bad_checksum_never_publishes(assets, monkeypatch):
    store, data = assets
    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, content=b"x" * len(data))
            ),
            **kw,
        ),
    )
    await store.download()
    assert (await finish(store)).state == "failed"
    assert not store.directory.exists()
    assert not list(store.root.glob("*.partial"))


async def test_cancel_before_download_starts_is_terminal(assets):
    store, _ = assets
    await store.download()
    assert (await store.cancel()).state == "cancelled"
    assert not store.directory.exists()
