"""Pydantic response models for plugin routes."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ...plugins.contracts import (
    ExtensionFieldOption,
    ActivationFlowSpec,
    ExtensionFieldSpec,
    PluginCapability,
    PluginDisplayGroupSpec,
    PluginIdentifier,
    PluginRegistryEntry,
    PluginSettingsActionSpec,
    PluginSettingsResourceSpec,
    SettingsUIBlockSpec,
)


class ExtensionFieldOptionResponse(ExtensionFieldOption):
    label_translated: str | None = None


class ExtensionFieldResponse(ExtensionFieldSpec):
    """Host-rendered plugin field, including translated presentation metadata."""

    options: list[ExtensionFieldOptionResponse] = Field(default_factory=list)
    label_translated: str | None = None
    description_translated: str | None = None
    section_translated: str | None = None
    section_note_translated: str | None = None


class PluginSettingsActionRequest(BaseModel):
    field_values: dict[str, Any] = Field(default_factory=dict)


class ActivationFlowResponse(ActivationFlowSpec):
    fields: list[ExtensionFieldResponse] = Field(default_factory=list)
    title_translated: str | None = None
    description_translated: str | None = None
    confirm_label_translated: str | None = None
    cancel_label_translated: str | None = None


class PluginSettingsActionResponse(PluginSettingsActionSpec):
    label_translated: str | None = None
    description_translated: str | None = None
    button_label_translated: str | None = None


class PluginSettingsUiBlockResponse(SettingsUIBlockSpec):
    title_translated: str | None = None
    description_translated: str | None = None


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
    protocol_version: Literal[2]
    min_sdk_version: str
    execution_mode: Literal["restricted_process", "trusted_process"]
    settings_fields: list[ExtensionFieldResponse]
    activation_flow: ActivationFlowResponse | None = None
    settings_actions: list[PluginSettingsActionResponse] = Field(default_factory=list)
    settings_resources: list[PluginSettingsResourceSpec] = Field(default_factory=list)
    settings_ui_blocks: list[PluginSettingsUiBlockResponse] = Field(default_factory=list)
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
    surface: Literal["extensions", "tools", "timeline"]
    fields: list[ExtensionFieldResponse] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginPackageResponse(BaseModel):
    manifest: PluginManifestResponse
    enabled: bool
    trusted: bool
    package_sha256: str | None = None
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
    protocol_version: Literal[2]
    execution_mode: Literal["restricted_process", "trusted_process"]
    min_sdk_version: str
    settings_fields: list[ExtensionFieldSpec] = Field(default_factory=list)
    activation_flow: ActivationFlowSpec | None = None
    settings_actions: list[PluginSettingsActionSpec] = Field(default_factory=list)
    settings_resources: list[PluginSettingsResourceSpec] = Field(default_factory=list)
    settings_ui_blocks: list[SettingsUIBlockSpec] = Field(default_factory=list)
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
    model_config = ConfigDict(extra="forbid")
    plugin_id: PluginIdentifier
    plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class PluginRegistryApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class PluginInstallPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plugin_id: PluginIdentifier
    update: bool


_PlanDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PluginInstallPlanChangeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry: PluginRegistryEntry
    action: Literal["install", "update", "reuse"]
    reason: str
    current_version: str | None
    current_package_sha256: _PlanDigest | None
    current_installed_package_sha256: _PlanDigest | None
    current_dependency_package_sha256: dict[PluginIdentifier, _PlanDigest]
    dependency_package_sha256: dict[PluginIdentifier, _PlanDigest]


class PluginInstallPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["registry-install-plan-v1"]
    target_id: PluginIdentifier
    update: bool
    registry_fingerprint: _PlanDigest
    fingerprint: _PlanDigest
    coordinated: bool
    changes: list[PluginInstallPlanChangeResponse] = Field(min_length=1, max_length=16)


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
    "PluginInstallPlanRequest",
    "PluginInstallPlanResponse",
    "PluginInstallPlanChangeResponse",
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
