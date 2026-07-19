"""High-level plugin install workflows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
from typing import Any

from ..config import get_config, save_config
from .contracts import (
    ContributionType,
    PluginManifest,
    PluginPackageState,
    PluginPermissions,
    PluginRegistryEntry,
)
from .discovery import load_plugin_manifest
from . import package_files
from .registry_client import PluginRegistryClient


class PluginRegistryEntryNotFound(LookupError):
    """Raised when a requested plugin is missing from the registry."""

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        super().__init__(f"Plugin not found in registry: {plugin_id}")


class PluginPackageNotInstalled(LookupError):
    """Raised when an update targets a package that is not installed."""

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        super().__init__(f"Plugin not installed: {plugin_id}")


class BuiltinPluginUpdateError(ValueError):
    """Raised when an update targets a builtin plugin."""

    def __init__(self) -> None:
        super().__init__("Cannot update builtin plugins")


class DirectLibraryInstallError(ValueError):
    """Raised when a user directly installs a library package."""


@dataclass(frozen=True)
class PluginRegistryInstallResult:
    """Result of installing a registry plugin and its dependency closure."""

    target_state: PluginPackageState
    extra_installed: list[str]
    used_runtime_manager: bool


class PluginInstallService:
    """Coordinate plugin install, update, and uninstall workflows."""

    def __init__(
        self,
        *,
        registry_client: PluginRegistryClient,
        plugin_manager: Any | None,
    ) -> None:
        self._registry_client = registry_client
        self._plugin_manager = plugin_manager

    async def install_from_registry(
        self,
        plugin_id: str,
        *,
        progress_reporter=None,
    ) -> PluginRegistryInstallResult:
        """Install a plugin and any missing registry-declared dependencies."""

        entry = await self._fetch_installable_entry(plugin_id)
        order = await self._resolve_install_closure(
            entry.plugin_id,
            already_installed=self._installed_plugin_ids(),
        )
        if not order:
            order = [entry]

        temp_root = Path(tempfile.mkdtemp(prefix="magi-plugin-dl-"))
        try:
            extra_installed: list[str] = []
            target_state: PluginPackageState | None = None
            for item in order:
                state = await self._install_registry_entry(
                    item,
                    is_target=item.plugin_id == entry.plugin_id,
                    temp_root=temp_root,
                    progress_reporter=progress_reporter,
                )
                if item.plugin_id == entry.plugin_id:
                    target_state = state
                else:
                    extra_installed.append(item.plugin_id)
        finally:
            await asyncio.to_thread(shutil.rmtree, temp_root, True)

        assert target_state is not None
        return PluginRegistryInstallResult(
            target_state=target_state,
            extra_installed=extra_installed,
            used_runtime_manager=self._plugin_manager is not None,
        )

    async def update_from_registry(
        self,
        plugin_id: str,
        *,
        progress_reporter=None,
    ) -> PluginPackageState:
        """Update an already-installed external plugin from the registry."""

        manager = self._require_manager()
        state = manager.get_package(plugin_id)
        if state is None:
            raise PluginPackageNotInstalled(plugin_id)
        if state.manifest.source == "builtin":
            raise BuiltinPluginUpdateError()

        entry = await self._fetch_registry_entry(plugin_id)
        temp_root = Path(tempfile.mkdtemp(prefix="magi-plugin-dl-"))
        try:
            plugin_dir = await self._registry_client.clone_plugin(entry, dest_dir=temp_root)
            new_state = await asyncio.to_thread(
                manager.install_plugin_from_directory,
                plugin_dir,
                progress_reporter=progress_reporter,
            )
            self._persist_registry_metadata(entry)
            return new_state
        finally:
            await asyncio.to_thread(shutil.rmtree, temp_root, True)

    async def install_from_archive(
        self,
        archive_path: Path,
        *,
        progress_reporter=None,
    ) -> PluginPackageState:
        """Install a plugin from an uploaded archive."""

        manager = self._require_manager()
        return await asyncio.to_thread(
            manager.install_plugin_from_archive,
            archive_path,
            progress_reporter=progress_reporter,
        )

    def uninstall(self, plugin_id: str) -> list[str]:
        """Uninstall a plugin package."""

        return self._require_manager().uninstall_plugin(plugin_id)

    async def _install_registry_entry(
        self,
        entry: PluginRegistryEntry,
        *,
        is_target: bool,
        temp_root: Path,
        progress_reporter=None,
    ) -> PluginPackageState:
        if progress_reporter is not None:
            label = "Installing" if is_target else "Installing dependency"
            progress_reporter("install", f"{label}: {entry.name}", None)
        plugin_dir = await self._registry_client.clone_plugin(entry, dest_dir=temp_root)
        if self._plugin_manager is None:
            return await asyncio.to_thread(_lightweight_install, plugin_dir, entry)

        state = await asyncio.to_thread(
            self._plugin_manager.install_plugin_from_directory,
            plugin_dir,
            progress_reporter=progress_reporter,
        )
        self._persist_registry_metadata(entry)
        return state

    async def _resolve_install_closure(
        self,
        target_id: str,
        *,
        already_installed: set[str],
    ) -> list[PluginRegistryEntry]:
        install_order: list[PluginRegistryEntry] = []
        visiting: set[str] = set()
        resolved: set[str] = set()

        async def visit(plugin_id: str) -> None:
            if plugin_id in resolved or plugin_id in already_installed:
                return
            if plugin_id in visiting:
                raise ValueError(f"Cyclic plugin dependency detected involving {plugin_id}")
            entry = await self._fetch_registry_entry(plugin_id)
            visiting.add(plugin_id)
            for dep_id in entry.depends_on:
                await visit(dep_id)
            visiting.discard(plugin_id)
            resolved.add(plugin_id)
            install_order.append(entry)

        await visit(target_id)
        return install_order

    async def _fetch_installable_entry(self, plugin_id: str) -> PluginRegistryEntry:
        entry = await self._fetch_registry_entry(plugin_id)
        if entry.kind == "library":
            raise DirectLibraryInstallError(
                "Library components are installed automatically as plugin dependencies "
                "and cannot be installed directly."
            )
        return entry

    async def _fetch_registry_entry(self, plugin_id: str) -> PluginRegistryEntry:
        entry = await self._registry_client.fetch_entry(plugin_id)
        if entry is None:
            raise PluginRegistryEntryNotFound(plugin_id)
        return entry

    def _installed_plugin_ids(self) -> set[str]:
        manager = self._plugin_manager
        if manager is not None:
            installed_plugin_ids = getattr(manager, "installed_plugin_ids", None)
            if callable(installed_plugin_ids):
                return set(installed_plugin_ids())
            return {state.manifest.plugin_id for state in manager.list_packages()}
        return set(get_config().plugins.packages.keys())

    def _require_manager(self) -> Any:
        if self._plugin_manager is None:
            raise RuntimeError("Plugin manager is not initialized")
        return self._plugin_manager

    @staticmethod
    def _persist_registry_metadata(entry: PluginRegistryEntry) -> None:
        updates = {
            f"plugins.packages.{entry.plugin_id}.official": bool(entry.official),
            f"plugins.packages.{entry.plugin_id}.consented_capabilities": [
                capability.model_dump() for capability in entry.capabilities
            ],
        }
        save_config(updates)


def _lightweight_install(source_dir: Path, entry: PluginRegistryEntry) -> PluginPackageState:
    """Install plugin files without a running PluginManager."""

    manifest_file = package_files.find_plugin_manifest_in_tree(source_dir)
    if manifest_file is None:
        raise ValueError("Directory does not contain a plugin.toml")

    plugin_source = manifest_file.parent
    source_manifest = load_plugin_manifest(manifest_file, source="external")
    user_root = package_files.user_plugins_root()
    user_root.mkdir(parents=True, exist_ok=True)
    dest_dir = user_root / entry.plugin_id
    package_files.replace_plugin_directory(plugin_source, dest_dir)

    is_library = entry.kind == "library"
    package_config: dict[str, Any] = {"enabled": True}
    if is_library:
        package_config["trusted"] = True
    package_config["official"] = bool(entry.official)
    package_config["consented_capabilities"] = [
        capability.model_dump() for capability in entry.capabilities
    ]
    save_config({f"plugins.packages.{entry.plugin_id}": package_config})

    contribution_types: list[ContributionType] = []
    for raw_type in entry.contribution_types:
        try:
            contribution_types.append(ContributionType(raw_type))
        except ValueError:
            continue

    return PluginPackageState(
        manifest=PluginManifest(
            id=entry.plugin_id,
            name=entry.name,
            version=entry.version,
            description=entry.description,
            author=entry.author,
            icon=source_manifest.icon,
            official=entry.official,
            kind=entry.kind,
            contribution_types=contribution_types,
            depends_on=list(entry.depends_on),
            platforms=entry.platforms,
            plugin_dir=str(dest_dir),
            source="external",
            permissions=PluginPermissions(capabilities=list(entry.capabilities)),
        ),
        enabled=True,
        trusted=is_library,
        loaded=False,
        healthy=True,
    )
