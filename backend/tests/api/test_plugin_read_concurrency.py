"""Plugin metadata reads must remain asynchronous during worker startup."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
import httpx
import pytest

from magi.api.routers.plugins import plugins_router
from magi.api.routers.availability_routes import availability_router
from magi.api.routers.delivery import delivery_router
from magi.api.routers.sources import sources_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.plugins.manager import PluginManager


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "status"), [
    ("/api/plugins", 200),
    ("/api/plugins/updates", 200),
    ("/api/plugins/registry", 200),
    ("/api/plugins/connections/setup/settings/resources/qr", 404),
    ("/api/availability", 200),
    ("/api/sources/status", 200),
    ("/api/delivery/collector/setup", 409),
])
async def test_plugin_reads_keep_public_routes_responsive_during_startup(
    monkeypatch, tmp_path, path, status,
):
    lock_held = threading.Event()
    read_started = threading.Event()
    release_startup = threading.Event()
    startup_finished = threading.Event()
    manager = object.__new__(PluginManager)
    manager._lifecycle_write_lock = threading.RLock()
    manager._package_states = {}
    manager.connection_store = SimpleNamespace(
        get=lambda _: SimpleNamespace(plugin_id="sample", enabled=True)
    )

    def list_packages():
        read_started.set()
        return PluginManager.list_packages(manager)

    def get_package(plugin_id):
        read_started.set()
        return PluginManager.get_package(manager, plugin_id)

    manager.list_packages = list_packages
    manager.get_package = get_package
    monkeypatch.setattr("magi.api.routers.plugins_common.resolve_plugin_manager", lambda: manager)
    monkeypatch.setattr(
        "magi.api.routers.plugins_core_routes.get_config",
        lambda: SimpleNamespace(plugins=SimpleNamespace(packages={})),
    )
    entry = SimpleNamespace(
        kind="plugin", plugin_id="sample", name="Sample", name_i18n={}, version="1.0.0",
        description="Sample source", description_i18n={}, author="Magi", icon="", icon_data="",
        official=False, data_locality="local_only", contribution_types=[], platforms=["macos"],
        protocol_version=2, min_sdk_version="0.2.0", execution_mode="trusted_process",
        settings_fields=[], activation_flow=None, settings_actions=[], settings_resources=[],
        settings_ui_blocks=[], homepage="", repository="", path="sample", capabilities=[],
        display_group=None,
    )
    registry = SimpleNamespace(fetch_snapshot=AsyncMock(return_value=SimpleNamespace(
        index=SimpleNamespace(plugins=[entry], registry_version="4"),
        install_fingerprint="a" * 64, official_source=False,
    )))
    monkeypatch.setattr("magi.api.routers.plugins_registry_routes._get_registry_client", lambda: registry)

    source_registry = SimpleNamespace(
        list_contributions=lambda: [],
        resolve_source=lambda *_args, **_kwargs: (
            "sample", None, None, SimpleNamespace(metadata={"remote_collection": "source.change.v1"})
        ),
    )
    monkeypatch.setattr("magi.api.routers.sources.resolve_plugin_manager", lambda: manager)
    monkeypatch.setattr("magi.api.routers.sources.resolve_source_registry", lambda: source_registry)
    monkeypatch.setattr("magi.api.routers.sources.get_config", lambda: None)
    monkeypatch.setattr("magi.api.routers.sources.get_runtime_paths", lambda: SimpleNamespace(base_dir=tmp_path))
    monkeypatch.setattr(
        "magi.api.routers.source_status_projection._build_schedule_repository",
        lambda _: SimpleNamespace(initialize=AsyncMock()),
    )
    monkeypatch.setattr("magi.api.routers.delivery.get_container", lambda: SimpleNamespace(
        plugin_manager=lambda: manager, source_registry=lambda: source_registry,
    ))

    def startup():
        with manager._lifecycle_write_lock:
            lock_held.set()
            release_startup.wait(2)
        startup_finished.set()

    app = FastAPI()
    app.include_router(
        _build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"]),
        prefix="/api/plugins",
    )

    app.include_router(
        _build_public_router(availability_router, _PUBLIC_ROUTE_METHODS["availability"]), prefix="/api",
    )
    app.include_router(
        _build_public_router(sources_router, _PUBLIC_ROUTE_METHODS["sources"]), prefix="/api/sources",
    )
    app.include_router(
        _build_public_router(delivery_router, _PUBLIC_ROUTE_METHODS["delivery"]), prefix="/api/delivery",
    )

    @app.get("/heartbeat")
    async def heartbeat():
        return {"ok": True}

    owner = asyncio.get_running_loop().run_in_executor(None, startup)
    request = None
    try:
        assert await asyncio.to_thread(lock_held.wait, 1)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            request = asyncio.create_task(client.get(path, headers={"x-magi-collector-source": "sample"}))
            assert await asyncio.to_thread(read_started.wait, 1)
            assert (await client.get("/heartbeat")).json() == {"ok": True}
            assert not startup_finished.is_set()
            assert not request.done()
            release_startup.set()
            response = await request
            assert response.status_code == status
    finally:
        release_startup.set()
        await owner
        if request is not None:
            await asyncio.gather(request, return_exceptions=True)
