"""Unified plugin manager for tool and sensor extensions."""

from __future__ import annotations

import asyncio
from functools import wraps
import importlib
import importlib.util
import logging
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ..config import get_config, save_config
from .base import Plugin
from .contribution_registration import PluginContributionRegistrar
from .contracts import (
    PluginCapability,
    PluginManifest,
    PluginPackageState,
)
from .discovery import (
    build_package_states,
    discover_plugin_manifests,
    load_plugin_manifest,
    persist_new_plugin_packages,
    placeholder_contributions,
    resolve_plugin_search_paths as _resolve_search_paths,
)
from .installation import InstallProgressReporter, PluginInstallationMixin
from .projections import PluginProjectionService
from .sensors import SensorRegistry
from .settings_service import PluginSettingsActionRun, PluginSettingsService

logger = logging.getLogger(__name__)


def _serialized_lifecycle_mutation(method: Callable[..., Any]) -> Callable[..., Any]:
    """Serialize one state-changing operation for a PluginManager instance."""

    @wraps(method)
    def wrapped(self: "PluginManager", *args: Any, **kwargs: Any) -> Any:
        with self._lifecycle_write_lock:
            return method(self, *args, **kwargs)

    return wrapped


@dataclass(frozen=True)
class PluginRuntimeBindings:
    plugin_manager: "PluginManager"
    plugin_projection_service: PluginProjectionService
    sensor_registry: SensorRegistry


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
    plugin_projection_service = PluginProjectionService(
        iter_loaded_plugins=plugin_manager.iter_loaded_plugins,
    )
    return PluginRuntimeBindings(
        plugin_manager=plugin_manager,
        plugin_projection_service=plugin_projection_service,
        sensor_registry=resolved_sensor_registry,
    )


class PluginManager(PluginInstallationMixin):
    """Discovers plugin packages and registers enabled contributions."""

    def __init__(
        self,
        *,
        tool_registry: Any,
        sensor_registry: SensorRegistry,
        search_paths: list[Path],
        request_sensor_schedule_refresh: Callable[[], None],
    ) -> None:
        self._search_paths = list(search_paths)
        self._request_sensor_schedule_refresh = request_sensor_schedule_refresh
        self._package_states: dict[str, PluginPackageState] = {}
        self._plugin_instances: dict[str, Plugin] = {}
        self._lifecycle_write_lock = threading.RLock()
        self._contribution_registrar = PluginContributionRegistrar(
            tool_registry=tool_registry,
            sensor_registry=sensor_registry,
        )
        self._settings_service = PluginSettingsService(
            get_package=self.get_package,
            load_plugin=self.load_plugin,
            get_loaded_plugin=self.get_loaded_plugin,
            update_plugin_settings=self.update_plugin_settings,
        )
        # Tasks spawned by unload_plugin to run plugins' shutdown coroutines.
        # We hold strong refs so they're not GC'd while pending; entries
        # remove themselves via a done callback.
        self._pending_plugin_shutdowns: set[asyncio.Task] = set()

    @property
    def search_paths(self) -> list[Path]:
        return list(self._search_paths)

    @property
    def settings_service(self) -> PluginSettingsService:
        return self._settings_service

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

    @_serialized_lifecycle_mutation
    def install_plugin_from_archive(
        self,
        archive_path: Path,
        *,
        consented_capabilities: list[PluginCapability],
        progress_reporter: InstallProgressReporter | None = None,
    ) -> PluginPackageState:
        """Install one uploaded archive without interleaving lifecycle writes."""

        return super().install_plugin_from_archive(
            archive_path,
            consented_capabilities=consented_capabilities,
            progress_reporter=progress_reporter,
        )

    @_serialized_lifecycle_mutation
    def install_plugin_from_directory(
        self,
        source_dir: Path,
        *,
        progress_reporter: InstallProgressReporter | None = None,
    ) -> PluginPackageState:
        """Install one directory without interleaving lifecycle writes."""

        return super().install_plugin_from_directory(
            source_dir,
            progress_reporter=progress_reporter,
        )

    @_serialized_lifecycle_mutation
    def uninstall_plugin(self, plugin_id: str) -> list[str]:
        """Uninstall one package without interleaving lifecycle writes."""

        return super().uninstall_plugin(plugin_id)

    @_serialized_lifecycle_mutation
    def scan(self, *, persist_discovery: bool = True) -> list[PluginPackageState]:
        """Discover plugin manifests in configured scan paths."""

        config = get_config()
        discovered = discover_plugin_manifests(self._search_paths)

        if persist_discovery:
            persist_new_plugin_packages(discovered, config=config, save=save_config)
            config = get_config()

        self._package_states = build_package_states(
            manifests=discovered,
            packages=config.plugins.packages,
            previous_states=self._package_states,
        )
        return self.list_packages()

    @_serialized_lifecycle_mutation
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

    @_serialized_lifecycle_mutation
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

    def installed_plugin_ids(self) -> set[str]:
        return set(self._package_states.keys())

    def get_loaded_plugin(self, plugin_id: str) -> Plugin | None:
        return self._plugin_instances.get(plugin_id)

    def iter_loaded_plugins(self) -> list[Plugin]:
        """Return currently loaded plugin instances."""
        return list(self._plugin_instances.values())

    @_serialized_lifecycle_mutation
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
        try:
            # _instantiate_plugin can raise (missing dep, syntax error in
            # plugin code, etc.). Keep it inside the try so any failure
            # marks the state unhealthy with a clear last_error — without
            # this guard, import-time errors would bypass error recording
            # entirely and propagate as a bare exception.
            plugin_instance = self._instantiate_plugin(state.manifest, state.current_settings)
            registered_contributions = self._contribution_registrar.register(
                plugin_id=plugin_id,
                manifest=state.manifest,
                plugin_instance=plugin_instance,
            )
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

    @_serialized_lifecycle_mutation
    def unload_plugin(self, plugin_id: str) -> None:
        """Unload a plugin and unregister its contributions.

        Invokes the plugin's ``shutdown()`` hook to give it a chance to
        tear down sensors / subprocesses / timers before its instance is
        discarded. Without this, every reload (settings update, disable,
        upgrade) leaks the previous instance's resources — the visible
        symptom being multiple sensor timers and helper subprocesses
        stacking up after each reload.
        """

        self._contribution_registrar.unregister(plugin_id)
        plugin_instance = self._plugin_instances.pop(plugin_id, None)
        if plugin_instance is not None:
            self._fire_plugin_shutdown(plugin_id, plugin_instance)
        state = self._package_states.get(plugin_id)
        if state is not None:
            state.loaded = False
            state.contributions = placeholder_contributions(state.manifest)
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
        - Without a running loop: starts a daemon thread with its own event
          loop. Lifecycle callers must never wait for plugin-controlled async
          shutdown code while holding the manager write lock.
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

            def run_in_background() -> None:
                try:
                    asyncio.run(_run())
                except Exception:
                    logger.exception(
                        "plugin.shutdown_sync_runner_failed plugin_id=%s",
                        plugin_id,
                    )

            threading.Thread(
                target=run_in_background,
                name=f"plugin-shutdown-{plugin_id}",
                daemon=True,
            ).start()
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

    @_serialized_lifecycle_mutation
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

    @_serialized_lifecycle_mutation
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

    @_serialized_lifecycle_mutation
    def reload_plugin(self, plugin_id: str) -> PluginPackageState:
        """Reload a single plugin package."""

        state = self._require_package(plugin_id)
        self.unload_plugin(plugin_id)
        if state.enabled:
            state = self.load_plugin(plugin_id)
        self._request_sensor_schedule_refresh()
        return state

    @_serialized_lifecycle_mutation
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

    def read_plugin_settings_resource(self, plugin_id: str, resource_name: str):
        return self._settings_service.read_plugin_settings_resource(plugin_id, resource_name)

    async def start_plugin_settings_action(
        self,
        plugin_id: str,
        action_id: str,
        *,
        field_values: dict[str, Any] | None = None,
    ) -> PluginSettingsActionRun:
        return await self._settings_service.start_plugin_settings_action(
            plugin_id,
            action_id,
            field_values=field_values,
        )

    async def poll_plugin_settings_action(
        self,
        plugin_id: str,
        action_id: str,
        *,
        session_id: str,
        field_values: dict[str, Any] | None = None,
    ) -> PluginSettingsActionRun:
        return await self._settings_service.poll_plugin_settings_action(
            plugin_id,
            action_id,
            session_id=session_id,
            field_values=field_values,
        )

    async def cancel_plugin_settings_action(
        self,
        plugin_id: str,
        action_id: str,
        *,
        session_id: str,
    ) -> PluginSettingsActionRun:
        return await self._settings_service.cancel_plugin_settings_action(
            plugin_id,
            action_id,
            session_id=session_id,
        )

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

    def _require_package(self, plugin_id: str) -> PluginPackageState:
        state = self._package_states.get(plugin_id)
        if state is None:
            raise KeyError(f"Unknown plugin package: {plugin_id}")
        return state

    def _load_manifest(self, manifest_path: Path, *, source: str) -> PluginManifest:
        return load_plugin_manifest(manifest_path, source=source)
