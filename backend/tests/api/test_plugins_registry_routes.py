"""Tests for the plugin registry HTTP routes.

Focus: the marketplace "refresh" button must be able to bypass the
registry client's 5-minute TTL cache. The route exposes a ``refresh``
query param that forwards to ``PluginRegistryClient.fetch_index(force=...)``.
"""
from __future__ import annotations

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


def _patch_registry_context(monkeypatch: pytest.MonkeyPatch, registry: _FakeRegistry) -> None:
    monkeypatch.setattr(plugins_registry_routes, "_get_registry_client", lambda: registry)
    monkeypatch.setattr(plugins_registry_routes, "_try_plugin_manager", lambda: None)
    monkeypatch.setattr(
        plugins_registry_routes,
        "_version_newer",
        lambda remote, local: False,  # noqa: ARG005
    )


@pytest.mark.asyncio
async def test_refresh_true_forces_index_refetch(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _FakeRegistry()
    _patch_registry_context(monkeypatch, registry)

    await plugins_registry_routes.list_registry_plugins(include=None, refresh=True)

    assert registry.force_calls == [True]


@pytest.mark.asyncio
async def test_default_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _FakeRegistry()
    _patch_registry_context(monkeypatch, registry)

    await plugins_registry_routes.list_registry_plugins(include=None, refresh=False)

    assert registry.force_calls == [False]


@pytest.mark.asyncio
async def test_registry_response_preserves_plugin_icon(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _FakeRegistry()
    icon_data = "data:image/svg+xml;base64,PHN2Zy8+"
    entry = SimpleNamespace(
        kind="plugin",
        plugin_id="github-activity",
        name="GitHub Activity",
        name_i18n={"zh-CN": "GitHub 活动"},
        version="0.1.0",
        description="Local-only GitHub repository activity sync.",
        description_i18n={"zh-CN": "本机 GitHub 仓库动态同步。"},
        author="Magi Team",
        icon="asset:assets/icon.svg",
        icon_data=icon_data,
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
    _patch_registry_context(monkeypatch, registry)

    response = await plugins_registry_routes.list_registry_plugins(include=None, refresh=False)

    assert response.plugins[0].icon == icon_data


@pytest.mark.asyncio
async def test_registry_response_preserves_plugin_display_group(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _FakeRegistry()
    entry = SimpleNamespace(
        kind="plugin",
        plugin_id="brave-history",
        name="Brave History",
        name_i18n={"zh-CN": "Brave 浏览器历史"},
        version="0.1.0",
        description="Read local Brave browsing history.",
        description_i18n={"zh-CN": "读取本地 Brave 浏览记录。"},
        author="Magi Team",
        icon="brand:brave",
        official=True,
        data_locality="local_only",
        contribution_types=["sensor"],
        platforms=["macos", "windows"],
        min_sdk_version="",
        homepage="",
        repository="",
        path="plugins/brave-history",
        capabilities=[],
        display_group={
            "id": "browser_history",
            "name": "Browser History",
            "name_i18n": {"zh-CN": "浏览器历史"},
            "description": "Manage browser history sources.",
            "description_i18n": {"zh-CN": "统一管理浏览器历史入口。"},
            "icon": "lucide:globe",
            "order": 10,
            "member_label": "Brave",
            "member_label_i18n": {"zh-CN": "Brave"},
            "member_order": 50,
        },
    )

    async def fetch_index(*, force: bool = False) -> _FakeIndex:
        registry.force_calls.append(force)
        index = _FakeIndex()
        index.plugins = [entry]
        return index

    registry.fetch_index = fetch_index  # type: ignore[method-assign]
    _patch_registry_context(monkeypatch, registry)

    response = await plugins_registry_routes.list_registry_plugins(include=None, refresh=False)

    assert response.plugins[0].display_group is not None
    assert response.plugins[0].display_group.id == "browser_history"
    assert response.plugins[0].display_group.member_label == "Brave"
