"""Plugin contracts - re-exported from magi-plugin-sdk.

Internal backend code continues to import from this module.  External
plugin authors should install ``magi-plugin-sdk`` and import directly
from ``magi_plugin_sdk`` instead.
"""
from magi_plugin_sdk.contracts import (  # noqa: F401
    ActivationFlowSpec,
    ActivationFirstContextSpec,
    ContributionType,
    ExtractionProfileSpec,
    ExtensionFieldOption,
    ExtensionFieldSpec,
    PluginCapability,
    PluginContribution,
    PluginDisplayGroupSpec,
    PluginManifest,
    PluginPackageState,
    PluginPermissions,
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
