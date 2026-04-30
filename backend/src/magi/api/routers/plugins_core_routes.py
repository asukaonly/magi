"""Installed plugin lifecycle and settings routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ...plugins.contracts import PluginSettingsResourcePayload
from .plugins_common import legacy_plugins_module
from .plugins_schemas import (
    PluginPackageResponse,
    PluginSettingsResourceResponse,
    PluginSettingsUpdateRequest,
    PluginsListResponse,
)

plugins_core_router = APIRouter()


@plugins_core_router.get("", response_model=PluginsListResponse)
async def list_plugins():
    legacy = legacy_plugins_module()
    try:
        manager = legacy.resolve_plugin_manager()
    except RuntimeError:
        return PluginsListResponse(plugins=[], total=0)
    packages = manager.list_packages()
    return PluginsListResponse(
        plugins=[legacy._serialize_package(item) for item in packages],
        total=len(packages),
    )


@plugins_core_router.post("/rescan", response_model=PluginsListResponse)
async def rescan_plugins():
    legacy = legacy_plugins_module()
    manager = legacy.resolve_plugin_manager()
    packages = manager.rescan_runtime()
    return PluginsListResponse(
        plugins=[legacy._serialize_package(item) for item in packages],
        total=len(packages),
    )


@plugins_core_router.post("/{plugin_id}/enable", response_model=PluginPackageResponse)
async def enable_plugin(plugin_id: str):
    legacy = legacy_plugins_module()
    manager, _ = legacy._require_package(plugin_id)
    state = manager.enable_plugin(plugin_id)
    return legacy._serialize_package(state)


@plugins_core_router.post("/{plugin_id}/disable", response_model=PluginPackageResponse)
async def disable_plugin(plugin_id: str):
    legacy = legacy_plugins_module()
    manager, _ = legacy._require_package(plugin_id)
    state = manager.disable_plugin(plugin_id)
    return legacy._serialize_package(state)


@plugins_core_router.post("/{plugin_id}/reload", response_model=PluginPackageResponse)
async def reload_plugin(plugin_id: str):
    legacy = legacy_plugins_module()
    manager, _ = legacy._require_package(plugin_id)
    state = manager.reload_plugin(plugin_id)
    return legacy._serialize_package(state)


@plugins_core_router.get("/{plugin_id}/settings", response_model=PluginPackageResponse)
async def get_plugin_settings(plugin_id: str):
    legacy = legacy_plugins_module()
    _, package = legacy._require_package(plugin_id)
    return legacy._serialize_package(package)


@plugins_core_router.put("/{plugin_id}/settings", response_model=PluginPackageResponse)
async def update_plugin_settings(plugin_id: str, request: PluginSettingsUpdateRequest):
    legacy = legacy_plugins_module()
    manager, _ = legacy._require_package(plugin_id)
    state = manager.update_plugin_settings(plugin_id, request.updates)
    return legacy._serialize_package(state)


@plugins_core_router.get("/{plugin_id}/settings/resources/{resource_name}", response_model=PluginSettingsResourceResponse)
async def read_plugin_settings_resource(plugin_id: str, resource_name: str):
    legacy = legacy_plugins_module()
    manager, _ = legacy._require_package(plugin_id)
    try:
        payload = manager.read_plugin_settings_resource(plugin_id, resource_name)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin settings resource not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if isinstance(payload, PluginSettingsResourcePayload):
        return PluginSettingsResourceResponse(**payload.model_dump())
    return PluginSettingsResourceResponse(**payload)


__all__ = [
    "disable_plugin",
    "enable_plugin",
    "get_plugin_settings",
    "list_plugins",
    "plugins_core_router",
    "read_plugin_settings_resource",
    "reload_plugin",
    "rescan_plugins",
    "update_plugin_settings",
]