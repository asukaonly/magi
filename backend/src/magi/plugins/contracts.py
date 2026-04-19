"""Typed contracts for unified plugin extensions."""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ContributionType(str, Enum):
    """Supported plugin contribution categories."""

    TOOL = "tool"
    SENSOR = "sensor"
    ACTION = "action"


class ExtensionFieldOption(BaseModel):
    """Option for a select-like plugin field."""

    label: str
    value: str


class ExtensionFieldSpec(BaseModel):
    """Declarative settings field exposed by a plugin contribution."""

    key: str
    type: Literal["switch", "select", "input", "number", "secret", "path", "tags"] = "input"
    label: str
    description: str = ""
    default: Any = None
    required: bool = False
    options: list[ExtensionFieldOption] = Field(default_factory=list)
    section: str = "general"
    surface: Literal["extensions", "tools", "timeline", "actions"] = "extensions"
    order: int = 0
    placeholder: Optional[str] = None
    depends_on_key: Optional[str] = None
    depends_on_values: list[str] = Field(default_factory=list)


class ActivationFlowSpec(BaseModel):
    """Declarative first-enable flow rendered by the host UI."""

    title: str
    description: str = ""
    confirm_label: str = "Confirm"
    cancel_label: str = "Cancel"
    authorize_on_confirm: bool = False
    enabled_key: str
    configured_key: str
    fields: list[ExtensionFieldSpec] = Field(default_factory=list)


class SettingsUIBlockSpec(BaseModel):
    """Host-rendered custom settings block declared by a plugin."""

    block_id: str
    type: Literal["resource_picker"] = "resource_picker"
    title: str
    description: str = ""
    resource_name: str
    value_key: str
    presentation: Literal["calendar_list", "list"] = "list"
    depends_on_key: Optional[str] = None
    depends_on_values: list[str] = Field(default_factory=list)


class PluginSettingsResourceSpec(BaseModel):
    """Read-only settings resource exposed by a plugin."""

    resource_name: str
    resource_type: Literal["collection"] = "collection"
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginSettingsResourcePayload(BaseModel):
    """Resolved payload returned by a plugin settings resource."""

    plugin_id: str
    resource_name: str
    resource_type: str = "collection"
    data: Any = None


class PluginManifest(BaseModel):
    """Parsed manifest for a plugin package."""

    plugin_id: str = Field(alias="id")
    name: str
    version: str
    description: str = ""
    author: str = "Magi Team"
    entry_module: str = "plugin"
    entry_class: str = "Plugin"
    official: bool = False
    contribution_types: list[ContributionType] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    min_sdk_version: str = ""
    platforms: list[str] = Field(default_factory=list)
    homepage: str = ""
    repository: str = ""
    plugin_dir: str = ""
    manifest_path: str = ""
    source: Literal["builtin", "external"] = "external"

    model_config = {"populate_by_name": True}

    @property
    def plugin_path(self) -> Path:
        return Path(self.plugin_dir)


class PluginContribution(BaseModel):
    """Contribution descriptor returned to APIs and UIs."""

    plugin_id: str
    contribution_id: str
    contribution_type: ContributionType
    display_name: str
    description: str = ""
    surface: Literal["extensions", "tools", "timeline", "actions"] = "extensions"
    fields: list[ExtensionFieldSpec] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginPackageState(BaseModel):
    """Current runtime state for a plugin package."""

    manifest: PluginManifest
    enabled: bool = False
    trusted: bool = False
    loaded: bool = False
    healthy: bool = True
    last_error: Optional[str] = None
    contributions: list[PluginContribution] = Field(default_factory=list)
    current_settings: dict[str, Any] = Field(default_factory=dict)


class PluginRegistryEntry(BaseModel):
    """Remote plugin registry entry describing an available plugin."""

    plugin_id: str
    name: str
    version: str
    path: str = ""
    description: str = ""
    author: str = ""
    official: bool = False
    contribution_types: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    min_sdk_version: str = ""
    homepage: str = ""
    repository: str = ""


class PluginRegistryIndex(BaseModel):
    """Response model for the remote plugin registry listing."""

    plugins: list[PluginRegistryEntry] = Field(default_factory=list)
    registry_version: str = "1"
    repo_url: str = ""
