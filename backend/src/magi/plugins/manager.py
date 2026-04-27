"""Unified plugin manager for tool and sensor extensions."""
from __future__ import annotations

import hashlib
import importlib.util
import logging
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from ..config import get_config, save_config
from ..config.models import PluginSettings
from ..awareness.scheduler_contrib import request_sensor_schedule_refresh
from ..tools.registry import ToolRegistry, tool_registry as shared_tool_registry
from ..utils.packaged_paths import get_repo_root
from .base import Plugin
from .contracts import (
    ContributionType,
    PluginContribution,
    PluginManifest,
    PluginPackageState,
    PluginSettingsResourcePayload,
    SummaryProfileSpec,
)
from .sensors import SensorRegistry, SensorSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginRuntimeBindings:
    plugin_manager: "PluginManager"
    sensor_registry: SensorRegistry


@dataclass(frozen=True)
class MergedSummaryProfile:
    """Summary profile after merging plugins that share a ``summary_category``.

    The L3 schedule registers one entry per (category, window). When several
    plugins (e.g. Chrome + Edge browsing history) declare the same category,
    their ``source_types`` and ``intent_verbs`` are unioned and the strictest
    cadence wins.
    """

    summary_category: str
    source_types: tuple[str, ...]
    windows: tuple[str, ...]
    settle_window_seconds: float
    min_events: int
    intent_verbs: tuple[str, ...]
    contributing_profile_ids: tuple[str, ...]
    prompt_hints: dict[str, Any]


def _resolve_search_paths() -> list[Path]:
    config = get_config()
    repo_root = get_repo_root()
    builtin_root = repo_root / "plugins"
    resolved: list[Path] = [builtin_root]
    for raw_path in config.plugins.scan_paths:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (repo_root / raw_path).resolve()
        if path not in resolved:
            resolved.append(path)
    return resolved


def build_plugin_runtime(
    *,
    tool_registry: ToolRegistry | None = None,
    sensor_registry: SensorRegistry | None = None,
) -> PluginRuntimeBindings:
    """Build plugin runtime services for the current runtime instance."""

    resolved_tool_registry = tool_registry or shared_tool_registry
    resolved_sensor_registry = sensor_registry or SensorRegistry()
    plugin_manager = PluginManager(
        tool_registry=resolved_tool_registry,
        sensor_registry=resolved_sensor_registry,
        search_paths=_resolve_search_paths(),
    )
    plugin_manager.scan(persist_discovery=True)
    plugin_manager.activate_enabled_plugins()
    return PluginRuntimeBindings(
        plugin_manager=plugin_manager,
        sensor_registry=resolved_sensor_registry,
    )


class PluginManager:
    """Discovers plugin packages and registers enabled contributions."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        sensor_registry: SensorRegistry,
        search_paths: list[Path],
    ) -> None:
        self._tool_registry = tool_registry
        self._sensor_registry = sensor_registry
        self._search_paths = list(search_paths)
        self._package_states: dict[str, PluginPackageState] = {}
        self._plugin_instances: dict[str, Plugin] = {}
        self._registered_tools: dict[str, list[str]] = {}
        self._registered_sensors: dict[str, list[str]] = {}

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
        request_sensor_schedule_refresh()
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
                        surface=spec.surface if spec.surface in {"extensions", "tools", "timeline"} else "extensions",
                        fields=list(spec.fields),
                        metadata={"domain": spec.domain, **dict(spec.metadata)},
                    )
                )
            self._registered_sensors[plugin_id] = sensor_ids

            channel = plugin_instance.get_channel()
            if channel is not None:
                channel_fields = plugin_instance.get_channel_fields()
                registered_contributions.append(
                    PluginContribution(
                        plugin_id=plugin_id,
                        contribution_id=f"{plugin_id}:channel",
                        contribution_type=ContributionType.CHANNEL,
                        display_name=state.manifest.name,
                        description=state.manifest.description,
                        surface="extensions",
                        fields=list(channel_fields),
                    )
                )

            state.loaded = True
            state.healthy = True
            state.last_error = None
            state.contributions = registered_contributions
            self._plugin_instances[plugin_id] = plugin_instance
            request_sensor_schedule_refresh()
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
        for sensor_id in self._registered_sensors.pop(plugin_id, []):
            self._sensor_registry.unregister(sensor_id)
        self._plugin_instances.pop(plugin_id, None)
        state = self._package_states.get(plugin_id)
        if state is not None:
            state.loaded = False
            state.contributions = self._placeholder_contributions(state.manifest)
        request_sensor_schedule_refresh()

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
        request_sensor_schedule_refresh()
        return state

    def disable_plugin(self, plugin_id: str) -> PluginPackageState:
        """Persist disabled state and unregister plugin contributions."""

        state = self._require_package(plugin_id)
        self.unload_plugin(plugin_id)
        save_config({f"plugins.packages.{plugin_id}.enabled": False})
        self.scan(persist_discovery=False)
        state = self._require_package(plugin_id)
        request_sensor_schedule_refresh()
        return state

    def reload_plugin(self, plugin_id: str) -> PluginPackageState:
        """Reload a single plugin package."""

        state = self._require_package(plugin_id)
        self.unload_plugin(plugin_id)
        if state.enabled:
            state = self.load_plugin(plugin_id)
        request_sensor_schedule_refresh()
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
        request_sensor_schedule_refresh()
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
        source_filter: list[str] | None = None,
    ) -> dict[str, Any]:
        """Collect plugin-provided temporal summary features for the current event window."""

        features_by_source: dict[str, Any] = {}
        events_by_source: dict[str, list[dict[str, Any]]] = {}
        normalized_filter = {str(s).strip() for s in source_filter or [] if str(s).strip()}
        for event in events:
            source_type = str(event.get("source") or "").strip()
            if not source_type:
                continue
            if normalized_filter and source_type not in normalized_filter:
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

    def iter_summary_profiles(self) -> list[SummaryProfileSpec]:
        """Aggregate ``SummaryProfileSpec`` entries from all loaded plugins."""

        profiles: list[SummaryProfileSpec] = []
        seen: set[str] = set()
        for plugin in self.iter_loaded_plugins():
            getter = getattr(plugin, "get_summary_profiles", None)
            if not callable(getter):
                continue
            try:
                items = getter() or []
            except Exception as exc:
                logger.warning(
                    "Plugin get_summary_profiles failed",
                    extra={"plugin_id": plugin.plugin_id, "error": str(exc)},
                )
                continue
            for spec in items:
                if not isinstance(spec, SummaryProfileSpec):
                    continue
                if spec.profile_id in seen:
                    continue
                seen.add(spec.profile_id)
                profiles.append(spec)
        return profiles

    def iter_merged_summary_profiles(self) -> list[MergedSummaryProfile]:
        """Aggregate per-plugin profiles into one entry per ``summary_category``.

        - ``source_types`` and ``intent_verbs`` are unioned across contributors.
        - ``windows`` is the union of declared windows.
        - ``min_events`` takes the maximum (more strict).
        - ``settle_window_seconds`` takes the minimum (faster settling wins).
        - ``prompt_hints`` are shallow-merged (later contributors do not
          overwrite earlier keys; collisions are silently kept from the first).
        """

        merged: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for spec in self.iter_summary_profiles():
            entry = merged.get(spec.summary_category)
            if entry is None:
                entry = {
                    "source_types": list(spec.source_types or []),
                    "windows": list(spec.windows or []),
                    "settle_window_seconds": float(spec.settle_window_seconds),
                    "min_events": int(spec.min_events),
                    "intent_verbs": list(spec.intent_verbs or []),
                    "contributing_profile_ids": [spec.profile_id],
                    "prompt_hints": dict(spec.prompt_hints or {}),
                }
                merged[spec.summary_category] = entry
                order.append(spec.summary_category)
                continue
            for source_type in spec.source_types or []:
                if source_type not in entry["source_types"]:
                    entry["source_types"].append(source_type)
            for window in spec.windows or []:
                if window not in entry["windows"]:
                    entry["windows"].append(window)
            for verb in spec.intent_verbs or []:
                if verb not in entry["intent_verbs"]:
                    entry["intent_verbs"].append(verb)
            entry["min_events"] = max(entry["min_events"], int(spec.min_events))
            entry["settle_window_seconds"] = min(
                entry["settle_window_seconds"], float(spec.settle_window_seconds),
            )
            entry["contributing_profile_ids"].append(spec.profile_id)
            for key, value in (spec.prompt_hints or {}).items():
                entry["prompt_hints"].setdefault(key, value)

        return [
            MergedSummaryProfile(
                summary_category=category,
                source_types=tuple(merged[category]["source_types"]),
                windows=tuple(merged[category]["windows"] or ["day"]),
                settle_window_seconds=merged[category]["settle_window_seconds"],
                min_events=merged[category]["min_events"],
                intent_verbs=tuple(merged[category]["intent_verbs"]),
                contributing_profile_ids=tuple(merged[category]["contributing_profile_ids"]),
                prompt_hints=dict(merged[category]["prompt_hints"]),
            )
            for category in order
        ]

    def build_recall_artifacts(
        self,
        *,
        events: list[dict[str, Any]],
        query: str,
        query_mode: str | None,
    ) -> dict[str, Any]:
        """Collect plugin-provided recall artifacts for the current query window.

        Plugins may optionally expose ``build_recall_artifacts`` and return
        answer-facing enrichment such as ``entity_refs`` or ``asset_refs`` for
        a given ``source_type``. The host runtime treats this as a query-side
        projection hook, not a persistence hook.
        """

        artifacts: dict[str, Any] = {"entity_refs": [], "asset_refs": []}
        events_by_source: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            source_type = str(event.get("source") or "").strip()
            metadata = event.get("metadata_json") if isinstance(event.get("metadata_json"), dict) else {}
            timeline = metadata.get("timeline") if isinstance(metadata.get("timeline"), dict) else {}
            source_type = str(timeline.get("source_type") or source_type).strip()
            if not source_type:
                continue
            events_by_source.setdefault(source_type, []).append(event)

        if not events_by_source:
            return artifacts

        for plugin in self.iter_loaded_plugins():
            builder = getattr(plugin, "build_recall_artifacts", None)
            if not callable(builder):
                continue
            for source_type, source_events in events_by_source.items():
                try:
                    features = builder(
                        source_type=source_type,
                        events=source_events,
                        query=query,
                        query_mode=query_mode,
                    )
                except Exception as exc:
                    logger.warning(
                        "Plugin recall artifact builder failed",
                        extra={"plugin_id": plugin.plugin_id, "source_type": source_type, "error": str(exc)},
                    )
                    continue
                if not isinstance(features, dict):
                    continue
                for key in ("entity_refs", "asset_refs"):
                    value = features.get(key)
                    if isinstance(value, list):
                        artifacts[key].extend(item for item in value if isinstance(item, dict))
        return artifacts

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

        # Add plugin-local .deps/ to sys.path so private dependencies resolve.
        # Appended (not inserted) so host packages take precedence over
        # plugin-bundled copies, avoiding accidental version overrides.
        deps_dir = Path(manifest.plugin_dir) / ".deps"
        if deps_dir.is_dir() and str(deps_dir) not in sys.path:
            sys.path.append(str(deps_dir))

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
        _surface_map = {
            ContributionType.TOOL: "tools",
            ContributionType.SENSOR: "timeline",
            ContributionType.CHANNEL: "extensions",
        }
        return [
            PluginContribution(
                plugin_id=manifest.plugin_id,
                contribution_id=f"{manifest.plugin_id}:{contribution_type.value}",
                contribution_type=contribution_type,
                display_name=manifest.name,
                description=manifest.description,
                surface=_surface_map.get(contribution_type, "extensions"),
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
        return get_repo_root() / "plugins"

    @staticmethod
    def _user_plugins_root() -> Path:
        return Path("~/.magi/plugins").expanduser()

    # ------------------------------------------------------------------
    # Plugin installation / uninstallation
    # ------------------------------------------------------------------

    def install_plugin_from_archive(self, archive_path: Path) -> PluginPackageState:
        """Install a plugin from a .tar.gz or .zip archive.

        The archive must contain a ``plugin.toml`` at the top level or
        inside exactly one subdirectory.  The plugin is extracted into
        ``~/.magi/plugins/<plugin_id>/``.
        """
        user_root = self._user_plugins_root()
        user_root.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="magi-plugin-install-") as tmp:
            tmp_path = Path(tmp)
            self._extract_archive(archive_path, tmp_path)
            manifest_file = self._find_manifest_in_tree(tmp_path)
            if manifest_file is None:
                raise ValueError("Archive does not contain a plugin.toml")
            manifest = self._load_manifest(manifest_file, source="external")
            plugin_id = manifest.plugin_id

            # Prevent overwriting builtin plugins.
            existing = self._package_states.get(plugin_id)
            if existing is not None and existing.manifest.source == "builtin":
                raise ValueError(f"Cannot overwrite builtin plugin: {plugin_id}")

            dest_dir = user_root / plugin_id
            source_dir = manifest_file.parent

            # Remove old installation if present.
            if dest_dir.exists():
                self.unload_plugin(plugin_id)
                shutil.rmtree(dest_dir)

            shutil.copytree(source_dir, dest_dir)

            # Install declared Python dependencies into plugin-local .deps/.
            new_manifest = self._load_manifest(dest_dir / "plugin.toml", source="external")
            if new_manifest.dependencies:
                self._install_dependencies(new_manifest.dependencies, dest_dir)

        self.scan(persist_discovery=True)
        state = self._require_package(plugin_id)
        return state

    def install_plugin_from_directory(self, source_dir: Path) -> PluginPackageState:
        """Install a plugin from a local directory containing a plugin.toml.

        Used by the git-clone registry flow where the plugin source has
        already been extracted into a temporary directory.
        """
        manifest_file = self._find_manifest_in_tree(source_dir)
        if manifest_file is None:
            raise ValueError("Directory does not contain a plugin.toml")
        manifest = self._load_manifest(manifest_file, source="external")
        plugin_id = manifest.plugin_id

        existing = self._package_states.get(plugin_id)
        if existing is not None and existing.manifest.source == "builtin":
            raise ValueError(f"Cannot overwrite builtin plugin: {plugin_id}")

        user_root = self._user_plugins_root()
        user_root.mkdir(parents=True, exist_ok=True)
        dest_dir = user_root / plugin_id
        plugin_source = manifest_file.parent

        if dest_dir.exists():
            self.unload_plugin(plugin_id)
            shutil.rmtree(dest_dir)

        shutil.copytree(plugin_source, dest_dir)

        new_manifest = self._load_manifest(dest_dir / "plugin.toml", source="external")
        if new_manifest.dependencies:
            self._install_dependencies(new_manifest.dependencies, dest_dir)

        self.scan(persist_discovery=True)
        return self.enable_plugin(plugin_id)

    def uninstall_plugin(self, plugin_id: str) -> None:
        """Uninstall a user-installed plugin and remove its files."""
        state = self._require_package(plugin_id)
        if state.manifest.source == "builtin":
            raise ValueError(f"Cannot uninstall builtin plugin: {plugin_id}")

        self.unload_plugin(plugin_id)

        plugin_dir = Path(state.manifest.plugin_dir)
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)

        # Remove persisted config.
        save_config({f"plugins.packages.{plugin_id}": None})
        self._package_states.pop(plugin_id, None)
        request_sensor_schedule_refresh()

    def check_installed_version(self, plugin_id: str) -> str | None:
        """Return the installed version of a plugin, or None if not installed."""
        state = self._package_states.get(plugin_id)
        if state is None:
            return None
        return state.manifest.version

    @staticmethod
    def _extract_archive(archive_path: Path, dest: Path) -> None:
        """Extract a .tar.gz or .zip archive into *dest*."""
        name = archive_path.name.lower()
        if name.endswith(".tar.gz") or name.endswith(".tgz"):
            with tarfile.open(archive_path, "r:gz") as tf:
                # Security: prevent path traversal.
                for member in tf.getmembers():
                    if member.name.startswith("/") or ".." in member.name.split("/"):
                        raise ValueError(f"Unsafe path in archive: {member.name}")
                tf.extractall(dest)
        elif name.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                for info in zf.infolist():
                    if info.filename.startswith("/") or ".." in info.filename.split("/"):
                        raise ValueError(f"Unsafe path in archive: {info.filename}")
                zf.extractall(dest)
        else:
            raise ValueError(f"Unsupported archive format: {archive_path.name}")

    @staticmethod
    def _find_manifest_in_tree(root: Path) -> Path | None:
        """Find plugin.toml at root level or one directory deep."""
        direct = root / "plugin.toml"
        if direct.exists():
            return direct
        for child in root.iterdir():
            if child.is_dir():
                candidate = child / "plugin.toml"
                if candidate.exists():
                    return candidate
        return None

    @staticmethod
    def _install_dependencies(dependencies: list[str], plugin_dir: Path) -> None:
        """Install plugin dependencies into a local .deps/ directory."""
        deps_dir = plugin_dir / ".deps"
        deps_dir.mkdir(exist_ok=True)
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--target",
            str(deps_dir),
            "--no-user",
            "--quiet",
            *dependencies,
        ]
        logger.info("Installing plugin dependencies", extra={"deps": dependencies, "target": str(deps_dir)})
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to install plugin dependencies: {result.stderr.strip()}")
