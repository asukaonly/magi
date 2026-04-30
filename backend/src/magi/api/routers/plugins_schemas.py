"""Pydantic response models for plugin routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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


class PluginRegistryEntryResponse(BaseModel):
    plugin_id: str
    name: str
    name_i18n: dict[str, str] = Field(default_factory=dict)
    version: str
    description: str = ""
    description_i18n: dict[str, str] = Field(default_factory=dict)
    author: str = ""
    official: bool = False
    contribution_types: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    min_sdk_version: str = ""
    homepage: str = ""
    repository: str = ""
    path: str = ""
    installed: bool = False
    installed_version: str | None = None
    update_available: bool = False


class PluginRegistryResponse(BaseModel):
    plugins: list[PluginRegistryEntryResponse] = Field(default_factory=list)
    registry_version: str = "1"


class PluginInstallRequest(BaseModel):
    plugin_id: str


class PluginUpdateCheckResponse(BaseModel):
    plugin_id: str
    current_version: str
    latest_version: str
    update_available: bool


class PluginsListResponse(BaseModel):
    plugins: list[PluginPackageResponse]
    total: int


__all__ = [
    "PluginContributionResponse",
    "PluginInstallRequest",
    "PluginManifestResponse",
    "PluginPackageResponse",
    "PluginRegistryEntryResponse",
    "PluginRegistryResponse",
    "PluginSettingsResourceResponse",
    "PluginSettingsUpdateRequest",
    "PluginUpdateCheckResponse",
    "PluginsListResponse",
]