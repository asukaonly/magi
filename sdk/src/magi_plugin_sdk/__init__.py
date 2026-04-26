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
    ContributionType,
    ExtensionFieldOption,
    ExtensionFieldSpec,
    PluginContribution,
    PluginManifest,
    PluginPackageState,
    PluginRegistryEntry,
    PluginRegistryIndex,
    PluginSettingsResourcePayload,
    PluginSettingsResourceSpec,
    SettingsUIBlockSpec,
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

__version__ = "0.1.0"

__all__ = [
    # Core base class
    "Plugin",
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
    # Field / settings specs
    "ExtensionFieldOption",
    "ExtensionFieldSpec",
    "ActivationFlowSpec",
    "SettingsUIBlockSpec",
    "PluginSettingsResourceSpec",
    "PluginSettingsResourcePayload",
    # Manifest and registry
    "ContributionType",
    "PluginContribution",
    "PluginManifest",
    "PluginPackageState",
    "PluginRegistryEntry",
    "PluginRegistryIndex",
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
    # i18n
    "PluginI18n",
    "DEFAULT_LANGUAGE",
    "LANGUAGE_ALIASES",
    "get_current_language",
    "set_current_language",
    # logging
    "configure_basic_logging",
    "get_logger",
    # Version
    "__version__",
]
