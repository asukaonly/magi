"""Plugin management API router."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ...plugins import get_plugin_manager, reload_plugin_manager
from ...plugins.contracts import PluginContribution, PluginManifest, PluginPackageState

plugins_router = APIRouter()


class PluginSettingsUpdateRequest(BaseModel):
    updates: dict[str, Any] = Field(default_factory=dict)


class PluginManifestResponse(BaseModel):
    plugin_id: str
    name: str
    version: str
    description: str
    author: str
    official: bool
    contribution_types: list[str]
    source: str
    plugin_dir: str
    manifest_path: str


class PluginContributionResponse(BaseModel):
    plugin_id: str
    contribution_id: str
    contribution_type: str
    display_name: str
    description: str
    surface: str
    fields: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginPackageResponse(BaseModel):
    manifest: PluginManifestResponse
    enabled: bool
    trusted: bool
    loaded: bool
    healthy: bool
    last_error: str | None = None
    contributions: list[PluginContributionResponse] = Field(default_factory=list)
    current_settings: dict[str, Any] = Field(default_factory=dict)


class PluginsListResponse(BaseModel):
    plugins: list[PluginPackageResponse]
    total: int


def _serialize_manifest(manifest: PluginManifest) -> PluginManifestResponse:
    return PluginManifestResponse(
        plugin_id=manifest.plugin_id,
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        author=manifest.author,
        official=manifest.official,
        contribution_types=[item.value for item in manifest.contribution_types],
        source=manifest.source,
        plugin_dir=manifest.plugin_dir,
        manifest_path=manifest.manifest_path,
    )


def _serialize_contribution(contribution: PluginContribution) -> PluginContributionResponse:
    return PluginContributionResponse(
        plugin_id=contribution.plugin_id,
        contribution_id=contribution.contribution_id,
        contribution_type=contribution.contribution_type.value if hasattr(contribution.contribution_type, "value") else str(contribution.contribution_type),
        display_name=contribution.display_name,
        description=contribution.description,
        surface=contribution.surface,
        fields=[field.model_dump() for field in contribution.fields],
        metadata=dict(contribution.metadata),
    )


def _serialize_package(state: PluginPackageState) -> PluginPackageResponse:
    return PluginPackageResponse(
        manifest=_serialize_manifest(state.manifest),
        enabled=state.enabled,
        trusted=state.trusted,
        loaded=state.loaded,
        healthy=state.healthy,
        last_error=state.last_error,
        contributions=[_serialize_contribution(item) for item in state.contributions],
        current_settings=dict(state.current_settings),
    )


def _require_package(plugin_id: str):
    manager = get_plugin_manager()
    package = manager.get_package(plugin_id)
    if package is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
    return manager, package


@plugins_router.get("", response_model=PluginsListResponse)
async def list_plugins():
    manager = get_plugin_manager()
    packages = manager.list_packages()
    return PluginsListResponse(
        plugins=[_serialize_package(item) for item in packages],
        total=len(packages),
    )


@plugins_router.post("/rescan", response_model=PluginsListResponse)
async def rescan_plugins():
    manager = reload_plugin_manager()
    packages = manager.list_packages()
    return PluginsListResponse(
        plugins=[_serialize_package(item) for item in packages],
        total=len(packages),
    )


@plugins_router.post("/{plugin_id}/enable", response_model=PluginPackageResponse)
async def enable_plugin(plugin_id: str):
    manager, _ = _require_package(plugin_id)
    state = manager.enable_plugin(plugin_id)
    return _serialize_package(state)


@plugins_router.post("/{plugin_id}/disable", response_model=PluginPackageResponse)
async def disable_plugin(plugin_id: str):
    manager, _ = _require_package(plugin_id)
    state = manager.disable_plugin(plugin_id)
    return _serialize_package(state)


@plugins_router.post("/{plugin_id}/reload", response_model=PluginPackageResponse)
async def reload_plugin(plugin_id: str):
    manager, _ = _require_package(plugin_id)
    state = manager.reload_plugin(plugin_id)
    return _serialize_package(state)


@plugins_router.get("/{plugin_id}/settings", response_model=PluginPackageResponse)
async def get_plugin_settings(plugin_id: str):
    _, package = _require_package(plugin_id)
    return _serialize_package(package)


@plugins_router.put("/{plugin_id}/settings", response_model=PluginPackageResponse)
async def update_plugin_settings(plugin_id: str, request: PluginSettingsUpdateRequest):
    manager, _ = _require_package(plugin_id)
    state = manager.update_plugin_settings(plugin_id, request.updates)
    return _serialize_package(state)
