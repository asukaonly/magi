"""Global plugin runtime helpers."""
from __future__ import annotations

from pathlib import Path

from ..config import get_config
from ..tools.registry import tool_registry
from .actions import ActionRegistry
from .manager import PluginManager
from .sensors import SensorRegistry

_plugin_manager: PluginManager | None = None
_sensor_registry = SensorRegistry()
_action_registry = ActionRegistry()


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


def initialize_plugin_manager(force: bool = False) -> PluginManager:
    """Create and populate the global plugin manager."""

    global _plugin_manager
    if _plugin_manager is not None and not force:
        return _plugin_manager
    manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=_sensor_registry,
        action_registry=_action_registry,
        search_paths=_resolve_search_paths(),
    )
    manager.scan(persist_discovery=True)
    manager.activate_enabled_plugins()
    _plugin_manager = manager
    return manager


def get_plugin_manager() -> PluginManager:
    """Get or lazily initialize the plugin manager."""

    return initialize_plugin_manager(force=False)


def reload_plugin_manager() -> PluginManager:
    """Rebuild the plugin manager from scratch."""

    return initialize_plugin_manager(force=True)


def get_sensor_registry() -> SensorRegistry:
    get_plugin_manager()
    return _sensor_registry


def get_action_registry() -> ActionRegistry:
    get_plugin_manager()
    return _action_registry
