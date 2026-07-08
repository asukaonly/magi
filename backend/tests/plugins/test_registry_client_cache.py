from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from magi.plugins.registry_client import DEFAULT_REGISTRY_URL, PluginRegistryClient


def _registry_payload(version: str = "1") -> dict[str, Any]:
    return {
        "registry_version": version,
        "repo_url": "https://github.com/example/magi-plugins.git",
        "plugins": [
            {
                "plugin_id": "chrome-history",
                "name": "Chrome History",
                "version": "0.1.0",
                "path": "chrome-history",
                "platforms": ["macos"],
            }
        ],
    }


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHttpClient:
    def __init__(
        self,
        *,
        payload: dict[str, Any] | None = None,
        error: Exception | None = None,
        delay: float = 0,
        calls: list[str] | None = None,
    ) -> None:
        self._payload = payload or _registry_payload()
        self._error = error
        self._delay = delay
        self._calls = calls

    async def __aenter__(self) -> _FakeHttpClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get(self, url: str) -> _FakeResponse:
        if self._calls is not None:
            self._calls.append(url)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return _FakeResponse(self._payload)


def test_default_registry_url_uses_jsdelivr_cdn() -> None:
    assert DEFAULT_REGISTRY_URL == "https://cdn.jsdelivr.net/gh/asukaonly/magi-plugins@main/registry.json"


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

    assert index.registry_version == "2"
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

    assert index.registry_version == "cached"


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

    assert first.registry_version == "coalesced"
    assert second.registry_version == "coalesced"
    assert calls == ["https://example.test/registry.json"]
