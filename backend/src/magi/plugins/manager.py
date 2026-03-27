"""Unified plugin manager for tool, sensor, and action extensions."""
from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from ..config import get_config, save_config
from ..config.models import PluginSettings
from ..timeline.scheduler_contrib import request_timeline_schedule_refresh
from ..tools.registry import ToolRegistry, tool_registry as shared_tool_registry
from .actions import ActionRegistry, BaseAction, build_action_tool_class
from .base import Plugin
from .contracts import (
    ContributionType,
    PluginContribution,
    PluginManifest,
    PluginPackageState,
    PluginSettingsResourcePayload,
)
from .sensors import SensorRegistry, SensorSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginRuntimeBindings:
    plugin_manager: "PluginManager"
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
    tool_registry: ToolRegistry | None = None,
    sensor_registry: SensorRegistry | None = None,
    action_registry: ActionRegistry | None = None,
) -> PluginRuntimeBindings:
    """Build plugin runtime services for the current runtime instance."""

    resolved_tool_registry = tool_registry or shared_tool_registry
    resolved_sensor_registry = sensor_registry or SensorRegistry()
    resolved_action_registry = action_registry or ActionRegistry()
    plugin_manager = PluginManager(
        tool_registry=resolved_tool_registry,
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

    def rescan_runtime(self, *, persist_discovery: bool = True) -> list[PluginPackageState]:
        """Rescan plugin manifests and reload enabled plugins in the current runtime."""

        for plugin_id in list(self._plugin_instances.keys()):
            self.unload_plugin(plugin_id)
        self.scan(persist_discovery=persist_discovery)
        self.activate_enabled_plugins()
        request_timeline_schedule_refresh()
        return self.list_packages()

    def list_packages(self) -> list[PluginPackageState]:
        return sorted(self._package_states.values(), key=lambda item: item.manifest.plugin_id)

    def get_package(self, plugin_id: str) -> Optional[PluginPackageState]:
        return self._package_states.get(plugin_id)

    def iter_loaded_plugins(self) -> list[Plugin]:
        """Return currently loaded plugin instances."""
        return list(self._plugin_instances.values())

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
                bind_plugin_context = getattr(sensor, "bind_plugin_context", None)
                if callable(bind_plugin_context):
                    bind_plugin_context(plugin_id=plugin_id, plugin_dir=state.manifest.plugin_dir)
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
            request_timeline_schedule_refresh()
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
        request_timeline_schedule_refresh()

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
        request_timeline_schedule_refresh()
        return state

    def disable_plugin(self, plugin_id: str) -> PluginPackageState:
        """Persist disabled state and unregister plugin contributions."""

        state = self._require_package(plugin_id)
        self.unload_plugin(plugin_id)
        save_config({f"plugins.packages.{plugin_id}.enabled": False})
        self.scan(persist_discovery=False)
        state = self._require_package(plugin_id)
        request_timeline_schedule_refresh()
        return state

    def reload_plugin(self, plugin_id: str) -> PluginPackageState:
        """Reload a single plugin package."""

        state = self._require_package(plugin_id)
        self.unload_plugin(plugin_id)
        if state.enabled:
            state = self.load_plugin(plugin_id)
        request_timeline_schedule_refresh()
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
        request_timeline_schedule_refresh()
        return state

    def read_plugin_settings_resource(self, plugin_id: str, resource_name: str) -> PluginSettingsResourcePayload:
        """Read a plugin-owned settings resource through the loaded plugin instance."""

        state = self._require_package(plugin_id)
        if not state.loaded:
            if not state.enabled:
                raise RuntimeError(f"Plugin {plugin_id} must be enabled before reading settings resources")
            state = self.load_plugin(plugin_id)

        plugin_instance = self._plugin_instances.get(plugin_id)
        if plugin_instance is None:
            raise RuntimeError(f"Plugin {plugin_id} is not loaded")

        resource_specs = {
            spec.resource_name: spec
            for spec in plugin_instance.get_settings_resources()
        }
        spec = resource_specs.get(resource_name)
        if spec is None:
            raise KeyError(resource_name)

        return PluginSettingsResourcePayload(
            plugin_id=plugin_id,
            resource_name=resource_name,
            resource_type=spec.resource_type,
            data=plugin_instance.read_settings_resource(resource_name),
        )

    def build_temporal_summary_features(
        self,
        *,
        events: list[dict[str, Any]],
        summary_category: str,
        period_start: float,
        period_end: float,
    ) -> dict[str, Any]:
        """Collect plugin-provided temporal summary features for the current event window."""

        features_by_source: dict[str, Any] = {}
        events_by_source: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            source_type = str(event.get("source") or "").strip()
            if not source_type:
                continue
            events_by_source.setdefault(source_type, []).append(event)

        if not events_by_source:
            return features_by_source

        for plugin in self.iter_loaded_plugins():
            for source_type, source_events in events_by_source.items():
                if source_type in features_by_source:
                    continue
                try:
                    features = plugin.build_temporal_summary_features(
                        source_type=source_type,
                        events=source_events,
                        summary_category=summary_category,
                        period_start=period_start,
                        period_end=period_end,
                    )
                except Exception as exc:
                    logger.warning(
                        "Plugin temporal summary feature builder failed",
                        extra={"plugin_id": plugin.plugin_id, "source_type": source_type, "error": str(exc)},
                    )
                    continue
                if features:
                    features_by_source[source_type] = features
        return features_by_source

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
            submodule_search_locations=[str(Path(manifest.plugin_dir))],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load plugin module for {manifest.plugin_id}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
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
