"""Bootstrap builder for assembling lifecycle modules from owning layers."""

from __future__ import annotations

from .context import RuntimeBootstrapContext
from .lifecycle import LifecycleModule

from ..core.lifecycle import CoreDependenciesModule
from ..config.lifecycle import ConfigurationModule
from ..events.lifecycle import MessageBusModule
from ..plugins.lifecycle import PluginSystemModule


def build_runtime_modules(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    """Build ordered runtime lifecycle modules from layer-owned contributions.

    Order aligns with the layered architecture:
    L1  CoreDependenciesModule    - Application-level infrastructure
    L2  ConfigurationModule       - Configuration loading
    L3  MessageBusModule          - Message bus
    L4  PluginSystemModule        - Plugin system
    L5+ ...                       - Additional layers added incrementally

    Args:
        context: The shared bootstrap context containing layer state slices

    Returns:
        Ordered list of lifecycle modules ready for orchestration
    """
    return [
        CoreDependenciesModule(context),      # L1
        ConfigurationModule(context),         # L2
        MessageBusModule(context),            # L3
        PluginSystemModule(context),          # L4
    ]
