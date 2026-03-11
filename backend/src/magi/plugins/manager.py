"""Unified plugin manager for tool, sensor, and action extensions."""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any, Optional

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from ..config import get_config, save_config
from ..config.models import PluginSettings
from ..scheduler.runtime import request_scheduler_refresh
from ..tools.registry import ToolRegistry
from .actions import ActionRegistry, BaseAction, build_action_tool_class
from .base import Plugin
from .contracts import ContributionType, PluginContribution, PluginManifest, PluginPackageState
from .sensors import SensorRegistry, SensorSpec

logger = logging.getLogger(__name__)


class PluginManager:
    """Discovers plugin packages and registers enabled contributions."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        sensor_registry: SensorRegistry,
        action_registry: ActionRegistry,
        search_paths: list[Path],
    ) -> None:
        self._tool_registry = tool_registry
        self._sensor_registry = sensor_registry
        self._action_registry = action_registry
        self._search_paths = list(search_paths)
        self._package_states: dict[str, PluginPackageState] = {}
        self._plugin_instances: dict[str, Plugin] = {}
        self._registered_tools: dict[str, list[str]] = {}
        self._registered_sensors: dict[str, list[str]] = {}
        self._registered_actions: dict[str, list[str]] = {}
        self._registered_action_tools: dict[str, list[str]] = {}

    @property
    def search_paths(self) -> list[Path]:
        return list(self._search_paths)

    def scan(self, *, persist_discovery: bool = True) -> list[PluginPackageState]:
        """Discover plugin manifests in configured scan paths."""

        config = get_config()
        discovered: dict[str, PluginManifest] = {}
        for root in self._search_paths:
            if not root.exists():
                continue
            source = "builtin" if self._is_builtin_root(root) else "external"
            for manifest_path in root.rglob("plugin.toml"):
                manifest = self._load_manifest(manifest_path, source=source)
                discovered[manifest.plugin_id] = manifest

        if persist_discovery:
            self._persist_new_packages(discovered)
            config = get_config()

        next_states: dict[str, PluginPackageState] = {}
        for plugin_id, manifest in discovered.items():
            package_cfg = self._coerce_package_settings(config.plugins.packages.get(plugin_id))
            enabled = bool(package_cfg.enabled) if package_cfg is not None else False
            trusted = bool(package_cfg.trusted) if package_cfg is not None else False
            current_settings = dict(package_cfg.settings) if package_cfg is not None else {}
            previous_state = self._package_states.get(plugin_id)
            next_states[plugin_id] = PluginPackageState(
                manifest=manifest,
                enabled=enabled,
                trusted=trusted,
                loaded=bool(previous_state.loaded) if previous_state is not None else False,
                healthy=bool(previous_state.healthy) if previous_state is not None else True,
                last_error=previous_state.last_error if previous_state is not None else None,
                contributions=list(previous_state.contributions) if previous_state is not None else self._placeholder_contributions(manifest),
                current_settings=current_settings,
            )
        self._package_states = next_states
        return self.list_packages()

    def activate_enabled_plugins(self) -> None:
        """Load every enabled and trusted plugin package."""

        for state in self.list_packages():
            if state.enabled:
                self.load_plugin(state.manifest.plugin_id)

    def list_packages(self) -> list[PluginPackageState]:
        return sorted(self._package_states.values(), key=lambda item: item.manifest.plugin_id)

    def get_package(self, plugin_id: str) -> Optional[PluginPackageState]:
        return self._package_states.get(plugin_id)

    def load_plugin(self, plugin_id: str) -> PluginPackageState:
        """Load a plugin and register all of its contributions."""

        state = self._require_package(plugin_id)
        if state.loaded:
            return state
        if not state.trusted and state.manifest.source != "builtin":
            raise RuntimeError(f"Plugin {plugin_id} must be trusted before loading")

        plugin_instance = self._instantiate_plugin(state.manifest, state.current_settings)
        registered_contributions: list[PluginContribution] = []
        try:
            tool_names: list[str] = []
            for tool_class in plugin_instance.get_tools():
                tool_instance = tool_class()
                tool_name = tool_instance.get_schema().name
                setattr(tool_class, "_plugin_package_id", plugin_id)
                self._tool_registry.register(tool_class)
                tool_names.append(tool_name)
                registered_contributions.append(
                    PluginContribution(
                        plugin_id=plugin_id,
                        contribution_id=tool_name,
                        contribution_type=ContributionType.TOOL,
                        display_name=tool_instance.get_schema().name,
                        description=tool_instance.get_schema().description,
                        surface="tools",
                    )
                )
            self._registered_tools[plugin_id] = tool_names

            sensor_ids: list[str] = []
            for sensor_id, sensor, spec in plugin_instance.get_sensors():
                self._sensor_registry.register(plugin_id, sensor_id, sensor, spec)
                sensor_ids.append(sensor_id)
                registered_contributions.append(
                    PluginContribution(
                        plugin_id=plugin_id,
                        contribution_id=sensor_id,
                        contribution_type=ContributionType.SENSOR,
                        display_name=spec.display_name,
                        description=spec.description,
                        surface=spec.surface if spec.surface in {"extensions", "tools", "timeline", "actions"} else "extensions",
                        fields=list(spec.fields),
                        metadata={"domain": spec.domain, **dict(spec.metadata)},
                    )
                )
            self._registered_sensors[plugin_id] = sensor_ids

            action_ids: list[str] = []
            action_tool_names: list[str] = []
            for action in plugin_instance.get_actions():
                if not isinstance(action, BaseAction):
                    continue
                self._action_registry.register(plugin_id, action)
                action_ids.append(action.spec.action_id)
                tool_class = build_action_tool_class(action)
                if tool_class is not None:
                    tool_instance = tool_class()
                    tool_name = tool_instance.get_schema().name
                    setattr(tool_class, "_plugin_package_id", plugin_id)
                    self._tool_registry.register(tool_class)
                    action_tool_names.append(tool_name)
            self._registered_actions[plugin_id] = action_ids
            self._registered_action_tools[plugin_id] = action_tool_names
            registered_contributions.extend(self._action_registry.list_contributions(plugin_id))

            state.loaded = True
            state.healthy = True
            state.last_error = None
            state.contributions = registered_contributions
            self._plugin_instances[plugin_id] = plugin_instance
            request_scheduler_refresh()
            return state
        except Exception as exc:
            state.loaded = False
            state.healthy = False
            state.last_error = str(exc)
            self.unload_plugin(plugin_id)
            raise

    def unload_plugin(self, plugin_id: str) -> None:
        """Unload a plugin and unregister its contributions."""

        for tool_name in self._registered_tools.pop(plugin_id, []):
            self._tool_registry.unregister(tool_name)
        for tool_name in self._registered_action_tools.pop(plugin_id, []):
            self._tool_registry.unregister(tool_name)
        for sensor_id in self._registered_sensors.pop(plugin_id, []):
            self._sensor_registry.unregister(sensor_id)
        for action_id in self._registered_actions.pop(plugin_id, []):
            self._action_registry.unregister(action_id)
        self._plugin_instances.pop(plugin_id, None)
        state = self._package_states.get(plugin_id)
        if state is not None:
            state.loaded = False
            state.contributions = self._placeholder_contributions(state.manifest)
        request_scheduler_refresh()

    def enable_plugin(self, plugin_id: str) -> PluginPackageState:
        """Persist enable/trust state and load the plugin."""

        state = self._require_package(plugin_id)
        save_config(
            {
                f"plugins.packages.{plugin_id}.enabled": True,
                f"plugins.packages.{plugin_id}.trusted": True,
                f"plugins.packages.{plugin_id}.source": state.manifest.source,
                f"plugins.packages.{plugin_id}.manifest_path": state.manifest.manifest_path,
            }
        )
        self.scan(persist_discovery=False)
        state = self.load_plugin(plugin_id)
        request_scheduler_refresh()
        return state

    def disable_plugin(self, plugin_id: str) -> PluginPackageState:
        """Persist disabled state and unregister plugin contributions."""

        state = self._require_package(plugin_id)
        self.unload_plugin(plugin_id)
        save_config({f"plugins.packages.{plugin_id}.enabled": False})
        self.scan(persist_discovery=False)
        state = self._require_package(plugin_id)
        request_scheduler_refresh()
        return state

    def reload_plugin(self, plugin_id: str) -> PluginPackageState:
        """Reload a single plugin package."""

        state = self._require_package(plugin_id)
        self.unload_plugin(plugin_id)
        if state.enabled:
            state = self.load_plugin(plugin_id)
        request_scheduler_refresh()
        return state

    def update_plugin_settings(self, plugin_id: str, updates: dict[str, Any]) -> PluginPackageState:
        """Persist plugin settings using dot-notated keys relative to plugin settings root."""

        self._require_package(plugin_id)
        save_payload = {
            f"plugins.packages.{plugin_id}.settings.{path}": value
            for path, value in updates.items()
        }
        if save_payload:
            save_config(save_payload)
        self.scan(persist_discovery=False)
        state = self._require_package(plugin_id)
        if state.enabled:
            state = self.reload_plugin(plugin_id)
        request_scheduler_refresh()
        return state

    def _persist_new_packages(self, manifests: dict[str, PluginManifest]) -> None:
        config = get_config()
        updates: dict[str, Any] = {}
        for plugin_id, manifest in manifests.items():
            if plugin_id in config.plugins.packages:
                continue
            enabled = bool(manifest.official and manifest.source == "builtin")
            trusted = enabled
            updates[f"plugins.packages.{plugin_id}.enabled"] = enabled
            updates[f"plugins.packages.{plugin_id}.trusted"] = trusted
            updates[f"plugins.packages.{plugin_id}.source"] = manifest.source
            updates[f"plugins.packages.{plugin_id}.manifest_path"] = manifest.manifest_path
            updates[f"plugins.packages.{plugin_id}.settings"] = {}
        if updates:
            save_config(updates)

    def _load_manifest(self, manifest_path: Path, *, source: str) -> PluginManifest:
        with manifest_path.open("rb") as fp:
            raw = tomllib.load(fp)
        plugin_block = raw.get("plugin", raw)
        manifest = PluginManifest.model_validate(
            {
                **plugin_block,
                "plugin_dir": str(manifest_path.parent),
                "manifest_path": str(manifest_path),
                "source": source,
            }
        )
        return manifest

    def _instantiate_plugin(self, manifest: PluginManifest, settings: dict[str, Any]) -> Plugin:
        module_path = Path(manifest.plugin_dir) / f"{manifest.entry_module}.py"
        spec = importlib.util.spec_from_file_location(
            f"magi_plugin_{manifest.plugin_id.replace('-', '_')}",
            module_path,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load plugin module for {manifest.plugin_id}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        plugin_class = getattr(module, manifest.entry_class)
        plugin_instance = plugin_class()
        if not isinstance(plugin_instance, Plugin):
            raise TypeError(f"Plugin entrypoint {manifest.entry_class} must inherit Plugin")
        plugin_instance.configure(manifest=manifest, settings=settings)
        return plugin_instance

    def _placeholder_contributions(self, manifest: PluginManifest) -> list[PluginContribution]:
        return [
            PluginContribution(
                plugin_id=manifest.plugin_id,
                contribution_id=f"{manifest.plugin_id}:{contribution_type.value}",
                contribution_type=contribution_type,
                display_name=manifest.name,
                description=manifest.description,
                surface={
                    ContributionType.TOOL: "tools",
                    ContributionType.SENSOR: "timeline",
                    ContributionType.ACTION: "actions",
                }[contribution_type],
            )
            for contribution_type in manifest.contribution_types
        ]

    def _require_package(self, plugin_id: str) -> PluginPackageState:
        state = self._package_states.get(plugin_id)
        if state is None:
            raise KeyError(f"Unknown plugin package: {plugin_id}")
        return state

    @staticmethod
    def _coerce_package_settings(value: Any) -> PluginSettings | None:
        if value is None:
            return None
        if isinstance(value, PluginSettings):
            return value
        if isinstance(value, dict):
            return PluginSettings.model_validate(value)
        return None

    def _is_builtin_root(self, path: Path) -> bool:
        return path == self._default_builtin_root()

    @staticmethod
    def _default_builtin_root() -> Path:
        return Path(__file__).resolve().parents[4] / "plugins"
