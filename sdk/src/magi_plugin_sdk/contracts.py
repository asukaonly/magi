"""Typed contracts for unified plugin extensions."""

from __future__ import annotations

import keyword
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .versioning import PluginVersion

_RESERVED_PLUGIN_IDENTIFIERS = {
    "aux",
    "con",
    "index",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def _reject_reserved_plugin_identifier(value: str) -> str:
    if value in _RESERVED_PLUGIN_IDENTIFIERS:
        raise ValueError("Plugin identifier is reserved by the host or operating system")
    return value


_PluginIdentifier = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_-]+$",
    ),
    AfterValidator(_reject_reserved_plugin_identifier),
]
PluginIdentifier = _PluginIdentifier


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
    path_kind: Literal["file", "directory"] | None = None
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


class ActivationFirstContextSpec(BaseModel):
    """First-run-only activation settings applied by the host onboarding UI."""

    max_items_per_sync: int | None = Field(default=None, ge=1)
    """Optional first-sync item limit. The host uses 200 only when omitted."""
    settings_overrides: dict[str, Any] = Field(default_factory=dict)


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
    first_context: ActivationFirstContextSpec | None = None


class SettingsUIBlockSpec(BaseModel):
    """Host-rendered custom settings block declared by a plugin.

    Blocks are read-only or selection widgets whose underlying data comes from a
    ``PluginSettingsResourceSpec``. The ``presentation`` hint tells the host
    which widget to render. New presentations may be added over time as the
    plugin platform matures.

    ``value_key`` is only meaningful for blocks that bind a selection back to a
    settings field (e.g. ``calendar_list``). Read-only presentations like
    ``permission_status`` ignore it; plugins should still pass a stable value
    such as ``"_readonly"`` to keep the schema stable.
    """

    block_id: str
    type: Literal["resource_picker"] = "resource_picker"
    title: str
    description: str = ""
    resource_name: str
    value_key: str
    presentation: Literal["calendar_list", "list", "permission_status"] = "list"
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

    plugin_id: _PluginIdentifier
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


class DerivedAssertionRuleSpec(BaseModel):
    """Domain signal semantics for host-owned graph-to-assertion promotion."""

    rule_id: str
    source_predicates: list[str] = Field(min_length=1)
    source_types: list[str] = Field(min_length=1)
    trait_family: str
    trait_name_template: str
    min_observations: int = Field(default=3, ge=1)
    min_distinct_days: int = Field(default=2, ge=1)
    signal_preset: Literal[
        "passive_exposure",
        "sustained_engagement",
        "deliberate_choice",
        "structured_source",
    ] = "passive_exposure"
    durable_permitted: bool = False
    durable_min_observations: int = Field(default=6, ge=6)
    durable_min_distinct_days: int = Field(default=3, ge=3)
    durable_min_span_days: float = Field(default=14.0, ge=14.0)
    source_domains: list[str] = Field(default_factory=lambda: ["external_activity"])
    value_strategy: Literal["canonical_name", "object_id", "object_slug"] = "canonical_name"
    object_types: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_durable_signal(self) -> "DerivedAssertionRuleSpec":
        if self.durable_permitted and self.signal_preset == "passive_exposure":
            raise ValueError("passive_exposure cannot permit durable assertions")
        return self


class ExtractionProfileSpec(BaseModel):
    """Declarative L2 extraction profile contributed by a plugin.

    Plugins declare source-local extraction and presentation preferences here.
    The host owns ontology routing, materialization, and final write guards.
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
    phase1_instructions: str | None = None
    summary_instructions: str | None = None
    allowed_assertion_traits: list[str] | Literal["all"] | None = None
    derived_assertion_specs: list[DerivedAssertionRuleSpec] = Field(default_factory=list)


class Triggers(BaseModel):
    """Conditions under which a plugin should be auto-suggested.

    All three categories are OR-combined: any matching intent, entity, or keyword
    contributes to the match score (weighted by signal type in the matcher).
    """

    intents: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    keywords: dict[str, list[str]] = Field(default_factory=dict)
    """Locale (e.g., 'zh', 'en') to keyword list mapping."""


class LocalizedText(BaseModel):
    """Per-locale strings; both zh and en are required."""

    zh: str
    en: str


class SuggestionSurfaceSpec(BaseModel):
    """Plugin-owned presentation for one recommendation surface."""

    order: int = Field(default=100, ge=0)
    rationale: LocalizedText | None = None
    scope: LocalizedText | None = None


class SuggestionSurfacesSpec(BaseModel):
    """Recommendation surfaces where the plugin opts in to appear."""

    empty_state: SuggestionSurfaceSpec | None = None
    first_context: SuggestionSurfaceSpec | None = None


class PluginCapability(BaseModel):
    """A single self-declared capability shown to the user for install-time
    consent. NOT enforced at runtime (no sandbox this iteration).

    ``capability`` is a permissive ``str`` for forward-compat: a newer
    registry may declare a capability an older app doesn't know, and that must
    not break parsing. The authoritative known set is enforced at build time in
    magi-plugins ``scripts/build-registry.py`` and rendered with a known map +
    graceful fallback in the frontend. Known values: screen_recording,
    accessibility, calendar, photos, contacts, system_media, filesystem_read,
    filesystem_write, network, subprocess.
    """

    capability: str
    scope: list[str] = Field(default_factory=list)
    """For filesystem_read/write/network/subprocess: path prefixes / hosts /
    executables. Empty = unspecified (broadest). Ignored for OS permissions."""
    optional: bool = False
    reason: str = ""
    reason_i18n: dict[str, str] = Field(default_factory=dict)


class PluginPermissions(BaseModel):
    """The ``[plugin.permissions]`` table. ``extra='allow'`` tolerates legacy
    keys (``declares``, ``memory_access``) so existing manifests still parse."""

    capabilities: list[PluginCapability] = Field(default_factory=list)
    model_config = {"extra": "allow"}


class LocalRequirementFileExists(BaseModel):
    """Requires a file to exist at the platform-specific path."""

    check_kind: Literal["file_exists"] = "file_exists"
    paths_per_platform: dict[str, str]
    """Map of platform key (darwin / win32 / linux) to file path. Path may use
    ~ for home and %VAR% for environment variables. If the current platform key
    is absent, the requirement is considered failed."""


class LocalRequirementExecutableInPath(BaseModel):
    """Requires at least one named executable to be reachable via PATH."""

    check_kind: Literal["executable_in_path"] = "executable_in_path"
    names: list[str]
    """Any-one-of executable names searched via shutil.which()."""


class LocalRequirementAppInstalled(BaseModel):
    """Requires an application identified by a platform-native identifier to be installed."""

    check_kind: Literal["app_installed"] = "app_installed"
    identifier_per_platform: dict[str, str]
    """Map platform key to a platform-native identifier: macOS bundle id
    (com.example.App), Windows uninstall registry key DisplayName fragment, or
    Linux .desktop file basename."""


LocalRequirement = Annotated[
    Union[
        LocalRequirementFileExists,
        LocalRequirementExecutableInPath,
        LocalRequirementAppInstalled,
    ],
    Field(discriminator="check_kind"),
]


class SuggestionDescriptor(BaseModel):
    """Declares how this plugin should be surfaced to users who lack it.

    See docs/plugin-suggestion-descriptor.md for the author guide.
    """

    category: str
    """Free-form group key. Sibling plugins (e.g. chrome-history /
    safari-history) share a category so the suggestion UI can bundle them."""
    triggers: Triggers
    platform_support: list[str]
    """Platforms where the plugin can run, in sys.platform values."""
    local_requirements: list[LocalRequirement] = Field(default_factory=list)
    """AND-combined; all must pass for the plugin to be 'available'."""
    rationale: LocalizedText
    setup_time_estimate_seconds: int = 30
    data_locality: Literal["local_only", "uploads"] = "local_only"
    icon: str | None = None
    """Optional icon path; if unset, the plugin's default icon is used."""
    surfaces: SuggestionSurfacesSpec = Field(default_factory=SuggestionSurfacesSpec)
    """Plugin-owned empty-state and first-context presentation metadata."""


class PluginDisplayGroupSpec(BaseModel):
    """User-facing grouping metadata for marketplace and installed plugin UIs."""

    id: str
    """Stable group id shared by related plugin implementations."""
    name: str
    name_i18n: dict[str, str] = Field(default_factory=dict)
    description: str = ""
    description_i18n: dict[str, str] = Field(default_factory=dict)
    icon: str = ""
    order: int = 100
    member_label: str = ""
    member_label_i18n: dict[str, str] = Field(default_factory=dict)
    member_order: int = 100


def _validate_direct_plugin_dependencies(
    plugin_id: str,
    depends_on: list[str],
) -> None:
    """Require one package dependency list to be unique and non-reflexive."""

    if len(depends_on) != len(set(depends_on)):
        raise ValueError("Plugin dependencies cannot contain duplicate plugin ids")
    if plugin_id in depends_on:
        raise ValueError("Plugin package cannot depend on itself")


class PluginManifest(BaseModel):
    """Parsed manifest for a plugin package.

    Plugins declare per-plugin default settings under ``[plugin.default_settings]``
    in their ``plugin.toml``. When the host first creates
    ``~/.magi/config/plugins/{plugin_id}.yaml`` it writes this manifest-provided
    dict verbatim. This is the sole source of seed defaults — adding a new
    plugin requires zero magi backend changes.
    """

    plugin_id: _PluginIdentifier = Field(alias="id")
    name: str
    name_i18n: dict[str, str] = Field(default_factory=dict)
    version: PluginVersion
    description: str = ""
    description_i18n: dict[str, str] = Field(default_factory=dict)
    author: str = "Magi Team"
    icon: str = ""
    """Optional icon declaration: ``asset:assets/icon.svg`` for packaged images
    or ``lucide:calendar-days`` for a generic host-provided icon."""
    entry_module: str = "plugin"
    entry_class: str = "Plugin"
    official: bool = False
    data_locality: str = ""
    """Privacy-transparency signal for the marketplace. ``"local_only"`` means the
    plugin processes and stores everything on-device and sends nothing out; empty
    means unspecified (no badge). Surfaced as a "Local only" badge."""
    kind: Literal["plugin", "library"] = "plugin"
    """Package kind. ``library`` means the package only ships Python modules
    consumed by other plugins via ``depends_on`` — it is not loaded as a
    :class:`Plugin` instance, never appears in user-facing market/installed
    lists, and is auto-installed and refcounted by the plugin manager."""
    contribution_types: list[ContributionType] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list, max_length=128)
    """PIP package dependencies installed under the plugin's ``.deps/`` dir."""
    depends_on: list[_PluginIdentifier] = Field(default_factory=list, max_length=8)
    """Library packages this plugin imports from. Each entry is a
    ``plugin_id`` whose registry entry must declare ``kind = "library"``.
    The manager auto-installs missing libraries during install,
    refcount-protects them on uninstall, and injects their install-root parent
    onto ``sys.path`` before loading this plugin."""
    min_sdk_version: str = ""
    platforms: list[str] = Field(default_factory=list)
    homepage: str = ""
    repository: str = ""
    plugin_dir: str = ""
    manifest_path: str = ""
    source: Literal["builtin", "external"] = "external"
    default_settings: dict[str, Any] = Field(default_factory=dict)
    """Optional nested dict of default settings written to
    ``~/.magi/config/plugins/{id}.yaml`` if missing.

    Typically shaped as ``{"sensors": {<sensor_key>: {...}}}`` but plugins may
    place other keys here too. Read from the ``[plugin.default_settings]`` table
    in ``plugin.toml``.
    """
    suggestion_descriptor: SuggestionDescriptor | None = None
    """Optional declaration of how/when this plugin should be auto-suggested.

    See :class:`SuggestionDescriptor` and the onboarding redesign spec
    (``docs/superpowers/specs/2026-05-28-onboarding-redesign-design.md``).
    """
    display_group: PluginDisplayGroupSpec | None = None
    """Optional user-facing grouping metadata. Sibling plugins with the same
    ``display_group.id`` render as one marketplace/installed-plugin card."""
    permissions: Optional[PluginPermissions] = None
    """Declared capabilities + legacy permission keys, from the
    ``[plugin.permissions]`` table. See :class:`PluginCapability`."""

    model_config = {"populate_by_name": True}

    @field_validator("entry_module", "entry_class")
    @classmethod
    def validate_entry_identifier(cls, value: str) -> str:
        """Reject entrypoint names that could escape the plugin module."""

        if not value.isidentifier() or keyword.iskeyword(value):
            raise ValueError("Plugin entrypoint names must be single Python identifiers")
        return value

    @model_validator(mode="after")
    def validate_direct_dependencies(self) -> "PluginManifest":
        """Reject duplicate and self-referential package dependencies."""

        _validate_direct_plugin_dependencies(self.plugin_id, self.depends_on)
        return self

    @property
    def plugin_path(self) -> Path:
        return Path(self.plugin_dir)

    @property
    def capabilities(self) -> list[PluginCapability]:
        return self.permissions.capabilities if self.permissions else []


class PluginContribution(BaseModel):
    """Contribution descriptor returned to APIs and UIs."""

    plugin_id: _PluginIdentifier
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

    plugin_id: _PluginIdentifier
    name: str
    name_i18n: dict[str, str] = Field(default_factory=dict)
    version: PluginVersion
    package_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Host-verified digest of the complete distributable plugin package.",
    )
    path: str = ""
    description: str = ""
    description_i18n: dict[str, str] = Field(default_factory=dict)
    author: str = ""
    icon: str = ""
    """Icon declaration copied from the plugin manifest."""
    icon_data: str = ""
    """Validated self-contained icon data for marketplace display before install."""
    official: bool = False
    data_locality: str = ""
    """Mirrors :attr:`PluginManifest.data_locality` — ``"local_only"`` renders a
    "Local only" privacy badge in the marketplace; empty means unspecified."""
    kind: Literal["plugin", "library"] = "plugin"
    """Mirrors :attr:`PluginManifest.kind`; libraries are hidden from
    user-facing market listings and installed via dep closure only."""
    contribution_types: list[str] = Field(default_factory=list)
    depends_on: list[_PluginIdentifier] = Field(default_factory=list, max_length=8)
    """Library registry entries this package imports from (plugin_ids)."""
    platforms: list[str] = Field(default_factory=list)
    min_sdk_version: str = ""
    homepage: str = ""
    repository: str = ""
    suggestion_descriptor: SuggestionDescriptor | None = None
    """Optional declaration of how/when this plugin should be auto-suggested,
    mirroring :attr:`PluginManifest.suggestion_descriptor` so the registry can
    drive install-first suggestions without a local manifest."""
    capabilities: list[PluginCapability] = Field(default_factory=list)
    """Self-declared capabilities, copied verbatim from the plugin's
    ``[[plugin.permissions.capabilities]]`` by build-registry.py."""
    display_group: PluginDisplayGroupSpec | None = None
    """Optional declaration that this plugin should appear under a shared
    user-facing group instead of a standalone card."""

    @model_validator(mode="after")
    def validate_direct_dependencies(self) -> "PluginRegistryEntry":
        """Reject duplicate and self-referential package dependencies."""

        _validate_direct_plugin_dependencies(self.plugin_id, self.depends_on)
        return self

    @property
    def display_icon(self) -> str:
        """Return the install-independent icon value used by host UIs."""
        return self.icon_data or self.icon


def _validate_registry_dependency_graph(
    entries: list[PluginRegistryEntry],
) -> None:
    """Require registry ids and dependency edges to form one valid graph."""

    entries_by_id: dict[str, PluginRegistryEntry] = {}
    for entry in entries:
        if entry.plugin_id in entries_by_id:
            raise ValueError(
                f"Plugin registry contains duplicate plugin id: {entry.plugin_id}"
            )
        entries_by_id[entry.plugin_id] = entry

    for entry in entries:
        for dependency_id in entry.depends_on:
            dependency = entries_by_id.get(dependency_id)
            if dependency is None:
                raise ValueError(
                    f"Plugin {entry.plugin_id} depends on missing package "
                    f"{dependency_id}"
                )
            if dependency.kind != "library":
                raise ValueError(
                    f"Plugin {entry.plugin_id} depends on non-library package "
                    f"{dependency_id}"
                )

    unresolved_dependency_counts = {
        entry.plugin_id: len(entry.depends_on) for entry in entries
    }
    dependents_by_id = {entry.plugin_id: [] for entry in entries}
    for entry in entries:
        for dependency_id in entry.depends_on:
            dependents_by_id[dependency_id].append(entry.plugin_id)

    ready = [
        plugin_id
        for plugin_id, count in unresolved_dependency_counts.items()
        if count == 0
    ]
    resolved_count = 0
    while ready:
        dependency_id = ready.pop()
        resolved_count += 1
        for dependent_id in dependents_by_id[dependency_id]:
            unresolved_dependency_counts[dependent_id] -= 1
            if unresolved_dependency_counts[dependent_id] == 0:
                ready.append(dependent_id)

    if resolved_count != len(entries):
        raise ValueError("Plugin registry dependency cycle detected")


class PluginRegistryIndex(BaseModel):
    """Response model for the remote plugin registry listing."""

    plugins: list[PluginRegistryEntry] = Field(default_factory=list, max_length=4096)
    registry_version: Literal["4"]
    repo_url: str = ""

    @model_validator(mode="after")
    def validate_dependency_graph(self) -> "PluginRegistryIndex":
        """Reject registry entries and dependency edges that are not self-consistent."""

        _validate_registry_dependency_graph(self.plugins)
        return self


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
