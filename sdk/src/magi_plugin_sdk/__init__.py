"""Magi Plugin SDK — public API.

Install this package to develop Magi plugins without pulling in the full
Magi backend runtime:

    pip install magi-plugin-sdk

Then in your plugin:

    from magi_plugin_sdk import Plugin, SensorSpec, ExtensionFieldSpec

Or, if you prefer the canonical backend import path (works when the full
Magi backend is installed):

    from magi.plugins import Plugin, SensorSpec, ExtensionFieldSpec

Both resolve to the same classes at runtime.
"""

from .base import Plugin
from .control import ControlRequest
from .delivery import DeliveryContent, DeliveryReceipt
from .channels import (
    Channel,
    ChannelConfig,
    ChannelCursorClearProof,
    ChannelInboundClearStrategy,
    ChannelInboundClearRequest,
    ChannelInboundContext,
    ChannelInboundEvidence,
    ChannelInboundRejectedError,
    ChannelInboundRejectionReason,
    ChannelMessageDispatcherProtocol,
    ChannelMessageDispatchOutcome,
    ChannelProviderTimeEvidence,
    ChannelSessionMapperProtocol,
    ChannelSessionMapping,
    ChannelTarget,
    InboundMessage,
    OutboundContent,
)
from .ingress import (
    PluginIngressEventHandler,
    PluginIngressEventRecord,
    PluginIngressHandlerRegistration,
)
from .history_imports import (
    HistoryImportParseResult,
    HistoryImportRecord,
    HistoryImportSource,
    HistoryImporter,
    HistoryImporterSpec,
)
from .user_content import UserContentClearContext, UserContentClearRequest
from .contracts import (
    ActivationFlowSpec,
    ActivationFirstContextSpec,
    ContributionType,
    DerivedAssertionRuleSpec,
    ExtractionProfileSpec,
    ExtensionFieldOption,
    ExtensionFieldSpec,
    PluginContribution,
    PluginDisplayGroupSpec,
    PluginIdentifier,
    PluginManifest,
    PluginPackageState,
    PluginRegistryEntry,
    PluginRegistryIndex,
    PluginSettingsActionResult,
    PluginSettingsActionSpec,
    PluginSettingsResourcePayload,
    PluginSettingsResourceSpec,
    SettingsUIBlockSpec,
    SuggestionSurfaceSpec,
    SuggestionSurfacesSpec,
    SummaryProfileSpec,
    TemporalSummaryFeatureBudget,
    TemporalSummarySourceFeatures,
)
from .i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_ALIASES,
    PluginI18n,
    get_current_language,
    set_current_language,
)
from .logging import configure_basic_logging, get_logger
from .fs import list_managed_directory_names, path_is_link
from .package_identity import (
    CanonicalPackagePath,
    ConflictingPackageIdentityPathError,
    INSTALLED_PACKAGE_IDENTITY_PROFILE,
    InvalidPackageIdentityPathError,
    PACKAGE_IDENTITY_DOMAIN,
    PACKAGE_IDENTITY_RECORD_DOMAIN,
    PACKAGE_IDENTITY_VERSION,
    PackageIdentityBuildError,
    PackageIdentityBuilder,
    PackageIdentityContractError,
    PackageIdentityFile,
    PackageFile,
    PortablePathTracker,
    SOURCE_PACKAGE_IDENTITY_PROFILE,
    WINDOWS_FORBIDDEN_PATH_CHARACTERS,
    WINDOWS_RESERVED_PATH_STEMS,
    canonicalize_package_path,
    compute_package_identity_sha256,
    normalize_package_path_component,
    windows_path_component_issue,
)
from .sensors import (
    ActivityFacet,
    ContentBlock,
    L2BatchPolicy,
    PluginRuntimePaths,
    PullSyncSensor,
    SensorActivity,
    SensorBase,
    SensorMemoryPolicy,
    SensorNarration,
    SensorOutput,
    SensorOutputMetadata,
    SensorSpec,
    SensorSyncContext,
    SensorSyncResult,
    TimelinePresentation,
)
from .subprocess import (
    DEFAULT_REGISTRY_PATH,
    ManagedSubprocess,
    RegistryEntry,
)
from .tools import (
    MultiProviderTool,
    ParameterType,
    Tool,
    ToolConfigSpec,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)
from .versioning import (
    MAX_PLUGIN_VERSION_LENGTH,
    PLUGIN_VERSION_PATTERN,
    PluginVersion,
    is_plugin_version_newer,
    parse_plugin_version,
)
from .capabilities import (
    BackgroundPort,
    DelegationEventPort,
    ToolCapabilities,
    TracePort,
)

__version__ = "0.1.1"

__all__ = [
    # Core base class
    "Plugin",
    # Delivery types (Phase G)
    "DeliveryContent",
    "DeliveryReceipt",
    # Control-plane types (Phase H+2 — approval fanout)
    "ControlRequest",
    # Channels
    "Channel",
    "ChannelConfig",
    "ChannelCursorClearProof",
    "ChannelInboundClearStrategy",
    "ChannelInboundClearRequest",
    "ChannelInboundContext",
    "ChannelInboundEvidence",
    "ChannelInboundRejectedError",
    "ChannelInboundRejectionReason",
    "ChannelMessageDispatcherProtocol",
    "ChannelMessageDispatchOutcome",
    "ChannelProviderTimeEvidence",
    "ChannelSessionMapperProtocol",
    "ChannelSessionMapping",
    "ChannelTarget",
    "InboundMessage",
    "OutboundContent",
    # Ingress
    "PluginIngressEventHandler",
    "PluginIngressEventRecord",
    "PluginIngressHandlerRegistration",
    # One-shot history import adapters
    "HistoryImportParseResult",
    "HistoryImportRecord",
    "HistoryImportSource",
    "HistoryImporter",
    "HistoryImporterSpec",
    # User-content clear lifecycle
    "UserContentClearContext",
    "UserContentClearRequest",
    # Sensor
    "ActivityFacet",
    "ContentBlock",
    "L2BatchPolicy",
    "PluginRuntimePaths",
    "PullSyncSensor",
    "SensorActivity",
    "SensorBase",
    "SensorMemoryPolicy",
    "SensorNarration",
    "SensorOutput",
    "SensorOutputMetadata",
    "SensorSpec",
    "SensorSyncContext",
    "SensorSyncResult",
    "TimelinePresentation",
    # Field / settings specs
    "ExtensionFieldOption",
    "ExtensionFieldSpec",
    "ActivationFirstContextSpec",
    "ActivationFlowSpec",
    "SettingsUIBlockSpec",
    "PluginSettingsActionSpec",
    "PluginSettingsActionResult",
    "PluginSettingsResourceSpec",
    "PluginSettingsResourcePayload",
    "SuggestionSurfaceSpec",
    "SuggestionSurfacesSpec",
    # Manifest and registry
    "ContributionType",
    "DerivedAssertionRuleSpec",
    "ExtractionProfileSpec",
    "PluginContribution",
    "PluginDisplayGroupSpec",
    "PluginManifest",
    "PluginIdentifier",
    "PluginPackageState",
    "PluginRegistryEntry",
    "PluginRegistryIndex",
    "SummaryProfileSpec",
    "TemporalSummaryFeatureBudget",
    "TemporalSummarySourceFeatures",
    # Tools
    "MultiProviderTool",
    "ParameterType",
    "Tool",
    "ToolConfigSpec",
    "ToolErrorCode",
    "ToolExecutionContext",
    "ToolParameter",
    "ToolResult",
    "ToolSchema",
    # Capabilities
    "BackgroundPort",
    "DelegationEventPort",
    "ToolCapabilities",
    "TracePort",
    # i18n
    "PluginI18n",
    "DEFAULT_LANGUAGE",
    "LANGUAGE_ALIASES",
    "get_current_language",
    "set_current_language",
    # logging
    "configure_basic_logging",
    "get_logger",
    # Managed filesystem safety
    "list_managed_directory_names",
    "path_is_link",
    # Subprocess management (crash-resistant child process lifecycle)
    "ManagedSubprocess",
    "RegistryEntry",
    "DEFAULT_REGISTRY_PATH",
    # Plugin package versions
    "MAX_PLUGIN_VERSION_LENGTH",
    "PLUGIN_VERSION_PATTERN",
    "PluginVersion",
    "is_plugin_version_newer",
    "parse_plugin_version",
    # Plugin package identity
    "CanonicalPackagePath",
    "ConflictingPackageIdentityPathError",
    "INSTALLED_PACKAGE_IDENTITY_PROFILE",
    "InvalidPackageIdentityPathError",
    "PACKAGE_IDENTITY_DOMAIN",
    "PACKAGE_IDENTITY_RECORD_DOMAIN",
    "PACKAGE_IDENTITY_VERSION",
    "PackageIdentityBuildError",
    "PackageIdentityBuilder",
    "PackageIdentityContractError",
    "PackageIdentityFile",
    "PackageFile",
    "PortablePathTracker",
    "SOURCE_PACKAGE_IDENTITY_PROFILE",
    "WINDOWS_FORBIDDEN_PATH_CHARACTERS",
    "WINDOWS_RESERVED_PATH_STEMS",
    "canonicalize_package_path",
    "compute_package_identity_sha256",
    "normalize_package_path_component",
    "windows_path_component_issue",
    # Version
    "__version__",
]
