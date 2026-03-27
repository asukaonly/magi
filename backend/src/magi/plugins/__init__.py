"""Unified plugin runtime exports."""

from .actions import ActionExecutionContext, ActionRegistry, ActionSpec, BaseAction
from .base import Plugin
from .contracts import (
    ActivationFlowSpec,
    ContributionType,
    ExtensionFieldOption,
    ExtensionFieldSpec,
    PluginContribution,
    PluginManifest,
    PluginPackageState,
    PluginSettingsResourcePayload,
    PluginSettingsResourceSpec,
    SettingsUIBlockSpec,
)
from .manager import PluginManager
from .sensors import SensorRegistry, SensorSpec

__all__ = [
    "ActionExecutionContext",
    "ActionRegistry",
    "ActionSpec",
    "ActivationFlowSpec",
    "BaseAction",
    "ContributionType",
    "ExtensionFieldOption",
    "ExtensionFieldSpec",
    "Plugin",
    "PluginContribution",
    "PluginManifest",
    "PluginManager",
    "PluginPackageState",
    "PluginSettingsResourcePayload",
    "PluginSettingsResourceSpec",
    "SensorRegistry",
    "SensorSpec",
    "SettingsUIBlockSpec",
]
