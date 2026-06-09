"""Unified plugin manager for tool and sensor extensions."""
from __future__ import annotations

import asyncio
import hashlib
import importlib
import inspect
import importlib.util
import logging
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from ..config import get_config, save_config
from ..config.models import PluginSettings
from ..utils.packaged_paths import get_repo_root
from .base import Plugin
from .contracts import (
    ContributionType,
    PluginContribution,
    PluginManifest,
    PluginPackageState,
    PluginSettingsActionResult,
    PluginSettingsActionSpec,
    PluginSettingsResourcePayload,
)
from .installation import PluginInstallationMixin
from .projections import MergedSummaryProfile, PluginProjectionMixin
from .sensors import SensorRegistry, SensorSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginRuntimeBindings:
    plugin_manager: "PluginManager"
    sensor_registry: SensorRegistry


@dataclass(frozen=True)
class PluginSettingsActionRun:
    """Host-owned envelope for one plugin settings action session response."""

    session_id: str
    result: PluginSettingsActionResult


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
    tool_registry: Any,
    request_sensor_schedule_refresh: Callable[[], None],
    sensor_registry: SensorRegistry | None = None,
) -> PluginRuntimeBindings:
    """Build plugin runtime services for the current runtime instance.

    ``tool_registry`` (the shared L9 tool registry) and the
    ``request_sensor_schedule_refresh`` callable (an L8 awareness hook) are
    injected by the composition root so this L4 plugins module does not import
    the higher tools / awareness layers.
    """

    resolved_sensor_registry = sensor_registry or SensorRegistry()
    plugin_manager = PluginManager(
        tool_registry=tool_registry,
        sensor_registry=resolved_sensor_registry,
        search_paths=_resolve_search_paths(),
        request_sensor_schedule_refresh=request_sensor_schedule_refresh,
    )
    plugin_manager.scan(persist_discovery=True)
    plugin_manager.activate_enabled_plugins()
    return PluginRuntimeBindings(
        plugin_manager=plugin_manager,
        sensor_registry=resolved_sensor_registry,
    )


class PluginManager(PluginInstallationMixin, PluginProjectionMixin):
    """Discovers plugin packages and registers enabled contributions."""

    def __init__(
        self,
        *,
        tool_registry: Any,
        sensor_registry: SensorRegistry,
        search_paths: list[Path],
        request_sensor_schedule_refresh: Callable[[], None],
    ) -> None:
        self._tool_registry = tool_registry
        self._sensor_registry = sensor_registry
        self._search_paths = list(search_paths)
        self._request_sensor_schedule_refresh = request_sensor_schedule_refresh
        self._package_states: dict[str, PluginPackageState] = {}
        self._plugin_instances: dict[str, Plugin] = {}
        self._registered_tools: dict[str, list[str]] = {}
        self._registered_sensors: dict[str, list[str]] = {}
        self._registered_hooks: dict[str, list[tuple[Any, Any]]] = {}
        # Tasks spawned by unload_plugin to run plugins' shutdown coroutines.
        # We hold strong refs so they're not GC'd while pending; entries
        # remove themselves via a done callback.
        self._pending_plugin_shutdowns: set[asyncio.Task] = set()

    @property
    def search_paths(self) -> list[Path]:
        return list(self._search_paths)

    @staticmethod
    def _module_name_prefix(plugin_id: str) -> str:
        return f"magi_plugin_{plugin_id.replace('-', '_')}"

    def _purge_plugin_modules(self, plugin_id: str) -> None:
        prefix = self._module_name_prefix(plugin_id)
        stale_module_names = [
            module_name
            for module_name in list(sys.modules)
            if module_name == prefix or module_name.startswith(f"{prefix}.")
        ]
        for module_name in stale_module_names:
            sys.modules.pop(module_name, None)
        importlib.invalidate_caches()

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
        """Load every enabled plugin package.

        Each plugin's load is wrapped in try/except so that one broken plugin
        (e.g. a missing Python dep) cannot crash the runtime startup. Failed
        plugins are left with ``healthy=False`` and a non-empty ``last_error``;
        the user can disable or repair them via the UI. Library packages
        (``kind == "library"``) ship Python modules consumed by other plugins
        and have no :class:`Plugin` instance to instantiate, so we just mark
        them loaded once they exist on disk.
        """

        for state in self.list_packages():
            if not state.enabled:
                continue
            if state.manifest.kind == "library":
                # Libraries are "loaded" just by being present on disk; their
                # code gets onto sys.path via _instantiate_plugin when a
                # consumer plugin loads.
                state.loaded = True
                state.healthy = True
                state.last_error = None
                continue
            try:
                self.load_plugin(state.manifest.plugin_id)
            except Exception as exc:
                # load_plugin already recorded last_error / healthy=False
                # on the state and called unload_plugin to clean up partial
                # registrations. Log and continue so other plugins still
                # come up.
                logger.warning(
                    "plugin.load_failed_during_startup plugin_id=%s error=%s",
                    state.manifest.plugin_id,
                    exc,
                )

    def rescan_runtime(self, *, persist_discovery: bool = True) -> list[PluginPackageState]:
        """Rescan plugin manifests and reload enabled plugins in the current runtime."""

        for plugin_id in list(self._plugin_instances.keys()):
            self.unload_plugin(plugin_id)
        self.scan(persist_discovery=persist_discovery)
        self.activate_enabled_plugins()
        self._request_sensor_schedule_refresh()
        return self.list_packages()

    def list_packages(self) -> list[PluginPackageState]:
        return sorted(self._package_states.values(), key=lambda item: item.manifest.plugin_id)

    def get_package(self, plugin_id: str) -> Optional[PluginPackageState]:
        return self._package_states.get(plugin_id)

    def iter_loaded_plugins(self) -> list[Plugin]:
        """Return currently loaded plugin instances."""
        return list(self._plugin_instances.values())

    def load_plugin(self, plugin_id: str) -> PluginPackageState:
        """Load a plugin and register all of its contributions.

        Library packages (``kind == "library"``) are not instantiated — they
        only ship Python modules consumed by other plugins. We mark them as
        loaded once their directory is present on disk.
        """

        state = self._require_package(plugin_id)
        if state.loaded:
            return state
        if not state.trusted and state.manifest.source != "builtin":
            raise RuntimeError(f"Plugin {plugin_id} must be trusted before loading")

        if state.manifest.kind == "library":
            state.loaded = True
            state.healthy = True
            state.last_error = None
            return state

        self._purge_plugin_modules(plugin_id)
        registered_contributions: list[PluginContribution] = []
        try:
            # _instantiate_plugin can raise (missing dep, syntax error in
            # plugin code, etc.). Keep it inside the try so any failure
            # marks the state unhealthy with a clear last_error — without
            # this guard, import-time errors would bypass error recording
            # entirely and propagate as a bare exception.
            plugin_instance = self._instantiate_plugin(state.manifest, state.current_settings)
            settings_actions = self._collect_settings_actions(plugin_instance)
            tool_names: list[str] = []
            for tool_class in plugin_instance.get_tools():
                tool_instance = tool_class()
                tool_name = tool_instance.get_schema().name
                setattr(tool_class, "_plugin_package_id", plugin_id)
                self._tool_registry.register(tool_class)
                tool_names.append(tool_name)
                tool_action_metadata = self._settings_actions_for_contribution(
                    settings_actions,
                    contribution_id=tool_name,
                    contribution_type=ContributionType.TOOL,
                    surface="tools",
                )
                registered_contributions.append(
                    PluginContribution(
                        plugin_id=plugin_id,
                        contribution_id=tool_name,
                        contribution_type=ContributionType.TOOL,
                        display_name=tool_instance.get_schema().name,
                        description=tool_instance.get_schema().description,
                        surface="tools",
                        metadata={"settings_actions": tool_action_metadata} if tool_action_metadata else {},
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
                sensor_metadata = {"domain": spec.domain, **dict(spec.metadata)}
                sensor_action_metadata = self._settings_actions_for_contribution(
                    settings_actions,
                    contribution_id=sensor_id,
                    contribution_type=ContributionType.SENSOR,
                    surface=spec.surface if spec.surface in {"extensions", "tools", "timeline"} else "extensions",
                )
                if sensor_action_metadata:
                    sensor_metadata["settings_actions"] = sensor_action_metadata
                registered_contributions.append(
                    PluginContribution(
                        plugin_id=plugin_id,
                        contribution_id=sensor_id,
                        contribution_type=ContributionType.SENSOR,
                        display_name=spec.display_name,
                        description=spec.description,
                        surface=spec.surface if spec.surface in {"extensions", "tools", "timeline"} else "extensions",
                        fields=list(spec.fields),
                        metadata=sensor_metadata,
                    )
                )
            self._registered_sensors[plugin_id] = sensor_ids

            channel = plugin_instance.get_channel()
            if channel is not None:
                channel_fields = plugin_instance.get_channel_fields()
                channel_contribution_id = f"{plugin_id}:channel"
                channel_action_metadata = self._settings_actions_for_contribution(
                    settings_actions,
                    contribution_id=channel_contribution_id,
                    contribution_type=ContributionType.CHANNEL,
                    surface="extensions",
                )
                registered_contributions.append(
                    PluginContribution(
                        plugin_id=plugin_id,
                        contribution_id=channel_contribution_id,
                        contribution_type=ContributionType.CHANNEL,
                        display_name=state.manifest.name,
                        description=state.manifest.description,
                        surface="extensions",
                        fields=list(channel_fields),
                        metadata={"settings_actions": channel_action_metadata} if channel_action_metadata else {},
                    )
                )

            # Phase 4: optional hook contributions. Defensively wrapped — a plugin
            # without get_hooks() (older SDK) simply contributes nothing.
            hook_ids: list[tuple[str, Any]] = []
            try:
                hook_specs = list(plugin_instance.get_hooks() or [])
            except AttributeError:
                hook_specs = []
            except Exception:
                hook_specs = []
            if hook_specs:
                self._register_plugin_hooks(plugin_id, hook_specs, registered_contributions)

            state.loaded = True
            state.healthy = True
            state.last_error = None
            state.contributions = registered_contributions
            self._plugin_instances[plugin_id] = plugin_instance
            self._request_sensor_schedule_refresh()
            return state
        except Exception as exc:
            state.loaded = False
            state.healthy = False
            state.last_error = str(exc)
            self.unload_plugin(plugin_id)
            raise

    def _resolve_hook_registry(self):
        """Best-effort resolve of the shared HookRegistry."""
        try:
            from ..core.container import get_container

            registry = get_container().hook_registry()
        except Exception:
            return None
        if registry is None or type(registry).__name__ == "object":
            return None
        return registry

    def _register_plugin_hooks(
        self,
        plugin_id: str,
        hook_specs: list[tuple[Any, ...]],
        registered_contributions: list[PluginContribution],
    ) -> None:
        registry = self._resolve_hook_registry()
        if registry is None:
            return
        try:
            from ..hooks.contracts import HookEventType
        except Exception:
            return

        recorded: list[tuple[Any, Any]] = []
        for raw_index, spec in enumerate(hook_specs):
            if not isinstance(spec, tuple) or len(spec) < 2:
                continue
            event_value = spec[0]
            handler = spec[1]
            matcher = spec[2] if len(spec) >= 3 else None
            try:
                event_type = HookEventType(event_value)
            except ValueError:
                continue
            try:
                registry.register(
                    event_type,
                    handler,
                    matcher=str(matcher) if matcher else None,
                    source=f"plugin:{plugin_id}",
                )
            except TypeError:
                # Sync handler — skip without crashing the plugin load.
                continue
            recorded.append((event_type, handler))
            contribution_id = f"{plugin_id}:hook:{event_type.value}:{raw_index}"
            registered_contributions.append(
                PluginContribution(
                    plugin_id=plugin_id,
                    contribution_id=contribution_id,
                    contribution_type=ContributionType.HOOK,
                    display_name=f"{event_type.value} hook",
                    description=f"Hook contributed by {plugin_id}",
                    surface="extensions",
                    metadata={
                        "event_type": event_type.value,
                        "matcher": matcher,
                    },
                )
            )
        if recorded:
            self._registered_hooks[plugin_id] = recorded

    def unload_plugin(self, plugin_id: str) -> None:
        """Unload a plugin and unregister its contributions.

        Invokes the plugin's ``shutdown()`` hook to give it a chance to
        tear down sensors / subprocesses / timers before its instance is
        discarded. Without this, every reload (settings update, disable,
        upgrade) leaks the previous instance's resources — the visible
        symptom being multiple sensor timers and helper subprocesses
        stacking up after each reload.
        """

        for tool_name in self._registered_tools.pop(plugin_id, []):
            self._tool_registry.unregister(tool_name)
        for sensor_id in self._registered_sensors.pop(plugin_id, []):
            self._sensor_registry.unregister(sensor_id)
        hook_entries = self._registered_hooks.pop(plugin_id, [])
        if hook_entries:
            registry = self._resolve_hook_registry()
            if registry is not None:
                for event_type, handler in hook_entries:
                    try:
                        registry.unregister(event_type, handler)
                    except Exception:
                        pass
        plugin_instance = self._plugin_instances.pop(plugin_id, None)
        if plugin_instance is not None:
            self._fire_plugin_shutdown(plugin_id, plugin_instance)
        state = self._package_states.get(plugin_id)
        if state is not None:
            state.loaded = False
            state.contributions = self._placeholder_contributions(state.manifest)
        self._purge_plugin_modules(plugin_id)
        self._request_sensor_schedule_refresh()

    def _fire_plugin_shutdown(self, plugin_id: str, instance: Any) -> None:
        """Invoke ``plugin.shutdown()`` regardless of caller sync/async context.

        - In an async context: schedules the shutdown coroutine on the running
          loop and returns immediately. The new plugin instance can start
          loading concurrently with the old one tearing down. This brief
          overlap is benign because (a) the old sensor is already
          unregistered from SensorRegistry above so the host won't pull
          from it, and (b) the SDK's ManagedSubprocess registry catches
          any subprocess we didn't get to in time.
        - In sync context (rare): runs the shutdown to completion via
          asyncio.run().
        """
        shutdown = getattr(instance, "shutdown", None)
        if shutdown is None:
            return

        async def _run() -> None:
            try:
                result = shutdown()
                if asyncio.iscoroutine(result):
                    await asyncio.wait_for(result, timeout=5.0)
            except Exception:
                logger.exception("plugin.shutdown_failed plugin_id=%s", plugin_id)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                asyncio.run(_run())
            except Exception:
                logger.exception(
                    "plugin.shutdown_sync_runner_failed plugin_id=%s", plugin_id
                )
            return

        task = loop.create_task(_run())
        # Keep a strong ref so the task isn't GC'd mid-flight.
        self._pending_plugin_shutdowns.add(task)
        task.add_done_callback(self._pending_plugin_shutdowns.discard)

    def iter_consumers(self, library_id: str) -> list[str]:
        """Return plugin_ids that declare ``library_id`` in their ``depends_on``.

        Used by uninstall flows to refcount-protect library packages: a
        library can only be physically removed once no installed plugin
        still references it.
        """

        return [
            state.manifest.plugin_id
            for state in self._package_states.values()
            if library_id in state.manifest.depends_on
        ]

    def _reject_library(self, state: PluginPackageState, action: str) -> None:
        """Forbid user-facing toggle operations on library packages.

        Libraries are auto-installed via dep closure and refcounted on
        uninstall — they have no meaningful enable/disable semantics.
        """
        if state.manifest.kind == "library":
            raise ValueError(
                f"Cannot {action} library package {state.manifest.plugin_id}: "
                f"libraries are managed automatically as dependencies."
            )

    def enable_plugin(self, plugin_id: str) -> PluginPackageState:
        """Persist enable/trust state and load the plugin."""

        state = self._require_package(plugin_id)
        self._reject_library(state, "enable")
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
        self._request_sensor_schedule_refresh()
        return state

    def disable_plugin(self, plugin_id: str) -> PluginPackageState:
        """Persist disabled state and unregister plugin contributions."""

        state = self._require_package(plugin_id)
        self._reject_library(state, "disable")
        self.unload_plugin(plugin_id)
        save_config({f"plugins.packages.{plugin_id}.enabled": False})
        self.scan(persist_discovery=False)
        state = self._require_package(plugin_id)
        self._request_sensor_schedule_refresh()
        return state

    def reload_plugin(self, plugin_id: str) -> PluginPackageState:
        """Reload a single plugin package."""

        state = self._require_package(plugin_id)
        self.unload_plugin(plugin_id)
        if state.enabled:
            state = self.load_plugin(plugin_id)
        self._request_sensor_schedule_refresh()
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
        self._request_sensor_schedule_refresh()
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

    async def start_plugin_settings_action(
        self,
        plugin_id: str,
        action_id: str,
        *,
        field_values: dict[str, Any] | None = None,
    ) -> PluginSettingsActionRun:
        """Start a plugin-owned settings action and return its session envelope."""

        spec, plugin_instance = self._resolve_settings_action(plugin_id, action_id)
        session_id = secrets.token_urlsafe(18)
        result = await self._call_settings_action_start(
            plugin_instance,
            action_id,
            session_id=session_id,
            field_values=field_values,
        )
        self._persist_successful_action_updates(plugin_id, spec, result)
        return PluginSettingsActionRun(session_id=session_id, result=result)

    async def poll_plugin_settings_action(
        self,
        plugin_id: str,
        action_id: str,
        *,
        session_id: str,
        field_values: dict[str, Any] | None = None,
    ) -> PluginSettingsActionRun:
        """Poll a plugin-owned settings action session."""

        spec, plugin_instance = self._resolve_settings_action(plugin_id, action_id)
        result = await self._call_settings_action_poll(
            plugin_instance,
            action_id,
            session_id=session_id,
            field_values=field_values,
        )
        self._persist_successful_action_updates(plugin_id, spec, result)
        return PluginSettingsActionRun(session_id=session_id, result=result)

    async def cancel_plugin_settings_action(
        self,
        plugin_id: str,
        action_id: str,
        *,
        session_id: str,
    ) -> PluginSettingsActionRun:
        """Cancel a plugin-owned settings action session."""

        _, plugin_instance = self._resolve_settings_action(plugin_id, action_id)
        result = plugin_instance.cancel_settings_action(action_id, session_id=session_id)
        if inspect.isawaitable(result):
            result = await result
        return PluginSettingsActionRun(
            session_id=session_id,
            result=self._coerce_settings_action_result(result),
        )

    def _persist_new_packages(self, manifests: dict[str, PluginManifest]) -> None:
        config = get_config()
        updates: dict[str, Any] = {}
        for plugin_id, manifest in manifests.items():
            if plugin_id in config.plugins.packages:
                continue
            if manifest.kind == "library":
                # Libraries are not user-toggled. Always enabled + trusted
                # so they pass through the load-time gates if any consumer
                # plugin references them. (They still don't get instantiated
                # — see load_plugin.)
                enabled = True
                trusted = True
            else:
                enabled = bool(manifest.official and manifest.source == "builtin")
                trusted = enabled
            updates[f"plugins.packages.{plugin_id}.enabled"] = enabled
            updates[f"plugins.packages.{plugin_id}.trusted"] = trusted
            updates[f"plugins.packages.{plugin_id}.source"] = manifest.source
            updates[f"plugins.packages.{plugin_id}.manifest_path"] = manifest.manifest_path
            updates[f"plugins.packages.{plugin_id}.official"] = (
                bool(manifest.official) if manifest.source == "builtin" else False
            )
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

        # For each declared plugin-level dep (typically a library package),
        # add its install-root *parent* to sys.path so that
        # ``import <library_module>`` works inside the plugin code. Libraries
        # are installed as siblings under ~/.magi/plugins/, so the parent
        # path is shared across consumers. We refuse to load when a declared
        # dep is missing — better a clear error here than a deep
        # ModuleNotFoundError later.
        for dep_id in manifest.depends_on:
            dep_state = self._package_states.get(dep_id)
            if dep_state is None or not Path(dep_state.manifest.plugin_dir).is_dir():
                raise RuntimeError(
                    f"Plugin {manifest.plugin_id} depends on missing package: {dep_id}. "
                    f"Reinstall {manifest.plugin_id} to fetch dependencies."
                )
            dep_parent = str(Path(dep_state.manifest.plugin_dir).parent)
            if dep_parent not in sys.path:
                sys.path.append(dep_parent)

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

    def _collect_settings_actions(self, plugin_instance: Plugin) -> list[PluginSettingsActionSpec]:
        actions: list[PluginSettingsActionSpec] = []
        for raw_action in plugin_instance.get_settings_actions():
            if isinstance(raw_action, PluginSettingsActionSpec):
                actions.append(raw_action)
            else:
                actions.append(PluginSettingsActionSpec.model_validate(raw_action))
        return actions

    @staticmethod
    def _settings_actions_for_contribution(
        actions: list[PluginSettingsActionSpec],
        *,
        contribution_id: str,
        contribution_type: ContributionType,
        surface: str,
    ) -> list[dict[str, Any]]:
        matched: list[dict[str, Any]] = []
        for action in actions:
            if action.surface != surface:
                continue
            if action.contribution_id:
                if action.contribution_id != contribution_id:
                    continue
            elif action.contribution_type != contribution_type:
                continue
            matched.append(action.model_dump(mode="json"))
        return sorted(matched, key=lambda item: int(item.get("order") or 0))

    def _resolve_settings_action(
        self,
        plugin_id: str,
        action_id: str,
    ) -> tuple[PluginSettingsActionSpec, Plugin]:
        state = self._require_package(plugin_id)
        if not state.loaded:
            if not state.enabled:
                raise RuntimeError(f"Plugin {plugin_id} must be enabled before running settings actions")
            state = self.load_plugin(plugin_id)

        plugin_instance = self._plugin_instances.get(plugin_id)
        if plugin_instance is None:
            raise RuntimeError(f"Plugin {plugin_id} is not loaded")

        actions = {action.action_id: action for action in self._collect_settings_actions(plugin_instance)}
        spec = actions.get(action_id)
        if spec is None:
            raise KeyError(action_id)
        if spec.requires_enabled and not state.enabled:
            raise RuntimeError(f"Plugin {plugin_id} must be enabled before running {action_id}")
        return spec, plugin_instance

    async def _call_settings_action_start(
        self,
        plugin_instance: Plugin,
        action_id: str,
        *,
        session_id: str,
        field_values: dict[str, Any] | None,
    ) -> PluginSettingsActionResult:
        result = plugin_instance.start_settings_action(
            action_id,
            session_id=session_id,
            field_values=field_values,
        )
        if inspect.isawaitable(result):
            result = await result
        return self._coerce_settings_action_result(result)

    async def _call_settings_action_poll(
        self,
        plugin_instance: Plugin,
        action_id: str,
        *,
        session_id: str,
        field_values: dict[str, Any] | None,
    ) -> PluginSettingsActionResult:
        result = plugin_instance.poll_settings_action(
            action_id,
            session_id=session_id,
            field_values=field_values,
        )
        if inspect.isawaitable(result):
            result = await result
        return self._coerce_settings_action_result(result)

    @staticmethod
    def _coerce_settings_action_result(raw_result: Any) -> PluginSettingsActionResult:
        if isinstance(raw_result, PluginSettingsActionResult):
            return raw_result
        if isinstance(raw_result, dict):
            return PluginSettingsActionResult.model_validate(raw_result)
        raise RuntimeError("Plugin settings action returned an invalid response")

    def _persist_successful_action_updates(
        self,
        plugin_id: str,
        spec: PluginSettingsActionSpec,
        result: PluginSettingsActionResult,
    ) -> None:
        if result.status != "succeeded" or not spec.persist_settings_on_success:
            return
        if not result.settings_updates:
            return
        self.update_plugin_settings(plugin_id, result.settings_updates)

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
