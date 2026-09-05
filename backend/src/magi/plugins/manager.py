"""Unified plugin manager for tool and source extensions."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from concurrent.futures import Future
import inspect
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

from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.runtime import (
    CapabilityReadiness,
    ConnectionStatus,
    InvocationIdentity,
    PluginConnection,
    PLUGIN_PROTOCOL_VERSION,
    SDK_VERSION,
)
from magi_plugin_sdk.versioning import parse_plugin_version

from ..config import PluginSettings, get_config, save_config
from .base import Plugin
from .contribution_registration import PluginContributionRegistrar
from .contracts import (
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
from .installation import PluginDirectoryInstallOutcome, PluginInstallationMixin
from .package_integrity import package_identity_error
from .package_identity import verify_installed_source_sha256, verify_installed_package_sha256
from .provisional_dependencies import ProvisionalLibraryReceipt
from .projections import PluginProjectionService
from .sources import RegisteredSourceSnapshot, SourceRegistry
from .history_importers import HistoryImporterRegistry
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
    source_registry: SourceRegistry
    history_importer_registry: HistoryImporterRegistry


@dataclass(frozen=True, slots=True)
class PluginUserContentTargetPreparationFailure:
    """Installed plugin that could not be prepared for local deletion."""

    plugin_id: str
    error: Exception
    connection_id: str | None = None


@dataclass(frozen=True, slots=True)
class PluginUserContentChannelTarget:
    """Channel created only to clear one disabled plugin's local state."""

    plugin_id: str
    channel_type: str
    channel: Any
    connection_id: str | None = None


@dataclass(frozen=True, slots=True)
class PluginUserContentTargetSnapshot:
    """Installed plugin and source clear targets captured atomically."""

    plugins: tuple[tuple[str, Plugin, dict[str, Any]], ...]
    sources: tuple[RegisteredSourceSnapshot, ...]
    channels: tuple[PluginUserContentChannelTarget, ...] = ()
    temporary_plugin_ids: frozenset[str] = frozenset()
    preparation_failures: tuple[PluginUserContentTargetPreparationFailure, ...] = ()


def build_plugin_runtime(
    *,
    tool_registry: Any,
    request_source_schedule_refresh: Callable[[], None],
    source_registry: SourceRegistry | None = None,
    activate_enabled: bool = True,
    connection_store: Any | None = None,
    instance_factory: Callable[[PluginManifest, PluginConnection, PluginContext], Plugin]
    | None = None,
    configure_instance: Callable[[PluginManifest, Plugin], None] | None = None,
    skill_registrar: Any | None = None,
    hook_registry_provider: Callable[[], Any] | None = None,
    operation_registrar: Any | None = None,
    provider_registrar: Any | None = None,
    content_clearer: Callable[..., Any] | None = None,
    connection_disconnector: Callable[[PluginConnection], Any] | None = None,
) -> PluginRuntimeBindings:
    """Build plugin runtime services for the current runtime instance.

    ``tool_registry`` (the shared L9 tool registry) and the
    ``request_source_schedule_refresh`` callable (an L8 awareness hook) are
    injected by the composition root so this L4 plugins module does not import
    the higher tools / awareness layers.
    """

    resolved_source_registry = source_registry or SourceRegistry()
    history_importer_registry = HistoryImporterRegistry()
    plugin_manager = PluginManager(
        tool_registry=tool_registry,
        connection_store=connection_store,
        instance_factory=instance_factory,
        configure_instance=configure_instance,
        skill_registrar=skill_registrar,
        hook_registry_provider=hook_registry_provider,
        operation_registrar=operation_registrar,
        provider_registrar=provider_registrar,
        content_clearer=content_clearer,
        connection_disconnector=connection_disconnector,
        source_registry=resolved_source_registry,
        history_importer_registry=history_importer_registry,
        search_paths=_resolve_search_paths(),
        request_source_schedule_refresh=request_source_schedule_refresh,
    )
    plugin_manager.scan(persist_discovery=activate_enabled)
    if activate_enabled:
        plugin_manager.activate_enabled_plugins()
    plugin_projection_service = PluginProjectionService(
        iter_loaded_plugins=plugin_manager.iter_loaded_plugins,
    )
    return PluginRuntimeBindings(
        plugin_manager=plugin_manager,
        plugin_projection_service=plugin_projection_service,
        source_registry=resolved_source_registry,
        history_importer_registry=history_importer_registry,
    )


class PluginManager(PluginInstallationMixin):
    """Discovers plugin packages and registers enabled contributions."""

    def __init__(
        self,
        *,
        tool_registry: Any,
        source_registry: SourceRegistry,
        search_paths: list[Path],
        request_source_schedule_refresh: Callable[[], None],
        history_importer_registry: HistoryImporterRegistry | None = None,
        connection_store: Any | None = None,
        instance_factory: Callable[[PluginManifest, PluginConnection, PluginContext], Plugin]
        | None = None,
        configure_instance: Callable[[PluginManifest, Plugin], None] | None = None,
        skill_registrar: Any | None = None,
        hook_registry_provider: Callable[[], Any] | None = None,
        operation_registrar: Any | None = None,
        provider_registrar: Any | None = None,
        content_clearer: Callable[..., Any] | None = None,
        connection_disconnector: Callable[[PluginConnection], Any] | None = None,
    ) -> None:
        self._search_paths = list(search_paths)
        self._source_registry = source_registry
        self._request_source_schedule_refresh = request_source_schedule_refresh
        self._package_states: dict[str, PluginPackageState] = {}
        self._plugin_instances: dict[str, Plugin] = {}
        self._setup_instances: dict[str, Plugin] = {}
        self._lifecycle_write_lock = threading.RLock()
        self._async_lifecycle_lock = asyncio.Lock()
        self._instance_factory = instance_factory
        self._configure_instance = configure_instance
        self._shutdown_started = False
        self._content_clearer = content_clearer
        self._connection_disconnector = connection_disconnector
        self._temporary_clear_instances: dict[str, Plugin] = {}
        self._instance_packages: dict[str, str] = {}
        self._connection_contributions: dict[str, list[Any]] = {}
        self._connection_failures: dict[str, tuple[int, str]] = {}
        self._pending_plugin_shutdowns: dict[str, Future[None]] = {}
        self._shutdown_owners: dict[str, str] = {}
        self._shutdown_tasks: set[asyncio.Task[Any]] = set()
        try:
            self._runtime_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            self._runtime_loop = None
        if connection_store is None:
            from .connections import PluginConnectionStore
            from .connection_settings import connection_fields, validate_connection_settings

            connection_store = PluginConnectionStore(
                require_package=self._require_connection_package,
                authorize_enable=self._authorize_connection,
                validate_settings=lambda connection: validate_connection_settings(
                    connection,
                    connection_fields(self._require_package(connection.plugin_id)),
                ),
            )
        self.connection_store = connection_store
        if operation_registrar is None:
            from .operations import PluginOperationRegistry

            operation_registrar = PluginOperationRegistry(
                tool_registry,
                get_connection=self.connection_store.get,
            )
        self.operation_registry = operation_registrar
        if provider_registrar is None:
            from .providers import PluginProviderRegistry

            provider_registrar = PluginProviderRegistry(get_connection=self.connection_store.get)
        self.provider_registry = provider_registrar
        self._contribution_registrar = PluginContributionRegistrar(
            tool_registry=tool_registry,
            source_registry=source_registry,
            history_importer_registry=history_importer_registry,
            skill_registrar=skill_registrar,
            hook_registry_provider=hook_registry_provider,
            operation_registrar=operation_registrar,
            provider_registrar=provider_registrar,
        )
        self._settings_service = PluginSettingsService(
            get_connection=self.connection_store.get,
            get_connection_plugin=self.get_connection_plugin,
            get_package=self.get_package,
            get_setup_plugin=self.get_connection_setup_plugin,
            operation_registry=self.operation_registry,
            update_connection_settings=lambda connection_id,
            settings,
            revision: self.update_connection(
                connection_id,
                expected_revision=revision,
                settings=settings,
            ),
        )

    @property
    def search_paths(self) -> list[Path]:
        return list(self._search_paths)

    @property
    def settings_service(self) -> PluginSettingsService:
        return self._settings_service

    @property
    def history_importer_registry(self) -> HistoryImporterRegistry:
        return self._contribution_registrar.history_importer_registry

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
    def _capture_plugin_install_target(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Capture an install target without racing lifecycle mutations."""

        return super()._capture_plugin_install_target(*args, **kwargs)

    def _commit_staged_plugin_package(
        self,
        plan: Any,
        **kwargs: Any,
    ) -> tuple[PluginDirectoryInstallOutcome, Path | None]:
        """Commit one prepared package without interleaving lifecycle writes."""

        had_loaded_connections = plan.plugin_id in self._instance_packages.values()
        self.unload_plugin(plan.plugin_id)
        self._drain_shutdowns_sync(plan.plugin_id)
        try:
            with self._lifecycle_write_lock:
                result = super()._commit_staged_plugin_package(plan, **kwargs)
                state = self.get_package(plan.plugin_id)
                if state is not None and state.trusted:
                    self.load_plugin(plan.plugin_id)
                return result
        except BaseException:
            self._drain_shutdowns_sync(plan.plugin_id)
            if had_loaded_connections:
                self.load_plugin(plan.plugin_id)
            raise

    @_serialized_lifecycle_mutation
    def remove_provisional_registry_library(
        self,
        receipt: ProvisionalLibraryReceipt,
    ) -> Path | None:
        """Remove an exact orphan without interleaving lifecycle writes."""

        return super().remove_provisional_registry_library(receipt)

    @_serialized_lifecycle_mutation
    def uninstall_plugin(self, plugin_id: str) -> list[str]:
        """Uninstall one package without interleaving lifecycle writes."""
        if self._require_package(plugin_id).manifest.kind != "library" and self.connection_store.list(plugin_id):
            raise ValueError("Disconnect plugin connections before uninstalling their package")
        self._require_no_pending_shutdown(plugin_id)
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
        for plugin_id in self._package_states:
            self._refresh_package_contributions(plugin_id)
        return self.list_packages()

    @_serialized_lifecycle_mutation
    def activate_enabled_plugins(self) -> None:
        """Load every enabled plugin package.

        Each plugin's load is wrapped in try/except so that one broken plugin
        (e.g. a missing Python dep) cannot crash the runtime startup. Failed
        plugins are left with ``healthy=False`` and a non-empty ``last_error``;
        the user can disable or repair them via the UI. Library packages
        (``kind == "library"``) ship Python modules consumed by other plugins
        and have no :class:`Plugin` instance to instantiate. Their availability
        comes from verified installation metadata, without an activation flag.
        """

        for state in self.list_packages():
            if not state.enabled:
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

        for plugin_id in set(self._instance_packages.values()):
            self.unload_plugin(plugin_id)
        self._require_no_pending_shutdown()
        self.scan(persist_discovery=persist_discovery)
        self.activate_enabled_plugins()
        self._request_source_schedule_refresh()
        return self.list_packages()

    def list_packages(self) -> list[PluginPackageState]:
        with self._lifecycle_write_lock:
            return sorted(
                list(self._package_states.values()),
                key=lambda item: item.manifest.plugin_id,
            )

    def get_package(self, plugin_id: str) -> Optional[PluginPackageState]:
        with self._lifecycle_write_lock:
            return self._package_states.get(plugin_id)

    @_serialized_lifecycle_mutation
    def authorize_package(
        self, plugin_id: str, expected_package_sha256: str
    ) -> PluginPackageState:
        """Record explicit user approval of one reviewed, sealed installed artifact.

        The host must show this artifact's permissions before calling. Matching
        its digest binds the approval to the current manifest and package files.
        Approval records consent only; connections and workers are unaffected.
        """
        state = self._require_package(plugin_id)
        configured = get_config().plugins.packages.get(plugin_id)
        if configured is None or state.manifest.source == "builtin":
            raise ValueError("Only installed external packages require user authorization")
        configured = PluginSettings.model_validate(configured)
        if configured.install_origin not in {"registry", "upload", "local"}:
            raise ValueError("Plugin must be installed before it can be authorized")
        if not configured.package_sha256 or not configured.installed_package_sha256:
            raise ValueError("Plugin installation must include an artifact digest and installed seal")
        if configured.package_sha256 != expected_package_sha256:
            raise ValueError("Reviewed plugin package digest no longer matches the installation")
        manifest = load_plugin_manifest(Path(state.manifest.manifest_path), source="external")
        if manifest != state.manifest:
            raise ValueError("Plugin manifest changed since it was reviewed")
        self._validate_runtime_version(manifest)
        identity_error = package_identity_error(manifest, configured)
        if identity_error:
            raise ValueError(identity_error)
        plugin_dir = Path(manifest.plugin_dir)
        verify_installed_source_sha256(plugin_dir, expected_package_sha256)
        verify_installed_package_sha256(plugin_dir, configured.installed_package_sha256)
        if not save_config({
            f"plugins.packages.{plugin_id}.consented_capabilities": [
                capability.model_dump(mode="json") for capability in manifest.capabilities
            ],
            f"plugins.packages.{plugin_id}.trusted": True,
        }):
            raise RuntimeError("Failed to persist plugin authorization")
        state.trusted = True
        return state

    def installed_plugin_ids(self) -> set[str]:
        with self._lifecycle_write_lock:
            return set(self._package_states.keys())

    def get_connection_plugin(self, connection_id: str) -> Plugin | None:
        with self._lifecycle_write_lock:
            return self._plugin_instances.get(connection_id)

    def get_connection_setup_plugin(self, connection_id: str) -> Plugin:
        """Resolve the retained setup worker through the same admission checks."""
        return self.setup_connection(connection_id)

    @_serialized_lifecycle_mutation
    def setup_connection(self, connection_id: str) -> Plugin:
        """Prepare a consented disabled connection without registering contributions.

        Settings actions retain this instance until a lifecycle change so login
        sessions survive polling. Callers on the event loop must dispatch this
        synchronous process-start boundary through the lifecycle worker.
        """
        from .operation_authorization import InstalledOperationAuthorizer

        if self._shutdown_started:
            raise RuntimeError("Plugin runtime is shutting down")
        connection = self.connection_store.get(connection_id)
        plugin_id = connection.plugin_id
        self._require_no_pending_shutdown(plugin_id)
        if connection.enabled:
            raise ValueError("Setup workers require a disabled connection")
        if connection_id in self._plugin_instances:
            self.unload_connection(connection_id)
            self._require_no_pending_shutdown(plugin_id)
        try:
            self._authorize_connection(connection)
            authorizer = InstalledOperationAuthorizer(
                get_package=self.get_package,
                connection_store=self.connection_store,
                config_provider=get_config,
            )
            if not authorizer.authorize_setup_connection(connection):
                raise PermissionError("Plugin connection setup requires current package consent")
        except BaseException:
            self.unload_connection(connection_id)
            self._record_connection_failure(connection_id, "setup_authorization_failed")
            raise
        existing = self._setup_instances.get(connection_id)
        if existing is not None:
            return existing
        if plugin_id not in self._instance_packages.values():
            self._purge_plugin_modules(plugin_id)
        state = self._require_package(plugin_id)
        try:
            instance = self._instantiate_configured_plugin(
                state.manifest, connection, self.connection_store.context(connection_id)
            )
            self._setup_instances[connection_id] = instance
            self._instance_packages[connection_id] = plugin_id
            self._connection_failures.pop(connection_id, None)
            self._publish_connection_readiness(connection_id)
            self._refresh_package_contributions(plugin_id)
        except BaseException as exc:
            state.healthy = False
            state.last_error = str(exc)
            self.unload_connection(connection_id)
            self._record_connection_failure(connection_id, "setup_start_failed")
            raise
        return instance

    def iter_loaded_plugins(self) -> list[Plugin]:
        """Return currently loaded plugin instances."""
        with self._lifecycle_write_lock:
            return list(self._plugin_instances.values())

    def snapshot_user_content_clear_targets(self) -> PluginUserContentTargetSnapshot:
        """Capture explicit connections, including disabled connections, for host deletion."""
        # The global clear coordinator holds the runtime operation barrier.
        # Drain outside the manager lock so shutdown callbacks can reenter it.
        with self._lifecycle_write_lock:
            setup_packages = {self._instance_packages[key] for key in self._setup_instances}
            for connection_id in tuple(self._setup_instances):
                self.unload_connection(connection_id)
        for plugin_id in setup_packages:
            self._drain_shutdowns_sync(plugin_id)
        with self._lifecycle_write_lock:
            self._require_no_pending_shutdown()
            plugins: list[tuple[str, Plugin, dict[str, Any]]] = []
            sources = list(self._source_registry.snapshot_user_content_clear_targets())
            channels: list[PluginUserContentChannelTarget] = []
            temporary_ids: set[str] = set()
            failures: list[PluginUserContentTargetPreparationFailure] = []
            for connection in self.connection_store.list():
                connection_id = connection.connection_id
                state = self._require_package(connection.plugin_id)
                instance = self._plugin_instances.get(connection_id)
                if instance is None:
                    try:
                        self._authorize_connection(connection)
                        instance = self._instantiate_configured_plugin(
                            state.manifest,
                            connection,
                            self.connection_store.context(connection_id),
                        )
                        self._temporary_clear_instances[connection_id] = instance
                        temporary_ids.add(connection_id)
                        for source_id, source, _spec in instance.get_sources():
                            sources.append(
                                RegisteredSourceSnapshot(
                                    plugin_id=connection.plugin_id,
                                    source_id=f"{connection_id}:{source_id}",
                                    source=source,
                                    connection_id=connection_id,
                                )
                            )
                        channel = instance.get_channel()
                        if channel is not None:
                            channels.append(
                                PluginUserContentChannelTarget(
                                    plugin_id=connection.plugin_id,
                                    channel_type=str(channel.channel_type),
                                    channel=channel,
                                    connection_id=connection_id,
                                )
                            )
                    except Exception as exc:
                        failures.append(
                            PluginUserContentTargetPreparationFailure(
                                plugin_id=connection.plugin_id,
                                error=exc,
                                connection_id=connection_id,
                            )
                        )
                        if instance is None:
                            continue
                plugins.append((connection_id, instance, deepcopy(connection.settings)))
            return PluginUserContentTargetSnapshot(
                plugins=tuple(plugins),
                sources=tuple(sources),
                channels=tuple(channels),
                temporary_plugin_ids=frozenset(temporary_ids),
                preparation_failures=tuple(failures),
            )

    def release_temporary_user_content_clear_target(self, connection_id: str) -> None:
        """Release modules after the coordinator drained a temporary connection instance."""
        with self._lifecycle_write_lock:
            if connection_id in self._plugin_instances:
                raise RuntimeError(f"Loaded connection {connection_id} is not a temporary target")
            instance = self._temporary_clear_instances.pop(connection_id, None)
            if instance is not None and instance.plugin_id not in self._instance_packages.values():
                self._purge_plugin_modules(instance.plugin_id)

    def _require_connection_package(self, plugin_id: str) -> PluginPackageState:
        state = self._require_package(plugin_id)
        self._reject_library(state, "create a connection for")
        return state

    def _drain_shutdowns_sync(self, plugin_id: str) -> None:
        """Worker callers may wait; loop callers must use the async lifecycle API."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            with self._lifecycle_write_lock:
                completions = [
                    future
                    for key, future in self._pending_plugin_shutdowns.items()
                    if self._shutdown_owners[key] == plugin_id
                ]
            for completion in completions:
                completion.result()
        with self._lifecycle_write_lock:
            self._require_no_pending_shutdown(plugin_id)

    def create_connection(self, plugin_id: str, **kwargs: Any) -> PluginConnection:
        connection = self.connection_store.create(plugin_id, **kwargs)
        if connection.enabled:
            self.load_connection(connection.connection_id)
        with self._lifecycle_write_lock:
            self._refresh_package_contributions(plugin_id)
            self._publish_connection_readiness(connection.connection_id)
        return self.connection_store.get(connection.connection_id)

    def update_connection(
        self, connection_id: str, *, expected_revision: int, **updates: Any
    ) -> PluginConnection:
        connection = self._check_connection_revision(connection_id, expected_revision)
        self.unload_connection(connection_id)
        self._drain_shutdowns_sync(connection.plugin_id)
        updated = self.connection_store.update(
            connection_id,
            expected_revision=expected_revision,
            **updates,
        )
        if updated.enabled:
            self.load_connection(connection_id)
        with self._lifecycle_write_lock:
            self._refresh_package_contributions(updated.plugin_id)
            self._publish_connection_readiness(connection_id)
        return self.connection_store.get(connection_id)

    def disconnect_connection(self, connection_id: str, *, expected_revision: int) -> None:
        connection = self._check_connection_revision(connection_id, expected_revision)
        if self._connection_disconnector is None:
            raise RuntimeError("Connection disconnect coordinator is unavailable")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Connection disconnect must run in the lifecycle worker")
        result = self._connection_disconnector(connection)
        if inspect.isawaitable(result):
            asyncio.run(result)
        self.unload_connection(connection_id)
        self._drain_shutdowns_sync(connection.plugin_id)
        self.connection_store.disconnect(connection_id, expected_revision=expected_revision)
        with self._lifecycle_write_lock:
            self._connection_failures.pop(connection_id, None)
            self._refresh_package_contributions(connection.plugin_id)

    def clear_connection_content(
        self, connection_id: str, *, expected_revision: int
    ) -> PluginConnection:
        connection = self._check_connection_revision(connection_id, expected_revision)
        if self._content_clearer is None:
            raise RuntimeError("Connection content clear coordinator is unavailable")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Connection content clear must run in the lifecycle worker")
        self.unload_connection(connection_id)
        self._drain_shutdowns_sync(connection.plugin_id)
        context = self.connection_store.context(connection_id)
        self._authorize_connection(connection)
        instance = self._instantiate_configured_plugin(
            self._require_package(connection.plugin_id).manifest, connection, context
        )
        try:
            result = self._content_clearer(connection, instance, context)
            if inspect.isawaitable(result):
                asyncio.run(result)
        finally:
            self._fire_plugin_shutdown(connection.plugin_id, connection_id, instance)
            self._drain_shutdowns_sync(connection.plugin_id)
        result = self.connection_store.clear_content(
            connection_id, expected_revision=expected_revision
        )
        if result.enabled:
            self.load_connection(connection_id)
        return self.connection_store.get(connection_id)

    def connection_readiness(self, connection_id: str) -> list[CapabilityReadiness]:
        """Recompute host readiness from the current schema and registered instance."""
        with self._lifecycle_write_lock:
            return self._publish_connection_readiness(connection_id)

    def _record_connection_failure(self, connection_id: str, reason: str) -> None:
        connection = self.connection_store.get(connection_id)
        self._connection_failures[connection_id] = (connection.revision, reason)
        self._publish_connection_readiness(connection_id)

    def _publish_connection_readiness(self, connection_id: str) -> list[CapabilityReadiness]:
        from .connection_settings import connection_fields, validate_connection_settings

        connection = self.connection_store.get(connection_id)
        failure = self._connection_failures.get(connection_id)
        status, reason = ConnectionStatus.DISABLED, None
        if failure is not None and failure[0] == connection.revision:
            status, reason = ConnectionStatus.FAILED, failure[1]
        elif connection.enabled or connection_id in self._setup_instances:
            fields = connection_fields(self._require_package(connection.plugin_id))
            candidate = connection.model_copy(update={"enabled": True})
            try:
                validate_connection_settings(candidate, fields)
            except ValueError:
                try:
                    validate_connection_settings(candidate, [field for field in fields if field.type != "secret"])
                except ValueError:
                    status, reason = ConnectionStatus.SETUP_REQUIRED, "configuration_required"
                else:
                    status, reason = ConnectionStatus.AUTH_REQUIRED, "credentials_required"
            else:
                if connection.enabled and connection_id in self._connection_contributions:
                    status = ConnectionStatus.READY
                else:
                    status, reason = ConnectionStatus.SETUP_REQUIRED, (
                        "enable_required" if not connection.enabled else "not_loaded"
                    )
        previous = self.connection_store.get_readiness(connection_id)
        readiness = [CapabilityReadiness(
            capability_id="connection", connection_id=connection_id,
            status=status, reason_code=reason,
        ), *(item for item in previous if item.capability_id != "connection")]
        if previous != readiness:
            self.connection_store.set_readiness(connection_id, readiness, expected_revision=connection.revision)
        return readiness

    def _check_connection_revision(
        self, connection_id: str, expected_revision: int
    ) -> PluginConnection:
        from .connections import ConnectionRevisionError

        connection = self.connection_store.get(connection_id)
        if connection.revision != expected_revision:
            raise ConnectionRevisionError(connection.revision)
        return connection

    def _validate_runtime_version(self, manifest: PluginManifest) -> None:
        if manifest.protocol_version != PLUGIN_PROTOCOL_VERSION:
            raise ValueError(f"Unsupported plugin protocol: {manifest.protocol_version}")
        if parse_plugin_version(manifest.min_sdk_version) > parse_plugin_version(SDK_VERSION):
            raise ValueError(
                f"Plugin requires SDK {manifest.min_sdk_version}; host SDK is {SDK_VERSION}"
            )

    def _authorize_connection(self, connection: PluginConnection) -> None:
        state = self._require_connection_package(connection.plugin_id)
        self._validate_runtime_version(state.manifest)
        configured = get_config().plugins.packages.get(connection.plugin_id)
        identity_error = package_identity_error(state.manifest, configured)
        if identity_error:
            raise RuntimeError(identity_error)
        if state.manifest.source != "builtin" and not state.trusted:
            raise RuntimeError(f"Plugin {connection.plugin_id} must be trusted before loading")

    def _require_no_pending_shutdown(self, plugin_id: str | None = None) -> None:
        """Never replace an instance until its previous shutdown completed successfully."""
        for connection_id, completion in tuple(self._pending_plugin_shutdowns.items()):
            owner = self._shutdown_owners[connection_id]
            if plugin_id is not None and owner != plugin_id:
                continue
            if not completion.done():
                raise RuntimeError(
                    f"Plugin shutdown is pending for {connection_id}; await drain_shutdowns()"
                )
            completion.result()
            self._pending_plugin_shutdowns.pop(connection_id)
            self._shutdown_owners.pop(connection_id)
            if owner not in self._instance_packages.values():
                self._purge_plugin_modules(owner)

    @_serialized_lifecycle_mutation
    def load_plugin(self, plugin_id: str) -> PluginPackageState:
        """Load enabled explicit connections; external packages never gain a default account."""
        state = self._require_package(plugin_id)
        self._validate_runtime_version(state.manifest)
        self._require_no_pending_shutdown(plugin_id)
        if state.manifest.kind == "library":
            if not state.trusted:
                raise RuntimeError(f"Library package {plugin_id} must be trusted before use")
            identity_error = package_identity_error(
                state.manifest, get_config().plugins.packages.get(plugin_id)
            )
            if identity_error:
                raise RuntimeError(identity_error)
            state.loaded = True
            return state
        connections = list(self.connection_store.list(plugin_id))
        if state.manifest.source == "builtin" and not connections:
            connections = [
                self.connection_store.create(
                    plugin_id,
                    display_name=state.manifest.name,
                    enabled=True,
                )
            ]
        loaded_now: list[str] = []
        try:
            for connection in connections:
                if connection.enabled and connection.connection_id not in self._plugin_instances:
                    self.load_connection(connection.connection_id)
                    loaded_now.append(connection.connection_id)
        except BaseException:
            for connection_id in reversed(loaded_now):
                self.unload_connection(connection_id)
            raise
        self._refresh_package_contributions(plugin_id)
        return state

    @_serialized_lifecycle_mutation
    def load_connection(self, connection_id: str) -> Plugin:
        if self._shutdown_started:
            raise RuntimeError("Plugin runtime is shutting down")
        connection = self.connection_store.get(connection_id)
        if connection is None:
            raise KeyError(f"Unknown plugin connection: {connection_id}")
        plugin_id = connection.plugin_id
        state = self._require_package(plugin_id)
        self._require_no_pending_shutdown(plugin_id)
        try:
            self._authorize_connection(connection)
        except Exception as exc:
            state.healthy = False
            state.last_error = str(exc)
            self._record_connection_failure(connection_id, "load_authorization_failed")
            raise
        if not connection.enabled:
            raise ValueError(f"Plugin connection is disabled: {connection_id}")
        if connection_id in self._setup_instances:
            self.unload_connection(connection_id)
            self._require_no_pending_shutdown(plugin_id)
        existing = self._plugin_instances.get(connection_id)
        if existing is not None:
            return existing
        if plugin_id not in self._instance_packages.values():
            self._purge_plugin_modules(plugin_id)
        instance: Plugin | None = None
        try:
            context = self.connection_store.context(connection_id)
            instance = self._instantiate_configured_plugin(state.manifest, connection, context)
            self._plugin_instances[connection_id] = instance
            self._instance_packages[connection_id] = plugin_id
            contributions = self._contribution_registrar.register(
                plugin_id=plugin_id,
                connection_id=connection_id,
                manifest=state.manifest,
                plugin_instance=instance,
            )
            self._connection_contributions[connection_id] = contributions
            self._connection_failures.pop(connection_id, None)
            self._publish_connection_readiness(connection_id)
            state.healthy = True
            state.last_error = None
            self._refresh_package_contributions(plugin_id)
            self._request_source_schedule_refresh()
            return instance
        except BaseException as exc:
            state.healthy = False
            state.last_error = str(exc)
            if instance is not None:
                self.unload_connection(connection_id)
            elif (
                plugin_id not in self._instance_packages.values()
                and plugin_id not in self._shutdown_owners.values()
            ):
                self._purge_plugin_modules(plugin_id)
            self._record_connection_failure(connection_id, "load_failed")
            raise

    def _refresh_package_contributions(self, plugin_id: str) -> None:
        state = self._package_states.get(plugin_id)
        if state is None:
            return
        if state.manifest.kind == "library":
            return
        connections = self.connection_store.list(plugin_id)
        state.enabled = any(connection.enabled for connection in connections) or (
            not connections and state.manifest.source == "builtin" and state.manifest.official
        )
        state.current_settings = deepcopy(connections[0].settings) if len(connections) == 1 else {}
        loaded_ids = [key for key in self._plugin_instances if self._instance_packages[key] == plugin_id]
        state.loaded = bool(loaded_ids)
        state.contributions = [
            contribution
            for key in loaded_ids
            for contribution in self._connection_contributions.get(key, [])
        ]
        if not loaded_ids:
            state.contributions = placeholder_contributions(state.manifest)

    @_serialized_lifecycle_mutation
    def unload_connection(self, connection_id: str) -> None:
        instance = self._plugin_instances.get(connection_id) or self._setup_instances.get(connection_id)
        if instance is None:
            return
        plugin_id = self._instance_packages[connection_id]
        try:
            self._settings_service.unregister_connection(connection_id)
            self._contribution_registrar.unregister(connection_id)
        finally:
            self._plugin_instances.pop(connection_id, None)
            self._setup_instances.pop(connection_id, None)
            self._instance_packages.pop(connection_id, None)
            self._connection_contributions.pop(connection_id, None)
            self._fire_plugin_shutdown(plugin_id, connection_id, instance)
            self._connection_failures.pop(connection_id, None)
            self._publish_connection_readiness(connection_id)
            self._refresh_package_contributions(plugin_id)
            self._request_source_schedule_refresh()

    @_serialized_lifecycle_mutation
    def unload_plugin(self, plugin_id: str) -> None:
        """Detach all package connections and retain every pending shutdown for draining."""
        failures: list[Exception] = []
        for connection_id, owner in tuple(self._instance_packages.items()):
            if owner == plugin_id:
                try:
                    self.unload_connection(connection_id)
                except Exception as exc:
                    failures.append(exc)
        self._refresh_package_contributions(plugin_id)
        if failures:
            raise RuntimeError(f"Plugin unload failed: {failures}") from failures[0]

    def _fire_plugin_shutdown(self, plugin_id: str, connection_id: str, instance: Plugin) -> None:
        completion: Future[None] = Future()
        self._pending_plugin_shutdowns[connection_id] = completion
        self._shutdown_owners[connection_id] = plugin_id

        async def run_shutdown() -> None:
            try:
                result = instance.shutdown()
                if inspect.isawaitable(result):
                    await result
            except BaseException as exc:
                completion.set_exception(exc)
            else:
                completion.set_result(None)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            if self._runtime_loop is not None and self._runtime_loop.is_running():
                asyncio.run_coroutine_threadsafe(run_shutdown(), self._runtime_loop)
                return
            # Track the thread through its completion future just like loop-owned tasks.
            threading.Thread(
                target=lambda: asyncio.run(run_shutdown()),
                name=f"plugin-shutdown-{connection_id}",
                daemon=True,
            ).start()
        else:
            task = loop.create_task(run_shutdown())
            self._shutdown_tasks.add(task)
            task.add_done_callback(self._shutdown_tasks.discard)

    async def drain_shutdowns(self, plugin_id: str | None = None) -> None:
        """Await shutdown without the write lock; cancellation cannot abandon cleanup."""
        with self._lifecycle_write_lock:
            completions = [
                future
                for key, future in self._pending_plugin_shutdowns.items()
                if plugin_id is None or self._shutdown_owners[key] == plugin_id
            ]
        results = await asyncio.gather(
            *(asyncio.shield(asyncio.wrap_future(future)) for future in completions),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise RuntimeError("Plugin shutdown failed; replacement is blocked") from result
        with self._lifecycle_write_lock:
            self._require_no_pending_shutdown(plugin_id)

    async def unload_plugin_async(self, plugin_id: str) -> None:
        async with self._async_lifecycle_lock:
            try:
                self.unload_plugin(plugin_id)
            finally:
                await self.drain_shutdowns(plugin_id)

    async def reload_plugin_async(self, plugin_id: str) -> PluginPackageState:
        async with self._async_lifecycle_lock:
            try:
                self.unload_plugin(plugin_id)
            finally:
                await self.drain_shutdowns(plugin_id)
            self._require_package(plugin_id)
            return self.load_plugin(plugin_id)

    async def unload_connection_async(self, connection_id: str) -> None:
        async with self._async_lifecycle_lock:
            connection = self.connection_store.get(connection_id)
            try:
                self.unload_connection(connection_id)
            finally:
                await self.drain_shutdowns(connection.plugin_id)

    async def reload_connection_async(self, connection_id: str) -> Plugin:
        async with self._async_lifecycle_lock:
            connection = self.connection_store.get(connection_id)
            try:
                self.unload_connection(connection_id)
            finally:
                await self.drain_shutdowns(connection.plugin_id)
            return self.load_connection(connection_id)

    async def shutdown(self) -> None:
        async with self._async_lifecycle_lock:
            with self._lifecycle_write_lock:
                self._shutdown_started = True
            failures: list[Exception] = []
            try:
                for plugin_id in set(self._instance_packages.values()):
                    try:
                        self.unload_plugin(plugin_id)
                    except Exception as exc:
                        failures.append(exc)
            finally:
                await self.drain_shutdowns()
            if failures:
                raise RuntimeError(f"Plugin shutdown cleanup failed: {failures}") from failures[0]

    def iter_consumers(self, library_id: str) -> list[str]:
        """Return plugin_ids that declare ``library_id`` in their ``depends_on``.

        Used by uninstall flows to refcount-protect library packages: a
        library can only be physically removed once no installed plugin
        still references it.
        """

        with self._lifecycle_write_lock:
            return [
                state.manifest.plugin_id
                for state in list(self._package_states.values())
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

    def reload_plugin(self, plugin_id: str) -> PluginPackageState:
        """Reload all enabled connections after the old instances finish shutdown."""
        self._require_package(plugin_id)
        self.unload_plugin(plugin_id)
        self._drain_shutdowns_sync(plugin_id)
        return self.load_plugin(plugin_id)

    def read_plugin_settings_resource(self, connection_id: str, resource_name: str):
        return self._settings_service.read_plugin_settings_resource(connection_id, resource_name)

    async def start_plugin_settings_action(
        self,
        connection_id: str,
        action_id: str,
        *,
        identity: InvocationIdentity,
        field_values: dict[str, Any] | None = None,
    ) -> PluginSettingsActionRun:
        return await self._settings_service.start_plugin_settings_action(
            connection_id,
            action_id,
            identity=identity,
            field_values=field_values,
        )

    async def poll_plugin_settings_action(
        self,
        connection_id: str,
        action_id: str,
        *,
        identity: InvocationIdentity,
        session_id: str,
        field_values: dict[str, Any] | None = None,
    ) -> PluginSettingsActionRun:
        return await self._settings_service.poll_plugin_settings_action(
            connection_id,
            action_id,
            identity=identity,
            session_id=session_id,
            field_values=field_values,
        )

    async def cancel_plugin_settings_action(
        self,
        connection_id: str,
        action_id: str,
        *,
        identity: InvocationIdentity,
        session_id: str,
    ) -> PluginSettingsActionRun:
        return await self._settings_service.cancel_plugin_settings_action(
            connection_id,
            action_id,
            identity=identity,
            session_id=session_id,
        )

    def _instantiate_configured_plugin(
        self, manifest: PluginManifest, connection: PluginConnection, context: PluginContext
    ) -> Plugin:
        """Bind host resources after plugin configuration and before publication."""
        instance = self._instantiate_plugin(manifest, connection, context)
        try:
            if self._configure_instance is not None:
                self._configure_instance(manifest, instance)
        except BaseException:
            self._fire_plugin_shutdown(manifest.plugin_id, connection.connection_id, instance)
            raise
        return instance

    def _instantiate_plugin(
        self, manifest: PluginManifest, connection: PluginConnection, context: PluginContext
    ) -> Plugin:
        if self._instance_factory is not None:
            return self._instance_factory(manifest, connection, context)
        module_path = Path(manifest.plugin_dir) / f"{manifest.entry_module}.py"

        # Add plugin-local .deps/ to sys.path so private dependencies resolve.
        # Appended (not inserted) so host packages take precedence over
        # plugin-bundled copies, avoiding accidental version overrides.
        deps_dir = Path(manifest.plugin_dir) / ".deps"
        if manifest.source == "builtin" and deps_dir.is_dir() and str(deps_dir) not in sys.path:
            sys.path.append(str(deps_dir))

        raw_package_config = get_config().plugins.packages.get(manifest.plugin_id)
        package_config = (
            PluginSettings.model_validate(raw_package_config)
            if raw_package_config is not None
            else None
        )
        dependency_targets = self._capture_plugin_dependencies(
            manifest,
            registry_source=(
                package_config.registry_source if package_config is not None else None
            ),
            registry_repo_url=(
                package_config.registry_repo_url if package_config is not None else None
            ),
            dependency_package_sha256=(
                dict(package_config.dependency_package_sha256) if package_config is not None else {}
            ),
        )
        if manifest.source != "builtin":
            from .process_runtime import ProcessPluginProxy

            return ProcessPluginProxy(
                manifest, connection, context,
                dependency_paths=tuple(Path(target.package_state.manifest.plugin_dir)
                                       for target in dependency_targets),
            )
        for dependency_target in dependency_targets:
            dep_state = dependency_target.package_state
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
        try:
            plugin_instance.configure(manifest=manifest, connection=connection, context=context)
        except BaseException:
            self._fire_plugin_shutdown(
                manifest.plugin_id, connection.connection_id, plugin_instance
            )
            raise
        return plugin_instance

    def _require_package(self, plugin_id: str) -> PluginPackageState:
        state = self._package_states.get(plugin_id)
        if state is None:
            raise KeyError(f"Unknown plugin package: {plugin_id}")
        return state

    def _load_manifest(self, manifest_path: Path, *, source: str) -> PluginManifest:
        return load_plugin_manifest(manifest_path, source=source)
