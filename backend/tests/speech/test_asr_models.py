import asyncio
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


async def test_download_deadline_is_failure_and_cleans_staging(assets, monkeypatch):
    store, data = assets
    client = httpx.AsyncClient

    async def slow_response(request):
        await asyncio.sleep(1)
        return httpx.Response(200, content=data)

    monkeypatch.setattr(models, "DOWNLOAD_TIMEOUT", 0.01)
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: client(transport=httpx.MockTransport(slow_response), **kw),
    )
    await store.download()
    result = await finish(store)
    assert result.state == "failed"
    assert result.error == "model_download_failed"
    assert not store.directory.exists()
    assert not (store.root / f".{models.MODEL_ID}.partial").exists()


async def test_model_download_uses_the_application_proxy(assets, monkeypatch):
    store, data = assets
    real_client = httpx.AsyncClient
    selected = []

    def client(**kwargs):
        selected.append((kwargs.pop("proxy"), kwargs["trust_env"]))
        return real_client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, content=data)),
            **kwargs,
        )

    monkeypatch.setattr(httpx, "AsyncClient", client)
    await store.download("http://proxy:8080")
    assert (await finish(store)).state == "ready"
    assert selected == [("http://proxy:8080", False)]
