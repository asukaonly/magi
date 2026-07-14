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
    ChannelMessageDispatcherProtocol,
    ChannelMessageDispatchOutcome,
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
from .capabilities import (
    BackgroundPort,
    DelegationEventPort,
    ToolCapabilities,
    TracePort,
)

__version__ = "0.1.0"

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
    "ChannelMessageDispatcherProtocol",
    "ChannelMessageDispatchOutcome",
    "ChannelSessionMapperProtocol",
    "ChannelSessionMapping",
    "ChannelTarget",
    "InboundMessage",
    "OutboundContent",
    # Ingress
    "PluginIngressEventHandler",
    "PluginIngressEventRecord",
    "PluginIngressHandlerRegistration",
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
    # Subprocess management (crash-resistant child process lifecycle)
    "ManagedSubprocess",
    "RegistryEntry",
    "DEFAULT_REGISTRY_PATH",
    # Version
    "__version__",
]
