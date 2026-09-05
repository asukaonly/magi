"""Pydantic response models for plugin routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ...plugins.contracts import (
    PluginCapability,
    PluginDisplayGroupSpec,
    PluginIdentifier,
)


class PluginSettingsActionRequest(BaseModel):
    field_values: dict[str, Any] = Field(default_factory=dict)


class PluginSettingsActionRunResponse(BaseModel):
    connection_id: str
    plugin_id: str
    action_id: str
    session_id: str
    status: Literal["pending", "succeeded", "failed", "cancelled", "uncertain"]
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    settings_updates: dict[str, Any] = Field(default_factory=dict)


class PluginManifestResponse(BaseModel):
    protocol_version: int
    min_sdk_version: str
    execution_mode: str
    settings_fields: list[dict[str, Any]]
    activation_flow: dict[str, Any] | None = None
    settings_actions: list[dict[str, Any]] = Field(default_factory=list)
    settings_resources: list[dict[str, Any]] = Field(default_factory=list)
    settings_ui_blocks: list[dict[str, Any]] = Field(default_factory=list)
    plugin_id: str
    name: str
    version: str
    description: str
    author: str
    icon: str = ""
    display_group: PluginDisplayGroupSpec | None = None
    official: bool
    contribution_types: list[str]
    source: str
    plugin_dir: str
    manifest_path: str
    capabilities: list[PluginCapability] = Field(default_factory=list)
    consented_capabilities: list[PluginCapability] | None = None


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
    connection_id: str
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
    icon: str = ""
    display_group: PluginDisplayGroupSpec | None = None
    official: bool = False
    data_locality: str = ""
    contribution_types: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    min_sdk_version: str = ""
    homepage: str = ""
    repository: str = ""
    path: str = ""
    installed: bool = False
    installed_version: str | None = None
    update_available: bool = False
    capabilities: list[PluginCapability] = Field(default_factory=list)


class PluginRegistryResponse(BaseModel):
    plugins: list[PluginRegistryEntryResponse] = Field(default_factory=list)
    registry_version: Literal["4"]
    install_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class PluginInstallRequest(BaseModel):
    plugin_id: PluginIdentifier
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class PluginRegistryApprovalRequest(BaseModel):
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class PluginInstallCandidateApprovalRequest(BaseModel):
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PluginInstallCandidateResponse(BaseModel):
    candidate_id: str
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at_ms: int
    manifest: PluginManifestResponse


class PluginInstallLogEntry(BaseModel):
    ts_ms: int
    level: Literal["info", "warning", "error"] = "info"
    stage: str
    message: str


class PluginInstallJobSnapshot(BaseModel):
    job_id: str
    operation: Literal["install", "update", "upload"]
    plugin_id: str | None = None
    filename: str | None = None
    status: Literal["queued", "running", "completed", "failed"]
    stage: str
    progress_pct: float = 0.0
    message: str
    error: str | None = None
    error_code: str | None = None
    logs: list[PluginInstallLogEntry] = Field(default_factory=list)
    result: PluginPackageResponse | None = None
    created_at_ms: int
    updated_at_ms: int
    finished_at_ms: int | None = None


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
    "PluginInstallCandidateApprovalRequest",
    "PluginInstallCandidateResponse",
    "PluginInstallJobSnapshot",
    "PluginInstallLogEntry",
    "PluginInstallRequest",
    "PluginManifestResponse",
    "PluginPackageResponse",
    "PluginRegistryEntryResponse",
    "PluginRegistryApprovalRequest",
    "PluginRegistryResponse",
    "PluginSettingsActionRequest",
    "PluginSettingsActionRunResponse",
    "PluginSettingsResourceResponse",
    "PluginUpdateCheckResponse",
    "PluginsListResponse",
]
