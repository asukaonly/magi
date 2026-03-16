"""Plugin runtime construction and binding helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dependency_injector import providers

from ..config import get_config
from ..core.container import get_container
from ..tools.registry import tool_registry
from .actions import ActionRegistry
from .manager import PluginManager
from .sensors import SensorRegistry


@dataclass(frozen=True)
class PluginRuntimeBindings:
    plugin_manager: PluginManager
    sensor_registry: SensorRegistry
    action_registry: ActionRegistry


def _resolve_search_paths() -> list[Path]:
    config = get_config()
    builtin_root = Path(__file__).resolve().parents[4] / "plugins"
    resolved: list[Path] = [builtin_root]
    for raw_path in config.plugins.scan_paths:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (Path(__file__).resolve().parents[4] / raw_path).resolve()
        if path not in resolved:
            resolved.append(path)
    return resolved


def build_plugin_runtime(
    *,
    sensor_registry: SensorRegistry | None = None,
    action_registry: ActionRegistry | None = None,
) -> PluginRuntimeBindings:
    """Build plugin runtime services without module-level globals."""

    resolved_sensor_registry = sensor_registry or SensorRegistry()
    resolved_action_registry = action_registry or ActionRegistry()
    plugin_manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=resolved_sensor_registry,
        action_registry=resolved_action_registry,
        search_paths=_resolve_search_paths(),
    )
    plugin_manager.scan(persist_discovery=True)
    plugin_manager.activate_enabled_plugins()
    return PluginRuntimeBindings(
        plugin_manager=plugin_manager,
        sensor_registry=resolved_sensor_registry,
        action_registry=resolved_action_registry,
    )


def rebuild_plugin_manager_binding() -> PluginManager:
    """Rebuild the runtime plugin manager while preserving active registries."""

    container = get_container()

    sensor_registry = None
    action_registry = None
    try:
        current_sensor_registry = container.sensor_registry()
        if current_sensor_registry is not None and type(current_sensor_registry).__name__ != "object":
            sensor_registry = current_sensor_registry
    except Exception:
        sensor_registry = None

    try:
        current_action_registry = container.action_registry()
        if current_action_registry is not None and type(current_action_registry).__name__ != "object":
            action_registry = current_action_registry
    except Exception:
        action_registry = None

    bindings = build_plugin_runtime(
        sensor_registry=sensor_registry,
        action_registry=action_registry,
    )

    container.plugin_manager.reset_override()
    container.plugin_manager.override(providers.Object(bindings.plugin_manager))
    container.sensor_registry.reset_override()
    container.sensor_registry.override(providers.Object(bindings.sensor_registry))
    container.action_registry.reset_override()
    container.action_registry.override(providers.Object(bindings.action_registry))

    try:
        context = container.runtime_bootstrap_context()
        if context is not None and type(context).__name__ != "object":
            context.plugins.plugin_manager = bindings.plugin_manager
            context.plugins.sensor_registry = bindings.sensor_registry
            context.plugins.action_registry = bindings.action_registry
    except Exception:
        pass

    return bindings.plugin_manager


def ensure_plugin_manager_binding() -> PluginManager:
    """Return the active plugin manager binding, rebuilding it when absent."""

    container = get_container()
    try:
        current_manager = container.plugin_manager()
        if current_manager is not None and type(current_manager).__name__ != "object":
            return current_manager
    except Exception:
        pass

    return rebuild_plugin_manager_binding()
