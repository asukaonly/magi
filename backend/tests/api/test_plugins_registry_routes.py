"""Tests for the plugin registry HTTP routes.

Focus: the marketplace "refresh" button must be able to bypass the
registry client's 5-minute TTL cache. The route exposes a ``refresh``
query param that forwards to ``PluginRegistryClient.fetch_index(force=...)``.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from magi.api.routers import plugins_registry_routes


class _FakeIndex:
    def __init__(self) -> None:
        self.plugins: list = []
        self.registry_version = "test"


class _FakeRegistry:
    """Records the ``force`` value passed to each ``fetch_index`` call."""

    def __init__(self) -> None:
        self.force_calls: list[bool] = []

    async def fetch_index(self, *, force: bool = False) -> _FakeIndex:
        self.force_calls.append(force)
        return _FakeIndex()


class _FakeLegacy:
    def __init__(self, registry: _FakeRegistry) -> None:
        self._registry = registry
        self.logger = logging.getLogger("test_plugins_registry_routes")

    def _try_plugin_manager(self):  # noqa: ANN202 - test stub
        return None

    def _get_registry_client(self) -> _FakeRegistry:
        return self._registry

    def _version_newer(self, remote: str, local: str) -> bool:  # noqa: ARG002
        return False


def _patch_legacy(monkeypatch: pytest.MonkeyPatch, registry: _FakeRegistry) -> None:
    legacy = _FakeLegacy(registry)
    monkeypatch.setattr(
        plugins_registry_routes, "legacy_plugins_module", lambda: legacy
    )


@pytest.mark.asyncio
async def test_refresh_true_forces_index_refetch(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _FakeRegistry()
    _patch_legacy(monkeypatch, registry)

    await plugins_registry_routes.list_registry_plugins(include=None, refresh=True)

    assert registry.force_calls == [True]


@pytest.mark.asyncio
async def test_default_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _FakeRegistry()
    _patch_legacy(monkeypatch, registry)

    await plugins_registry_routes.list_registry_plugins(include=None, refresh=False)

    assert registry.force_calls == [False]


@pytest.mark.asyncio
async def test_registry_response_preserves_plugin_icon(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _FakeRegistry()
    entry = SimpleNamespace(
        kind="plugin",
        plugin_id="github-activity",
        name="GitHub Activity",
        name_i18n={"zh-CN": "GitHub 活动"},
        version="0.1.0",
        description="Local-only GitHub repository activity sync.",
        description_i18n={"zh-CN": "本机 GitHub 仓库动态同步。"},
        author="Magi Team",
        icon="brand:github",
        official=True,
        data_locality="local_only",
        contribution_types=["sensor"],
        platforms=["macos", "windows", "linux"],
        min_sdk_version="",
        homepage="",
        repository="",
        path="plugins/github_activity",
        capabilities=[],
    )

    async def fetch_index(*, force: bool = False) -> _FakeIndex:
        registry.force_calls.append(force)
        index = _FakeIndex()
        index.plugins = [entry]
        return index

    registry.fetch_index = fetch_index  # type: ignore[method-assign]
    _patch_legacy(monkeypatch, registry)

    response = await plugins_registry_routes.list_registry_plugins(include=None, refresh=False)

    assert response.plugins[0].icon == "brand:github"
