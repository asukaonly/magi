"""Unified plugin runtime exports."""

from .actions import ActionExecutionContext, ActionRegistry, ActionSpec, BaseAction
from .base import Plugin
from .contracts import (
    ContributionType,
    ExtensionFieldOption,
    ExtensionFieldSpec,
    PluginContribution,
    PluginManifest,
    PluginPackageState,
)
from .manager import PluginManager
from .runtime import (
    get_action_registry,
    get_plugin_manager,
    get_sensor_registry,
    initialize_plugin_manager,
    reload_plugin_manager,
)
from .sensors import SensorRegistry, SensorSpec

__all__ = [
    "ActionExecutionContext",
    "ActionRegistry",
    "ActionSpec",
    "BaseAction",
    "ContributionType",
    "ExtensionFieldOption",
    "ExtensionFieldSpec",
    "Plugin",
    "PluginContribution",
    "PluginManifest",
    "PluginManager",
    "PluginPackageState",
    "SensorRegistry",
    "SensorSpec",
    "get_action_registry",
    "get_plugin_manager",
    "get_sensor_registry",
    "initialize_plugin_manager",
    "reload_plugin_manager",
]
