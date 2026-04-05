"""Plugin management API router."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ...core.runtime_bindings import require_plugin_manager
from ...plugins.contracts import (
    ExtensionFieldSpec,
    PluginContribution,
    PluginManifest,
    PluginPackageState,
    PluginSettingsResourcePayload,
)
from ...plugins.i18n import PluginI18n

plugins_router = APIRouter()


def _get_plugin_i18n(plugin_id: str, plugin_dir: str) -> PluginI18n:
    """Get i18n helper for a plugin, using cached instance if plugin is loaded."""
    manager = require_plugin_manager()
    plugin_instance = manager._plugin_instances.get(plugin_id)
    if plugin_instance:
        return plugin_instance.i18n
    # For unloaded plugins, create i18n instance directly
    return PluginI18n(plugin_id, Path(plugin_dir))


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


class PluginSettingsResourceResponse(BaseModel):
    plugin_id: str
    resource_name: str
    resource_type: str
    data: Any = None


class PluginsListResponse(BaseModel):
    plugins: list[PluginPackageResponse]
    total: int


def _serialize_manifest(manifest: PluginManifest) -> PluginManifestResponse:
    i18n = _get_plugin_i18n(manifest.plugin_id, manifest.plugin_dir)
    plugin_id = manifest.plugin_id

    # Translate name and description
    translated_name = i18n.t(f"{plugin_id}.name", fallback=manifest.name)
    translated_description = i18n.t(f"{plugin_id}.description", fallback=manifest.description)

    return PluginManifestResponse(
        plugin_id=manifest.plugin_id,
        name=translated_name,
        version=manifest.version,
        description=translated_description,
        author=manifest.author,
        official=manifest.official,
        contribution_types=[item.value for item in manifest.contribution_types],
        source=manifest.source,
        plugin_dir=manifest.plugin_dir,
        manifest_path=manifest.manifest_path,
    )


def _serialize_field(field: ExtensionFieldSpec, i18n: PluginI18n, contribution_id: str) -> dict[str, Any]:
    """Serialize a field with translation."""
    # Translate label and description
    label_key = f"fields.{contribution_id}.{field.key}.label"
    desc_key = f"fields.{contribution_id}.{field.key}.description"

    translated_label = i18n.t(label_key, fallback=field.label)
    translated_description = i18n.t(desc_key, fallback=field.description)

    field_dict = field.model_dump()
    field_dict["label"] = translated_label
    field_dict["description"] = translated_description

    # Translate options if present
    if field_dict.get("options"):
        translated_options = []
        for opt in field_dict["options"]:
            opt_label_key = f"fields.{contribution_id}.{field.key}.options.{opt['value']}"
            translated_opt_label = i18n.t(opt_label_key, fallback=opt["label"])
            translated_options.append({"label": translated_opt_label, "value": opt["value"]})
        field_dict["options"] = translated_options

    return field_dict


def _serialize_contribution(contribution: PluginContribution, i18n: PluginI18n) -> PluginContributionResponse:
    contribution_id = contribution.contribution_id

    # Translate display_name and description
    display_name_key = f"contributions.{contribution_id}.display_name"
    description_key = f"contributions.{contribution_id}.description"

    translated_display_name = i18n.t(display_name_key, fallback=contribution.display_name)
    translated_description = i18n.t(description_key, fallback=contribution.description)

    # Serialize fields with translation
    serialized_fields = [_serialize_field(field, i18n, contribution_id) for field in contribution.fields]

    return PluginContributionResponse(
        plugin_id=contribution.plugin_id,
        contribution_id=contribution.contribution_id,
        contribution_type=contribution.contribution_type.value if hasattr(contribution.contribution_type, "value") else str(contribution.contribution_type),
        display_name=translated_display_name,
        description=translated_description,
        surface=contribution.surface,
        fields=serialized_fields,
        metadata=dict(contribution.metadata),
    )


def _serialize_package(state: PluginPackageState) -> PluginPackageResponse:
    i18n = _get_plugin_i18n(state.manifest.plugin_id, state.manifest.plugin_dir)

    return PluginPackageResponse(
        manifest=_serialize_manifest(state.manifest),
        enabled=state.enabled,
        trusted=state.trusted,
        loaded=state.loaded,
        healthy=state.healthy,
        last_error=state.last_error,
        contributions=[_serialize_contribution(item, i18n) for item in state.contributions],
        current_settings=dict(state.current_settings),
    )


def _require_package(plugin_id: str):
    manager = require_plugin_manager()
    package = manager.get_package(plugin_id)
    if package is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
    return manager, package


@plugins_router.get("", response_model=PluginsListResponse)
async def list_plugins():
    manager = require_plugin_manager()
    packages = manager.list_packages()
    return PluginsListResponse(
        plugins=[_serialize_package(item) for item in packages],
        total=len(packages),
    )


@plugins_router.post("/rescan", response_model=PluginsListResponse)
async def rescan_plugins():
    manager = require_plugin_manager()
    packages = manager.rescan_runtime()
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


@plugins_router.get("/{plugin_id}/settings/resources/{resource_name}", response_model=PluginSettingsResourceResponse)
async def read_plugin_settings_resource(plugin_id: str, resource_name: str):
    manager, _ = _require_package(plugin_id)
    try:
        payload = manager.read_plugin_settings_resource(plugin_id, resource_name)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin settings resource not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if isinstance(payload, PluginSettingsResourcePayload):
        return PluginSettingsResourceResponse(**payload.model_dump())
    return PluginSettingsResourceResponse(**payload)
