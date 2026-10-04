"""Tests for the plugin registry HTTP routes.

Focus: the marketplace "refresh" button must be able to bypass the
registry client's 5-minute TTL cache. The route exposes a ``refresh``
query param that forwards to ``PluginRegistryClient.fetch_index(force=...)``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.api.routers import plugins_registry_routes


def _registry_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from magi.api.routers.plugins import plugins_router
    from magi.api.routes import _PUBLIC_ROUTE_METHODS,_build_public_router
    app=FastAPI()
    app.include_router(_build_public_router(plugins_router,_PUBLIC_ROUTE_METHODS["plugins"]),prefix="/api/plugins")
    return TestClient(app)


class _FakeIndex:
    def __init__(self) -> None:
        self.plugins: list = []
        self.registry_version = "4"


class _FakeRegistry:
    """Records the ``force`` value passed to each ``fetch_index`` call."""

    def __init__(self) -> None:
        self.force_calls: list[bool] = []

    async def fetch_index(self, *, force: bool = False) -> _FakeIndex:
        self.force_calls.append(force)
        return _FakeIndex()

    async def fetch_snapshot(self, *, force: bool = False):
        index = await self.fetch_index(force=force)
        return SimpleNamespace(
            index=index,
            install_fingerprint="a" * 64,
            official_source=True,
        )


def _patch_registry_context(monkeypatch: pytest.MonkeyPatch, registry: _FakeRegistry) -> None:
    monkeypatch.setattr(plugins_registry_routes, "_get_registry_client", lambda: registry)
    monkeypatch.setattr(plugins_registry_routes, "_try_plugin_manager", lambda: None)
    monkeypatch.setattr(
        plugins_registry_routes,
        "_version_newer",
        lambda remote, local: False,  # noqa: ARG005
    )


def _registry_icon_entry(
    *,
    icon: str,
    icon_data: str,
    display_group=None,
):
    return SimpleNamespace(
        kind="plugin",
        plugin_id="icon-test",
        name="Icon Test",
        name_i18n={},
        version="0.1.0",
        description="Icon validation test.",
        description_i18n={},
        author="Magi Team",
        icon=icon,
        icon_data=icon_data,
        official=False,
        data_locality="local_only",
        contribution_types=[],
        platforms=["macos"],
        protocol_version=2,
        min_sdk_version="0.2.0",
        execution_mode="trusted_process",
        settings_fields=[],
        activation_flow=None,
        settings_actions=[],
        settings_resources=[],
        settings_ui_blocks=[],
        homepage="",
        repository="",
        path="plugins/icon-test",
        capabilities=[],
        display_group=display_group,
    )


@pytest.mark.parametrize(
    "query,force", [("", False), ("?refresh=false", False), ("?refresh=true", True)]
)
def test_public_registry_query_controls_refresh(monkeypatch, query, force):
    registry = _FakeRegistry()
    _patch_registry_context(monkeypatch, registry)
    with _registry_client() as client:
        response = client.get("/api/plugins/registry" + query)
    assert response.status_code == 200
    assert response.json() == {
        "plugins": [],
        "registry_version": "4",
        "install_fingerprint": "a" * 64,
    }
    assert registry.force_calls == [force]


@pytest.mark.parametrize(
    "icon,icon_data,expected",
    [
        (
            "asset:assets/icon.svg",
            "data:image/svg+xml;base64,PHN2Zy8+",
            "data:image/svg+xml;base64,PHN2Zy8+",
        ),
        ("lucide:globe", "data:image/png;base64,PHN2Zy8+", "lucide:globe"),
    ],
    ids=["valid-inline", "mime-mismatch-fallback"],
)
def test_public_registry_preserves_only_safe_plugin_icons(monkeypatch, icon, icon_data, expected):
    registry = _FakeRegistry()
    entry = _registry_icon_entry(icon=icon, icon_data=icon_data)

    async def fetch_index(*, force=False):
        index = _FakeIndex()
        index.plugins = [entry]
        return index

    registry.fetch_index = fetch_index
    _patch_registry_context(monkeypatch, registry)
    with _registry_client() as client:
        response = client.get("/api/plugins/registry")
    assert response.status_code == 200
    assert [item["plugin_id"] for item in response.json()["plugins"]] == ["icon-test"]
    assert response.json()["plugins"][0]["icon"] == expected


@pytest.mark.parametrize("as_model", [False, True])
@pytest.mark.parametrize(
    "icon,expected",
    [
        ("data:image/svg+xml;base64,PHN2Zy8+", "data:image/svg+xml;base64,PHN2Zy8+"),
        ("data:image/svg+xml;base64,PHN2Zz48c2NyaXB0Lz48L3N2Zz4=", ""),
    ],
)
def test_registry_validates_group_artwork(monkeypatch, as_model, icon, expected) -> None:
    from magi_plugin_sdk import PluginDisplayGroupSpec

    group = {
        "id": "browser_history",
        "name": "Browser History",
        "name_i18n": {"zh-CN": "浏览器历史"},
        "description": "Manage browser history sources.",
        "description_i18n": {"zh-CN": "统一管理浏览器历史入口。"},
        "icon": icon,
        "order": 10,
        "member_label": "Brave",
        "member_label_i18n": {"zh-CN": "Brave"},
        "member_order": 50,
    }
    entry = _registry_icon_entry(
        icon="lucide:package",
        icon_data="",
        display_group=PluginDisplayGroupSpec(**group) if as_model else group,
    )
    registry = _FakeRegistry()

    async def fetch_index(*, force: bool = False) -> _FakeIndex:
        index = _FakeIndex()
        index.plugins = [entry]
        return index

    registry.fetch_index = fetch_index
    _patch_registry_context(monkeypatch, registry)
    with _registry_client() as client:
        response = client.get("/api/plugins/registry")
    assert response.status_code == 200
    actual = response.json()["plugins"][0]["display_group"]
    assert {key: actual[key] for key in group} == {**group, "icon": expected}


@pytest.mark.asyncio
async def test_registry_response_drops_invalid_icon_and_display_group_icon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _FakeRegistry()
    entry = _registry_icon_entry(
        icon="https://attacker.example/icon.svg",
        icon_data="data:image/svg+xml;base64," "PHN2Zz48c2NyaXB0PmFsZXJ0KDEpPC9zY3JpcHQ+PC9zdmc+",
        display_group={
            "id": "unsafe-group",
            "name": "Unsafe Group",
            "icon": "lucide:../../escape",
        },
    )

    async def fetch_index(*, force: bool = False) -> _FakeIndex:
        registry.force_calls.append(force)
        index = _FakeIndex()
        index.plugins = [entry]
        return index

    registry.fetch_index = fetch_index  # type: ignore[method-assign]
    _patch_registry_context(monkeypatch, registry)

    response = await plugins_registry_routes.list_registry_plugins(
        include=None,
        refresh=False,
    )

    assert response.plugins[0].icon == ""
    assert response.plugins[0].display_group is not None
    assert response.plugins[0].display_group.icon == ""


@pytest.mark.asyncio
async def test_custom_registry_entry_remains_available_for_manual_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _FakeRegistry()
    entry = _registry_icon_entry(
        icon="lucide:globe",
        icon_data="",
    )
    entry.official = True

    async def fetch_snapshot(*, force: bool = False):
        registry.force_calls.append(force)
        index = _FakeIndex()
        index.plugins = [entry]
        return SimpleNamespace(
            index=index,
            install_fingerprint="b" * 64,
            official_source=False,
        )

    registry.fetch_snapshot = fetch_snapshot  # type: ignore[method-assign]
    _patch_registry_context(monkeypatch, registry)

    response = await plugins_registry_routes.list_registry_plugins(
        include=None,
        refresh=False,
    )

    assert [item.plugin_id for item in response.plugins] == ["icon-test"]
    assert response.plugins[0].official is False
    assert response.plugins[0].icon == "lucide:globe"
