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
    CHANNEL = "channel"
    SKILL = "skill"
    HOOK = "hook"


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
    surface: Literal["extensions", "tools", "timeline"] = "extensions"
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


class PluginSettingsActionSpec(BaseModel):
    """Host-rendered settings action declared by a plugin.

    The host owns routing and UI chrome, while the plugin owns the action
    implementation and any provider-specific protocol details.
    """

    action_id: str
    label: str
    description: str = ""
    button_label: str = "Run"
    presentation: Literal["inline", "qr_code"] = "inline"
    surface: Literal["extensions", "tools", "timeline"] = "extensions"
    contribution_id: str = ""
    contribution_type: ContributionType | None = None
    order: int = 0
    destructive: bool = False
    requires_enabled: bool = True
    poll_interval_ms: int = 2_000
    timeout_ms: int = 480_000
    persist_settings_on_success: bool = False
    depends_on_key: Optional[str] = None
    depends_on_values: list[str] = Field(default_factory=list)


class PluginSettingsActionResult(BaseModel):
    """Result returned by a plugin settings action invocation."""

    status: Literal["pending", "succeeded", "failed", "cancelled"] = "succeeded"
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    settings_updates: dict[str, Any] = Field(default_factory=dict)


class PluginSettingsResourceSpec(BaseModel):
    """Read-only settings resource exposed by a plugin."""

    resource_name: str
    resource_type: Literal["collection", "channel_status"] = "collection"
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginSettingsResourcePayload(BaseModel):
    """Resolved payload returned by a plugin settings resource."""

    plugin_id: str
    resource_name: str
    resource_type: str = "collection"
    data: Any = None


class TemporalSummaryFeatureBudget(BaseModel):
    """Host-provided budget for a plugin temporal feature builder.

    The host may pass only a bounded event sample to a plugin. These fields let
    the plugin report coverage honestly instead of implying it saw every L1
    event in the window.
    """

    source_type: str
    total_event_count: int = 0
    available_event_count: int = 0
    selected_event_count: int = 0
    omitted_event_count: int = 0
    max_feature_events: int = 240
    max_summary_lines: int = 6
    max_representative_events: int = 8
    selection_policy: str = "source_aware_compaction_v1"


class TemporalSummarySourceFeatures(BaseModel):
    """Structured source-local evidence contributed to generic L3 summaries.

    Plugins should return source-specific facts and compact observations, not a
    final cross-source L3 summary. The host uses these features alongside a
    balanced set of representative raw events.
    """

    source_type: str
    feature_type: str = "source_summary_features"
    total_event_count: int = 0
    covered_event_count: int = 0
    omitted_event_count: int = 0
    coverage_ratio: float | None = None
    summary_lines: list[str] = Field(default_factory=list)
    top_entities: list[dict[str, Any]] = Field(default_factory=list)
    top_tags: list[dict[str, Any]] = Field(default_factory=list)
    time_buckets: list[dict[str, Any]] = Field(default_factory=list)
    representative_event_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractionProfileSpec(BaseModel):
    """Declarative L2 extraction profile contributed by a plugin.

    Plugins declare source-local extraction preferences here. The host owns
    ontology validation, prompt assembly, and final write guards.
    """

    profile_id: str
    source_types: list[str] = Field(default_factory=list)
    allowed_entity_types: list[str] | Literal["all"] = "all"
    allowed_predicates: list[str] | Literal["all"] = "all"
    structured_allowed_entity_types: list[str] | Literal["all"] | None = None
    structured_allowed_predicates: list[str] | Literal["all"] | None = None
    allowed_assertion_families: list[str] | Literal["all"] = "all"
    allow_graph: bool = True
    allow_assertion: bool = True
    extraction_instructions: str | None = None


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
    surface: Literal["extensions", "tools", "timeline"] = "extensions"
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
    name_i18n: dict[str, str] = Field(default_factory=dict)
    version: str
    path: str = ""
    description: str = ""
    description_i18n: dict[str, str] = Field(default_factory=dict)
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


class SummaryProfileSpec(BaseModel):
    """Declarative L3 activity summary profile contributed by a plugin.

    A profile tells the host runtime that the plugin wants periodic activity
    summaries built from L1 events of one or more sensor sources, scoped to
    a stable summary category (used as the L3 ``summary_category`` column).

    The host scheduler turns each profile + window into a periodic job that
    queries the matching L1 events and feeds them through the standard
    temporal summary pipeline. Plugins do not write L3 rows directly.
    """

    profile_id: str
    summary_category: str
    source_types: list[str] = Field(default_factory=list)
    windows: list[Literal["hour", "day", "week"]] = Field(default_factory=lambda: ["day"])
    settle_window_seconds: int = 300
    min_events: int = 4
    intent_verbs: list[str] = Field(default_factory=list)
    prompt_hints: dict[str, Any] = Field(default_factory=dict)
