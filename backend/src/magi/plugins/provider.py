"""Container-backed providers for plugin-domain runtime services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..core.container import get_container

if TYPE_CHECKING:
    from .manager import PluginManager
    from .sensors import SensorRegistry


def _require_plugin_binding(provider_name: str) -> Any:
    provider = getattr(get_container(), provider_name)
    instance = provider()
    if instance is None:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    return instance


def resolve_plugin_manager() -> "PluginManager":
    """Return the active plugin manager binding."""
    return cast("PluginManager", _require_plugin_binding("plugin_manager"))


def resolve_sensor_registry() -> "SensorRegistry":
    """Return the active sensor registry binding."""
    return cast("SensorRegistry", _require_plugin_binding("sensor_registry"))
