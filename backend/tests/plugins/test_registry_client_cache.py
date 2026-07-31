from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from magi.plugins import registry_client as registry_client_module
from magi.plugins.contracts import PluginRegistryIndex
from magi.plugins.dependency_installation import PluginInstallWorkflowTimeoutError
from magi.plugins.registry_client import (
    DEFAULT_REGISTRY_URL,
    DEFAULT_REPO_URL,
    PluginRegistryClient,
)
from magi.plugins.registry_client import PluginRegistrySnapshot


def _registry_payload(marker: str = "default") -> dict[str, Any]:
    return {
        "registry_version": "4",
        "repo_url": "https://github.com/example/magi-plugins.git",
        "plugins": [
            {
                "plugin_id": "chrome-history",
                "name": "Chrome History",
                "version": "0.1.0",
                "description": marker,
                "package_sha256": "a" * 64,
                "path": "chrome-history",
                "platforms": ["macos"],
            }
        ],
    }


class _FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        error: Exception | None = None,
        delay: float = 0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self._error = error
        self._delay = delay
        self.headers = dict(headers or {})

    async def __aenter__(self) -> _FakeResponse:
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def aiter_bytes(self):
        yield json.dumps(self._payload).encode("utf-8")


class _FakeHttpClient:
    def __init__(
        self,
        *,
        payload: dict[str, Any] | None = None,
        error: Exception | None = None,
        delay: float = 0,
        calls: list[str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload or _registry_payload()
        self._error = error
        self._delay = delay
        self._calls = calls
        self._headers = headers

    async def __aenter__(self) -> _FakeHttpClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def stream(self, method: str, url: str) -> _FakeResponse:
        assert method == "GET"
        if self._calls is not None:
            self._calls.append(url)
        return _FakeResponse(
            self._payload,
            error=self._error,
            delay=self._delay,
            headers=self._headers,
        )


class _RawResponse:
    def __init__(
        self,
        chunks: list[bytes],
        *,
        delay: float = 0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._chunks = chunks
        self._delay = delay
        self.headers = dict(headers or {})

    async def __aenter__(self) -> "_RawResponse":
        if self._delay:
            await asyncio.sleep(self._delay)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class _RawHttpClient:
    def __init__(
        self,
        chunks: list[bytes],
        *,
        calls: list[str],
        delay: float = 0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._chunks = chunks
        self._calls = calls
        self._delay = delay
        self._headers = headers

    async def __aenter__(self) -> "_RawHttpClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def stream(self, method: str, url: str) -> _RawResponse:
        assert method == "GET"
        self._calls.append(url)
        return _RawResponse(
            self._chunks,
            delay=self._delay,
            headers=self._headers,
        )


def _snapshot(*, fingerprint: str = "a" * 64) -> PluginRegistrySnapshot:
    return PluginRegistrySnapshot(
        index=PluginRegistryIndex.model_validate(_registry_payload()),
        registry_url="https://example.test/registry.json",
        repo_url="https://github.com/example/magi-plugins.git",
        install_fingerprint=fingerprint,
        official_source=False,
    )


def test_default_registry_url_reads_the_current_main_branch() -> None:
    assert DEFAULT_REGISTRY_URL == (
        "https://raw.githubusercontent.com/asukaonly/magi-plugins/main/registry.json"
    )


@pytest.mark.asyncio
async def test_fetch_index_persists_successful_registry_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = tmp_path / "registry" / "index.json"
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=cache_path,
    )
    monkeypatch.setattr(
        client,
        "_http_client",
        lambda *, timeout=30: _FakeHttpClient(payload=_registry_payload("2")),
    )

    index = await client.fetch_index(force=True)

    assert index.plugins[0].description == "2"
    assert cache_path.exists()


@pytest.mark.asyncio
async def test_fetch_index_falls_back_to_disk_cache_after_remote_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = tmp_path / "registry" / "index.json"
    warm_client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=cache_path,
    )
    monkeypatch.setattr(
        warm_client,
        "_http_client",
        lambda *, timeout=30: _FakeHttpClient(payload=_registry_payload("cached")),
    )
    await warm_client.fetch_index(force=True)

    cold_client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=cache_path,
    )
    monkeypatch.setattr(
        cold_client,
        "_http_client",
        lambda *, timeout=30: _FakeHttpClient(error=RuntimeError("rate limited")),
    )

    index = await cold_client.fetch_index(force=True)

    assert index.plugins[0].description == "cached"


@pytest.mark.asyncio
async def test_concurrent_fetch_index_calls_share_one_remote_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=tmp_path / "registry.json",
    )
    monkeypatch.setattr(
        client,
        "_http_client",
        lambda *, timeout=30: _FakeHttpClient(
            payload=_registry_payload("coalesced"),
            delay=0.01,
            calls=calls,
        ),
    )

    first, second = await asyncio.gather(client.fetch_index(), client.fetch_index())

    assert first.plugins[0].description == "coalesced"
    assert second.plugins[0].description == "coalesced"
    assert calls == ["https://example.test/registry.json"]


@pytest.mark.asyncio
async def test_concurrent_forced_index_refreshes_share_one_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=tmp_path / "registry.json",
    )
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def controlled_download() -> bytes:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return json.dumps(_registry_payload("shared")).encode("utf-8")

    monkeypatch.setattr(client, "_download_remote_index", controlled_download)

    first = asyncio.create_task(client.fetch_index(force=True))
    await started.wait()
    second = asyncio.create_task(client.fetch_index(force=True))
    cached = asyncio.create_task(client.fetch_index())
    await asyncio.sleep(0)
    release.set()

    first_result, second_result, cached_result = await asyncio.gather(
        first,
        second,
        cached,
    )

    assert first_result is second_result
    assert second_result is cached_result
    assert first_result.plugins[0].description == "shared"
    assert calls == 1


@pytest.mark.asyncio
async def test_concurrent_forced_index_refreshes_share_one_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=tmp_path / "registry.json",
    )
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def controlled_download() -> bytes:
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
            raise RuntimeError("registry unavailable")
        return json.dumps(_registry_payload("recovered")).encode("utf-8")

    monkeypatch.setattr(client, "_download_remote_index", controlled_download)

    first = asyncio.create_task(client.fetch_index(force=True))
    await started.wait()
    second = asyncio.create_task(client.fetch_index(force=True))
    await asyncio.sleep(0)
    release.set()

    failures = await asyncio.gather(first, second, return_exceptions=True)

    assert isinstance(failures[0], RuntimeError)
    assert failures[0] is failures[1]
    assert calls == 1

    recovered = await client.fetch_index(force=True)

    assert recovered.plugins[0].description == "recovered"
    assert calls == 2


@pytest.mark.asyncio
async def test_cancelled_index_waiter_does_not_cancel_shared_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=tmp_path / "registry.json",
    )
    started = asyncio.Event()
    release = asyncio.Event()
    remote_cancelled = asyncio.Event()
    calls = 0

    async def controlled_download() -> bytes:
        nonlocal calls
        calls += 1
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            remote_cancelled.set()
            raise
        return json.dumps(_registry_payload("completed")).encode("utf-8")

    monkeypatch.setattr(client, "_download_remote_index", controlled_download)

    cancelled_waiter = asyncio.create_task(client.fetch_index(force=True))
    await started.wait()
    successful_waiter = asyncio.create_task(client.fetch_index(force=True))
    await asyncio.sleep(0)

    cancelled_waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_waiter

    assert not remote_cancelled.is_set()
    release.set()

    result = await successful_waiter

    assert result.plugins[0].description == "completed"
    assert calls == 1
    assert not remote_cancelled.is_set()


@pytest.mark.asyncio
async def test_timed_out_index_waiter_does_not_cancel_shared_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=tmp_path / "registry.json",
    )
    started = asyncio.Event()
    release = asyncio.Event()
    remote_cancelled = asyncio.Event()
    calls = 0

    async def controlled_download() -> bytes:
        nonlocal calls
        calls += 1
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            remote_cancelled.set()
            raise
        return json.dumps(_registry_payload("completed")).encode("utf-8")

    monkeypatch.setattr(client, "_download_remote_index", controlled_download)

    timed_out_waiter = asyncio.create_task(
        client.fetch_index(
            force=True,
            deadline_monotonic=asyncio.get_running_loop().time() + 0.05,
        )
    )
    await started.wait()
    successful_waiter = asyncio.create_task(client.fetch_index(force=True))
    await asyncio.sleep(0)

    with pytest.raises(PluginInstallWorkflowTimeoutError, match="workflow time limit"):
        await timed_out_waiter

    assert not remote_cancelled.is_set()
    release.set()

    result = await successful_waiter

    assert result.plugins[0].description == "completed"
    assert calls == 1
    assert not remote_cancelled.is_set()


@pytest.mark.asyncio
async def test_sequential_forced_index_refreshes_each_fetch_remote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=tmp_path / "registry.json",
    )
    calls = 0

    async def versioned_download() -> bytes:
        nonlocal calls
        calls += 1
        return json.dumps(_registry_payload(str(calls))).encode("utf-8")

    monkeypatch.setattr(client, "_download_remote_index", versioned_download)

    first = await client.fetch_index(force=True)
    second = await client.fetch_index(force=True)

    assert first.plugins[0].description == "1"
    assert second.plugins[0].description == "2"
    assert calls == 2


@pytest.mark.asyncio
async def test_registry_index_download_has_a_total_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry_client_module, "INDEX_TOTAL_TIMEOUT", 0.02)
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=tmp_path / "registry.json",
    )
    cancelled = asyncio.Event()

    async def slow_download() -> bytes:
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.set()
        return b"unreachable"

    monkeypatch.setattr(client, "_download_remote_index", slow_download)

    with pytest.raises(TimeoutError, match="total download time limit"):
        await client.fetch_index(force=True)

    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_registry_index_timeout_falls_back_to_bound_disk_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry_client_module, "INDEX_TOTAL_TIMEOUT", 0.02)
    cache_path = tmp_path / "registry.json"
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=cache_path,
    )
    client._write_disk_cache(PluginRegistryIndex.model_validate(_registry_payload("cached")))

    async def slow_download() -> bytes:
        await asyncio.sleep(30)
        return b"unreachable"

    monkeypatch.setattr(client, "_download_remote_index", slow_download)

    index = await client.fetch_index(force=True)

    assert index.plugins[0].description == "cached"


@pytest.mark.asyncio
async def test_registry_index_rejects_oversized_content_length(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry_client_module, "MAX_REGISTRY_INDEX_BYTES", 16)
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=tmp_path / "registry.json",
    )
    monkeypatch.setattr(
        client,
        "_http_client",
        lambda *, timeout=30: _FakeHttpClient(
            headers={"content-length": "17"},
        ),
    )

    with pytest.raises(ValueError, match="download limit"):
        await client.fetch_index(force=True)


@pytest.mark.asyncio
async def test_registry_index_rejects_oversized_chunked_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry_client_module, "MAX_REGISTRY_INDEX_BYTES", 16)
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=tmp_path / "registry.json",
    )
    monkeypatch.setattr(
        client,
        "_http_client",
        lambda *, timeout=30: _FakeHttpClient(payload=_registry_payload()),
    )

    with pytest.raises(ValueError, match="download limit"):
        await client.fetch_index(force=True)


@pytest.mark.asyncio
async def test_registry_index_ignores_oversized_disk_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry_client_module, "MAX_REGISTRY_INDEX_BYTES", 16)
    cache_path = tmp_path / "registry.json"
    cache_path.write_bytes(b"x" * 17)
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=cache_path,
    )
    monkeypatch.setattr(
        client,
        "_http_client",
        lambda *, timeout=30: _FakeHttpClient(error=RuntimeError("offline")),
    )

    with pytest.raises(RuntimeError, match="offline"):
        await client.fetch_index(force=True)


@pytest.mark.asyncio
async def test_registry_disk_cache_cannot_cross_registry_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = tmp_path / "registry.json"
    custom_payload = _registry_payload("custom")
    custom_payload["repo_url"] = DEFAULT_REPO_URL
    custom_client = PluginRegistryClient(
        registry_url="https://mirror.example/registry.json",
        cache_path=cache_path,
    )
    monkeypatch.setattr(
        custom_client,
        "_http_client",
        lambda *, timeout=30: _FakeHttpClient(payload=custom_payload),
    )
    await custom_client.fetch_index(force=True)

    canonical_client = PluginRegistryClient(
        registry_url=DEFAULT_REGISTRY_URL,
        cache_path=cache_path,
    )
    monkeypatch.setattr(
        canonical_client,
        "_http_client",
        lambda *, timeout=30: _FakeHttpClient(error=RuntimeError("offline")),
    )

    with pytest.raises(RuntimeError, match="offline"):
        await canonical_client.fetch_snapshot(force=True)


@pytest.mark.asyncio
async def test_registry_disk_cache_rejects_legacy_unbound_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = tmp_path / "registry.json"
    cache_path.write_text(json.dumps(_registry_payload()), encoding="utf-8")
    client = PluginRegistryClient(
        registry_url=DEFAULT_REGISTRY_URL,
        cache_path=cache_path,
    )
    monkeypatch.setattr(
        client,
        "_http_client",
        lambda *, timeout=30: _FakeHttpClient(error=RuntimeError("offline")),
    )

    with pytest.raises(RuntimeError, match="offline"):
        await client.fetch_index(force=True)


def test_registry_index_rejects_more_than_4096_plugins() -> None:
    plugin = _registry_payload()["plugins"][0]

    with pytest.raises(ValidationError):
        PluginRegistryIndex.model_validate({"plugins": [plugin] * 4097})


@pytest.mark.asyncio
async def test_concurrent_tarball_fetches_share_one_remote_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=tmp_path / "registry.json",
    )
    monkeypatch.setattr(
        client,
        "_http_client",
        lambda *, timeout=30: _RawHttpClient(
            [b"tarball"],
            calls=calls,
            delay=0.01,
        ),
    )

    results = await asyncio.gather(*(client._fetch_tarball(_snapshot()) for _ in range(20)))

    assert results == [b"tarball"] * 20
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_tarball_rejects_oversized_content_length(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry_client_module, "MAX_REGISTRY_TARBALL_BYTES", 4)
    calls: list[str] = []
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=tmp_path / "registry.json",
    )
    monkeypatch.setattr(
        client,
        "_http_client",
        lambda *, timeout=30: _RawHttpClient(
            [b"12345"],
            calls=calls,
            headers={"content-length": "5"},
        ),
    )

    with pytest.raises(ValueError, match="download limit"):
        await client._fetch_tarball(_snapshot())


@pytest.mark.asyncio
async def test_tarball_rejects_oversized_chunked_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry_client_module, "MAX_REGISTRY_TARBALL_BYTES", 4)
    calls: list[str] = []
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=tmp_path / "registry.json",
    )
    monkeypatch.setattr(
        client,
        "_http_client",
        lambda *, timeout=30: _RawHttpClient(
            [b"123", b"45"],
            calls=calls,
        ),
    )

    with pytest.raises(ValueError, match="download limit"):
        await client._fetch_tarball(_snapshot())


@pytest.mark.asyncio
async def test_tarball_cache_is_bound_to_registry_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    responses = iter([[b"first"], [b"second"]])
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=tmp_path / "registry.json",
    )
    monkeypatch.setattr(
        client,
        "_http_client",
        lambda *, timeout=30: _RawHttpClient(
            next(responses),
            calls=calls,
        ),
    )

    first = await client._fetch_tarball(_snapshot(fingerprint="a" * 64))
    second = await client._fetch_tarball(_snapshot(fingerprint="b" * 64))

    assert first == b"first"
    assert second == b"second"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_tarball_download_is_cancelled_at_workflow_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PluginRegistryClient(
        registry_url="https://example.test/registry.json",
        cache_path=tmp_path / "registry.json",
    )
    cancelled = asyncio.Event()

    async def slow_download(_url: str) -> bytes:
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.set()
        return b"unreachable"

    monkeypatch.setattr(client, "_download_tarball", slow_download)

    with pytest.raises(RuntimeError, match="workflow time limit"):
        await client._fetch_tarball(
            _snapshot(),
            deadline_monotonic=asyncio.get_running_loop().time() + 0.02,
        )

    assert cancelled.is_set()
