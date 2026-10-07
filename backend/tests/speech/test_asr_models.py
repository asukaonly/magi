import asyncio
import hashlib
import httpx
import pytest
from magi.speech.asr import models
from magi.speech.asr.catalog import ModelFile, ModelSpec


@pytest.fixture
def assets(tmp_path, monkeypatch):
    data = b"model-data"
    monkeypatch.setattr(
        models,
        "CATALOG",
        {
            identity: ModelSpec(
                identity,
                identity,
                "model.onnx",
                (ModelFile("model.onnx", len(data), hashlib.sha256(data).hexdigest()),),
            )
            for identity in ("first", "second")
        },
    )
    return models.ASRModelStore(tmp_path).get("first"), data


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
    assert not list(store.root.rglob("*.magi-part"))


async def test_cancel_before_download_starts_is_terminal(assets):
    store, _ = assets
    await store.download()
    assert (await store.cancel()).state == "cancelled"
    assert not store.directory.exists()


async def test_download_deadline_is_failure_and_retains_resumable_staging(assets, monkeypatch):
    store, data = assets
    client = httpx.AsyncClient

    async def slow_response(request):
        await asyncio.sleep(1)
        return httpx.Response(200, content=data)

    monkeypatch.setattr(models, "DOWNLOAD_TIMEOUT", 0.01)
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: client(transport=httpx.MockTransport(slow_response), **kw),
    )
    await store.download()
    result = await finish(store)
    assert result.state == "failed"
    assert result.error == "model_download_failed"
    assert not store.directory.exists()
    assert (store.root / f".{store.model.id}.partial" / ".download.json").exists()


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


async def test_installations_do_not_share_download_or_delete_state(assets, monkeypatch):
    installation, data = assets
    store = models.ASRModelStore(installation.root)
    first, second = store.get("first"), store.get("second")
    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, content=data)), **kw
        ),
    )
    await first.download()
    await finish(first)
    await second.download()
    await finish(second)
    await first.delete()
    states = {item.id: item.state for item in await store.snapshot()}
    assert states == {"first": "missing", "second": "ready"}
    assert await store.ready("second")
    with pytest.raises(models.ASRError, match="unknown_model"):
        store.get("../second")


async def test_cancelling_one_download_keeps_other_installation(assets, monkeypatch):
    installation, data = assets
    store = models.ASRModelStore(installation.root)
    first, second = store.get("first"), store.get("second")
    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, content=data)), **kw
        ),
    )
    await second.download()
    await finish(second)
    await first.download()
    await first.cancel()
    assert (await first.snapshot()).state == "cancelled"
    assert await second.ready()
    await store.cancel_all()


async def test_catalog_downloads_use_each_models_pinned_source(tmp_path, monkeypatch):
    from dataclasses import replace
    from magi.speech.asr.catalog import CATALOG

    data = b"test-weights"
    requests = []
    specs = {
        key: replace(spec, files=(ModelFile("model.onnx", len(data), hashlib.sha256(data).hexdigest()),))
        for key, spec in CATALOG.items()
    }
    monkeypatch.setattr(models, "CATALOG", specs)
    client = httpx.AsyncClient

    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200, content=data)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(respond), **kw))
    store = models.ASRModelStore(tmp_path)
    for key, spec in specs.items():
        installation = store.get(key)
        await installation.download()
        result = await finish(installation)
        assert result.state == "ready"
        assert result.family == spec.family
        assert result.source_url == spec.source_url
        assert result.license_url == spec.license_url
        assert requests[-1] == f"https://huggingface.co/{spec.repo}/resolve/{spec.revision}/model.onnx"
    assert len({url.split("/resolve/")[0] for url in requests}) == 4


async def test_nested_tokenizer_files_are_verified_and_published_together(assets, monkeypatch, tmp_path):
    from dataclasses import replace

    original, data = assets
    tokenizer = b'{"tokens": ["hello"]}'
    spec = replace(original.model, files=original.model.files + (
        ModelFile("tokenizer/vocab.json", len(tokenizer), hashlib.sha256(tokenizer).hexdigest()),
    ))
    monkeypatch.setattr(models, "CATALOG", {spec.id: spec})
    store = models.ASRModelStore(original.root).get(spec.id)
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, content=tokenizer if request.url.path.endswith("vocab.json") else data,
        )), **kw,
    ))
    await store.download()
    assert (await finish(store)).state == "ready"
    assert (store.directory / "tokenizer/vocab.json").read_bytes() == tokenizer
    assert not (store.root / f".{spec.id}.partial").exists()
    # An unchanged leaf must not bypass verification of a replaced parent.
    moved = tmp_path / "outside-tokenizer"
    (store.directory / "tokenizer").rename(moved)
    (store.directory / "tokenizer").symlink_to(moved, target_is_directory=True)
    assert not await store.ready()


async def test_catalog_shows_three_choices_and_preserves_explicit_selections(tmp_path):
    store = models.ASRModelStore(tmp_path)
    entries = await store.snapshot()
    assert [item.id for item in entries] == [
        "sensevoice-zh-en-ja-ko-yue", "qwen3-asr-0.6b-int8", "whisper-large-v3-turbo-int8",
    ]
    assert [item.id for item in entries if item.recommended] == ["sensevoice-zh-en-ja-ko-yue"]
    entries = await store.snapshot("paraformer-zh-en-fp32")
    assert entries[-1].id == "paraformer-zh-en-fp32"
    assert len(entries) == 4


async def test_downloaded_unlisted_models_remain_manageable(tmp_path, monkeypatch):
    store = models.ASRModelStore(tmp_path)

    async def ready():
        return True

    monkeypatch.setattr(store.get("paraformer-zh-en-int8"), "ready", ready)
    entries = await store.snapshot()
    assert entries[-1].id == "paraformer-zh-en-int8"
    assert entries[-1].state == "ready"
