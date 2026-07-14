"""Unified plugin runtime exports.

Public API for both internal backend code and plugin authors.
All contract types originate from ``magi-plugin-sdk``.
"""

from magi_plugin_sdk import (  # noqa: F401
    ActivationFlowSpec,
    ActivationFirstContextSpec,
    ContributionType,
    ExtractionProfileSpec,
    ExtensionFieldOption,
    ExtensionFieldSpec,
    Plugin,
    PluginContribution,
    PluginDisplayGroupSpec,
    PluginI18n,
    PluginManifest,
    PluginPackageState,
    PluginRegistryEntry,
    PluginRegistryIndex,
    PluginSettingsActionResult,
    PluginSettingsActionSpec,
    PluginSettingsResourcePayload,
    PluginSettingsResourceSpec,
    SensorSpec,
    SettingsUIBlockSpec,
    SuggestionSurfaceSpec,
    SuggestionSurfacesSpec,
    configure_basic_logging,
    get_logger,
)
from .manager import PluginManager
from .projections import PluginProjectionService
from .sensors import SensorRegistry

__all__ = [
    "ActivationFlowSpec",
    "ActivationFirstContextSpec",
    "ContributionType",
    "ExtractionProfileSpec",
    "ExtensionFieldOption",
    "ExtensionFieldSpec",
    "Plugin",
    "PluginContribution",
    "PluginDisplayGroupSpec",
    "PluginI18n",
    "PluginManifest",
    "PluginManager",
    "PluginPackageState",
    "PluginProjectionService",
    "PluginRegistryEntry",
    "PluginRegistryIndex",
    "PluginSettingsActionResult",
    "PluginSettingsActionSpec",
    "PluginSettingsResourcePayload",
    "PluginSettingsResourceSpec",
    "SensorRegistry",
    "SensorSpec",
    "SettingsUIBlockSpec",
    "SuggestionSurfaceSpec",
    "SuggestionSurfacesSpec",
    "configure_basic_logging",
    "get_logger",
]
