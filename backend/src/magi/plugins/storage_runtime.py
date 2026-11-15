"""Early storage package loading without queues, sources or domain services."""

from __future__ import annotations

import asyncio
import importlib.util
from collections.abc import Callable, Mapping
from pathlib import Path
import sys

from magi_plugin_sdk import Plugin
from magi_plugin_sdk.contracts import ContributionType, PluginManifest
from magi_plugin_sdk.runtime import PluginConnection, SDK_VERSION
from magi_plugin_sdk.storage import StorageDomain
from magi_plugin_sdk.versioning import validate_sdk_requirement

from ..config.plugin_models import PluginSettings
from ..core.async_cleanup import finish_cleanup
from ..utils.runtime import RuntimePaths
from .connection_settings import connection_fields, validate_connection_settings
from .connections import PluginConnectionStore
from .discovery import build_package_states, discover_plugin_manifests
from .package_integrity import package_identity_error, package_install_record_error
from .process_runtime import ProcessPluginProxy
from .storage_registry import PluginStorageRegistry, StorageContribution

class StoragePluginRuntime:
    def __init__(
        self, *, paths: RuntimePaths, search_paths: list[Path],
        packages: Mapping[str, PluginSettings],
        bind_builtin: Callable[[PluginManifest, Plugin], None],
        guard_mutation: Callable[[str, str | None], None] | None = None,
    ) -> None:
        self.packages = packages
        self._guard_mutation = guard_mutation
        self.states = build_package_states(
            manifests=discover_plugin_manifests(search_paths), packages=packages, previous_states={},
        )
        self._bind_builtin = bind_builtin
        self._load_lock = asyncio.Lock()
        self.registry = PluginStorageRegistry()
        self.instances: dict[str, Plugin] = {}
        self._module_names: set[str] = set()
        self._disposers: list[Callable[[], None]] = []
        self.connections = PluginConnectionStore(
            runtime_paths=paths, require_package=self._require_package,
            authorize_enable=self._authorize,
            validate_settings=lambda connection: validate_connection_settings(
                connection, connection_fields(self._require_package(connection.plugin_id)),
            ),
        )

    def _require_package(self, plugin_id: str):
        state = self.states[plugin_id]
        if state.manifest.contribution_types != [ContributionType.STORAGE]:
            raise ValueError("Storage packages must contribute only storage")
        if state.manifest.depends_on:
            raise ValueError("Early storage packages must be self-contained")
        return state

    def _authorize(self, connection: PluginConnection) -> None:
        manifest = self._require_package(connection.plugin_id).manifest
        validate_sdk_requirement(manifest.min_sdk_version, protocol_version=manifest.protocol_version, sdk_version=SDK_VERSION)
        configured = self.packages.get(connection.plugin_id)
        error = package_install_record_error(manifest, configured)
        if error:
            raise RuntimeError(error)
        if manifest.source != "builtin":
            if configured is None or not configured.trusted or configured.consented_capabilities != manifest.capabilities:
                raise PermissionError("Storage package requires current trust and capability consent")
            error = package_identity_error(manifest, configured)
            if error:
                raise RuntimeError(error)

    def default_sqlite_connection(self) -> str:
        connections = self.connections.list("storage-sqlite")
        if not connections:
            return self.connections.create("storage-sqlite", display_name="SQLite", enabled=True).connection_id
        if len(connections) != 1:
            raise ValueError("Select an explicit SQLite storage connection")
        return connections[0].connection_id

    async def load(self, connection_id: str, provider_id: str, domain: StorageDomain) -> StorageContribution:
        async with self._load_lock:
            if connection_id not in self.instances:
                try:
                    await finish_cleanup(asyncio.to_thread(self._load, connection_id))
                except BaseException:
                    await self.close()
                    raise
        return self.registry.resolve(connection_id, provider_id, domain)

    def _load(self, connection_id: str) -> None:
        connection = self.connections.get(connection_id)
        if not connection.enabled:
            raise ValueError("Selected storage connection is disabled")
        self._authorize(connection)
        state = self._require_package(connection.plugin_id)
        manifest = state.manifest
        validate_connection_settings(connection, connection_fields(state))
        context = self.connections.context(connection_id)
        if manifest.source == "builtin":
            spec = importlib.util.spec_from_file_location(
                f"magi_storage_{connection_id}", Path(manifest.plugin_dir) / f"{manifest.entry_module}.py",
                submodule_search_locations=[manifest.plugin_dir],
            )
            if spec is None or spec.loader is None:
                raise RuntimeError("Builtin storage entrypoint is unavailable")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            self._module_names.add(spec.name)
            spec.loader.exec_module(module)
            instance = getattr(module, manifest.entry_class)()
            if not isinstance(instance, Plugin):
                raise TypeError("Storage entrypoint must implement Plugin")
            instance.configure(manifest=manifest, connection=connection, context=context)
            self._bind_builtin(manifest, instance)
        else:
            instance = ProcessPluginProxy(manifest, connection, context)
        self.instances[connection_id] = instance
        entries = instance.get_storage_providers()
        if not entries:
            raise ValueError("Storage package did not provide its declared capability")
        for spec, provider in entries:
            self._disposers.append(self.registry.register(
                plugin_id=manifest.plugin_id, connection_id=connection_id, spec=spec, provider=provider,
            ))

    def require_mutable(self, plugin_id: str, connection_id: str | None = None) -> None:
        for key, instance in self.instances.items():
            if instance.plugin_id == plugin_id and (connection_id is None or connection_id == key):
                self.registry.require_mutable(key)
        if self._guard_mutation is not None:
            self._guard_mutation(plugin_id, connection_id)

    async def close(self) -> None:
        failures: list[BaseException] = []
        for connection_id, instance in reversed(tuple(self.instances.items())):
            self.registry.release(connection_id)
            try:
                await instance.shutdown()
            except BaseException as exc:
                failures.append(exc)
        self.instances.clear()
        for dispose in reversed(self._disposers):
            dispose()
        self._disposers.clear()
        for name in tuple(sys.modules):
            if any(name == root or name.startswith(root + ".") for root in self._module_names):
                sys.modules.pop(name, None)
        self._module_names.clear()
        if failures:
            raise failures[0]
