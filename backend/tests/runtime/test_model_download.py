"""Exercise interrupted transfers, publication integrity and bounded concurrency."""

import asyncio
import hashlib
from dataclasses import asdict
import json

import httpx
import pytest

from magi.utils import model_download as downloads
from magi.utils.hub_model_download import download_hub_model


def asset(name="model.onnx", data=b"abcdefgh"):
    return downloads.DownloadFile(name, f"https://models.test/{name}", len(data), hashlib.sha256(data).hexdigest())


def client(monkeypatch, handler):
    factory = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: factory(transport=httpx.MockTransport(handler), **kwargs))


class InterruptedStream(httpx.AsyncByteStream):
    def __init__(self, gate=None):
        self.gate = gate
        self.closed = False

    async def __aiter__(self):
        yield b"abcd"
        if self.gate:
            await self.gate.wait()
        raise httpx.ReadError("Connection interrupted")

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_transport_retry_resumes_at_last_received_byte(tmp_path, monkeypatch):
    requests = []
    interrupted = InterruptedStream()
    def respond(request):
        requests.append(request.headers.get("range"))
        if len(requests) == 1:
            return httpx.Response(200, stream=interrupted)
        return httpx.Response(206, content=b"efgh", headers={"content-range": "bytes 4-7/8"})
    client(monkeypatch, respond)
    tracker = downloads.DownloadTracker()
    await downloads.download_files([asset()], tmp_path / "stage", tracker)
    assert requests == [None, "bytes=4-"]
    assert interrupted.closed
    assert (tmp_path / "stage/model.onnx").read_bytes() == b"abcdefgh"
    assert tracker.snapshot().downloaded_bytes == 8
    assert tracker.snapshot().files_completed == 1


@pytest.mark.asyncio
async def test_cancel_stops_writers_and_new_tracker_resumes(tmp_path, monkeypatch):
    stream = InterruptedStream(asyncio.Event())
    requests = []
    def respond(request):
        requests.append(request.headers.get("range"))
        return httpx.Response(200, stream=stream) if len(requests) == 1 else httpx.Response(206, content=b"efgh", headers={"content-range": "bytes 4-7/8"})
    client(monkeypatch, respond)
    tracker = downloads.DownloadTracker()
    staging = tmp_path / "stage"
    task = asyncio.create_task(downloads.download_files([asset()], staging, tracker))
    async with asyncio.timeout(2):
        while tracker.snapshot().downloaded_bytes != 4:
            await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed
    assert tracker.snapshot().phase == "cancelled"
    assert (staging / "model.onnx.magi-part").read_bytes() == b"abcd"
    assert not (staging / "model.onnx").exists()
    await downloads.download_files([asset()], staging, downloads.DownloadTracker())
    assert requests == [None, "bytes=4-"]
    assert (staging / "model.onnx").read_bytes() == b"abcdefgh"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["ignored", "wrong-range", "checksum", "revision"])
async def test_resume_never_appends_an_unrelated_response(tmp_path, monkeypatch, mode):
    item = asset()
    staging = tmp_path / "stage"
    staging.mkdir()
    manifest = [asdict(item)]
    if mode == "revision":
        manifest[0]["url"] += "?old-revision"
    (staging / ".download.json").write_text(json.dumps(manifest))
    (staging / "model.onnx.magi-part").write_bytes(b"abcd")
    requests = []
    def respond(request):
        requests.append(request.headers.get("range"))
        if mode in {"ignored", "revision"}:
            return httpx.Response(200, content=b"abcdefgh")
        return httpx.Response(206, content=b"XXXX", headers={"content-range": "bytes 4-7/8" if mode == "checksum" else "bytes 0-3/8"})
    client(monkeypatch, respond)
    if mode in {"checksum", "wrong-range"}:
        with pytest.raises(ValueError):
            await downloads.download_files([item], staging, downloads.DownloadTracker())
        assert not (staging / item.path).exists()
    else:
        await downloads.download_files([item], staging, downloads.DownloadTracker())
        assert (staging / item.path).read_bytes() == b"abcdefgh"
    assert requests == [None if mode == "revision" else "bytes=4-"]


@pytest.mark.asyncio
async def test_four_requests_run_concurrently_and_cancel_together(tmp_path, monkeypatch):
    streams = []
    def respond(request):
        stream = InterruptedStream(asyncio.Event())
        streams.append(stream)
        return httpx.Response(200, stream=stream)
    client(monkeypatch, respond)
    task = asyncio.create_task(downloads.download_files([asset(str(i)) for i in range(9)], tmp_path / "stage", downloads.DownloadTracker()))
    async with asyncio.timeout(2):
        while len(streams) < 4:
            await asyncio.sleep(0.001)
    await asyncio.sleep(0.02)
    assert len(streams) == 4
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(stream.closed for stream in streams)
    assert len(streams) == 4


@pytest.mark.asyncio
async def test_completed_files_are_verified_and_reused(tmp_path, monkeypatch):
    requests = []
    def respond(request):
        requests.append(request.url.path)
        return httpx.Response(200, content=b"abcdefgh")
    client(monkeypatch, respond)
    staging = tmp_path / "stage"
    await downloads.download_files([asset()], staging, downloads.DownloadTracker())
    await downloads.download_files([asset()], staging, downloads.DownloadTracker())
    assert len(requests) == 1
    (staging / "model.onnx").write_bytes(b"tampered")
    await downloads.download_files([asset()], staging, downloads.DownloadTracker())
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_nested_symlinks_cannot_redirect_a_transfer(tmp_path, monkeypatch):
    item = asset("tokenizer/vocab.json")
    staging = tmp_path / "stage"
    staging.mkdir()
    (staging / ".download.json").write_text(json.dumps([asdict(item)]))
    outside = tmp_path / "outside"
    outside.mkdir()
    (staging / "tokenizer").symlink_to(outside, target_is_directory=True)
    client(monkeypatch, lambda _: pytest.fail("Unsafe paths must not reach the network"))
    with pytest.raises(ValueError, match="unsafe_model_path"):
        await downloads.download_files([item], staging, downloads.DownloadTracker())
    assert not list(outside.iterdir())


def test_rate_ignores_cached_bytes_and_expires_when_stalled(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(downloads.time, "monotonic", lambda: clock[0])
    tracker = downloads.DownloadTracker()
    tracker.total = 10000
    tracker.counts = {"model": 5000}
    tracker.phases = {"model": "downloading"}
    for i in range(1, 9):
        clock[0] = i / 4
        tracker.received("model", 100)
    status = tracker.snapshot()
    assert status.speed_bps == 400
    assert status.eta_seconds == 10.5
    clock[0] += 4
    assert tracker.snapshot().speed_bps == 0
    assert tracker.snapshot().eta_seconds is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_after_publish", [False, True])
async def test_hub_download_pins_commit_and_preserves_other_variants(tmp_path, monkeypatch, cancel_after_publish):
    data = {"onnx/model.onnx": b"weights", "tokenizer.json": b"{}"}
    revision = "a" * 40
    requests = []
    def respond(request):
        requests.append(request.url.path)
        if request.url.path.startswith("/api/"):
            return httpx.Response(200, json={"sha": revision, "siblings": [
                {"rfilename": name, "size": len(payload), "blobId": hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest(),
                 **({"lfs": {"sha256": hashlib.sha256(payload).hexdigest()}} if name.endswith(".onnx") else {})}
                for name, payload in data.items()
            ]})
        assert f"/resolve/{revision}/" in request.url.path
        return httpx.Response(200, content=data[request.url.path.split(f"/{revision}/")[1]])
    client(monkeypatch, respond)
    if cancel_after_publish:
        async def cleanup(directory):
            asyncio.current_task().cancel()
            await downloads.remove_directory(directory)
        monkeypatch.setattr("magi.utils.hub_model_download.remove_directory", cleanup)
    directory = tmp_path / "model"
    directory.mkdir()
    (directory / "other.onnx").write_bytes(b"existing")
    tracker = downloads.DownloadTracker()
    await download_hub_model("owner/model", ["onnx/model.onnx", "tokenizer.json"], directory, tracker)
    assert (directory / "other.onnx").read_bytes() == b"existing"
    assert (directory / "onnx/model.onnx").read_bytes() == b"weights"
    assert tracker.snapshot().phase == "completed"
    assert tracker.snapshot().downloaded_bytes == 9
    assert len(requests) == 3
    assert not (tmp_path / ".model.partial").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["embedding", "reranker"])
async def test_public_model_routes_report_bytes_and_cancel_before_acknowledging(tmp_path, monkeypatch, domain):
    from importlib import import_module
    from types import SimpleNamespace
    from fastapi import FastAPI
    from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router

    module = import_module(f"magi.api.routers.local_{domain}")
    identity = "fixture"
    meta = SimpleNamespace(id=identity, variants={})
    registry = SimpleNamespace(get=lambda name: meta if name == identity else None)
    monkeypatch.setattr(module, "get_local_embedding_registry" if domain == "embedding" else "get_cross_encoder_registry", lambda: registry)
    monkeypatch.setattr(module, "RuntimePaths", lambda: SimpleNamespace(**{f"managed_{domain}_model_dir": lambda _: str(tmp_path / identity)}))
    monkeypatch.setattr(module, "_download_progress", {})
    monkeypatch.setattr(module, "_download_errors", {})
    monkeypatch.setattr(module, "_download_tasks", {})
    monkeypatch.setattr(module, "_download_locks", {})
    stopped = asyncio.Event()
    async def worker(meta, directory, *, variant_override):
        tracker = module._download_progress[identity]
        tracker.total = 8
        tracker.counts = {"model": 4}
        tracker.phase = "downloading"
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    monkeypatch.setattr(module, "_download_model_task", worker)
    app = FastAPI()
    app.include_router(_build_public_router(getattr(module, f"local_{domain}_router"), _PUBLIC_ROUTE_METHODS[f"local_{domain}"]))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as api:
        assert (await api.post(f"/models/{identity}/download")).status_code == 200
        await asyncio.sleep(0)
        status = (await api.get(f"/models/{identity}/status")).json()
        assert status["download"]["downloaded_bytes"] == 4
        assert status["download"]["total_bytes"] == 8
        cancelled = await api.post(f"/models/{identity}/download/cancel")
        assert cancelled.status_code == 200
        assert stopped.is_set()
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["download"]["downloaded_bytes"] == 4


@pytest.mark.asyncio
async def test_cancellation_drains_filesystem_cleanup(tmp_path, monkeypatch):
    import threading
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    def remove(_):
        entered.set()
        release.wait(timeout=5)
        finished.set()
    monkeypatch.setattr(downloads.shutil, "rmtree", remove)
    job = asyncio.create_task(downloads.remove_directory(tmp_path))
    assert await asyncio.to_thread(entered.wait, 5)
    job.cancel()
    await asyncio.sleep(0)
    assert not job.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await job
    assert finished.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["embedding", "reranker"])
async def test_restart_waits_for_delete_cleanup(tmp_path, monkeypatch, domain):
    from importlib import import_module
    from types import SimpleNamespace
    module = import_module(f"magi.api.routers.local_{domain}")
    directory = tmp_path / "fixture"
    directory.mkdir()
    meta = SimpleNamespace(id="fixture", variants={})
    monkeypatch.setattr(module, "get_local_embedding_registry" if domain == "embedding" else "get_cross_encoder_registry", lambda: SimpleNamespace(get=lambda _: meta))
    monkeypatch.setattr(module, "RuntimePaths", lambda: SimpleNamespace(**{f"managed_{domain}_model_dir": lambda _: str(directory)}))
    for name in ("_download_progress", "_download_tasks", "_download_errors", "_download_locks"):
        monkeypatch.setattr(module, name, {})
    entered, release, started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def remove(_):
        entered.set()
        await release.wait()
        directory.rmdir()
    async def worker(*args, **kwargs):
        started.set()
    monkeypatch.setattr(module, "remove_directory", remove)
    monkeypatch.setattr(module, "_download_model_task", worker)
    deletion = asyncio.create_task(module.delete_model("fixture"))
    await entered.wait()
    restart = asyncio.create_task(module.download_model("fixture"))
    await asyncio.sleep(0)
    assert not restart.done() and not started.is_set()
    release.set()
    assert await deletion == {"status": "deleted"}
    assert (await restart).status == "downloading"
    await module._download_tasks["fixture"]
    assert started.is_set()
