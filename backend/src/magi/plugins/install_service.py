"""High-level plugin install workflows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
from typing import Any

from magi_plugin_sdk.versioning import is_plugin_version_newer

from ..config import PluginSettings, get_config
from .operation_execution import run_plugin_archive_operation, run_plugin_preparation_operation
from .contracts import (
    PluginCapability,
    PluginManifest,
    PluginPackageState,
    PluginRegistryEntry,
)
from .discovery import load_plugin_manifest
from .dependency_installation import PluginDependencyWorkflowBudget
from .install_admission import (
    PluginInstallAdmissionLease,
    plugin_install_admission,
)
from .installation import (
    PluginDirectoryInstallOutcome,
    PluginDependencyValidationError,
    PluginPackageConflictError,
    PluginRegistrySourceConflictError,
)
from .package_identity import verify_package_sha256
from .package_integrity import (
    has_registry_install_record,
    is_verified_registry_package,
)
from . import package_files
from .registry_client import PluginRegistryClient
from .registry_client import PluginRegistrySnapshot
from .provisional_dependencies import (
    ProvisionalDependencyConflictError,
    ProvisionalDependencyCoordinator,
    ProvisionalDependencyLease,
    ProvisionalLibraryFinalizer,
    ProvisionalLibraryReceipt,
    ProvisionalLibraryRequirement,
    provisional_dependency_coordinator,
)


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


class PluginInstallApprovalMismatchError(ValueError):
    """Raised when a staged archive no longer matches the inspected manifest."""


class PluginSideloadConflictError(ValueError):
    """Raised when a sideload archive would replace an installed plugin."""


class PluginRegistrySnapshotMismatchError(ValueError):
    """Raised when marketplace consent no longer matches the registry."""


class PluginRegistryVersionError(ValueError):
    """Raised when a marketplace update does not advance the package version."""


PluginDependencyConflictError = PluginDependencyValidationError
MAX_PLUGIN_DEPENDENCY_CLOSURE = 16


def registry_source_matches_installed_package(
    state: PluginPackageState,
    snapshot: PluginRegistrySnapshot,
) -> bool:
    """Return whether last-verified state belongs to this exact registry source."""

    manifest = state.manifest
    configured = get_config().plugins.packages.get(manifest.plugin_id)
    if isinstance(configured, dict):
        configured = PluginSettings.model_validate(configured)
    return bool(
        state.trusted
        and has_registry_install_record(manifest, configured)
        and configured is not None
        and configured.registry_source == snapshot.registry_url
        and configured.registry_repo_url == snapshot.repo_url
    )


@dataclass(frozen=True)
class PluginRegistryInstallResult:
    """Result of installing a registry plugin and its dependency closure."""

    target_state: PluginPackageState
    extra_installed: list[str]


class PluginInstallService:
    """Coordinate plugin install, update, and uninstall workflows."""

    def __init__(
        self,
        *,
        registry_client: PluginRegistryClient,
        plugin_manager: Any | None,
        provisional_coordinator: ProvisionalDependencyCoordinator | None = None,
    ) -> None:
        self._registry_client = registry_client
        self._plugin_manager = plugin_manager
        self._provisional_coordinator = (
            provisional_coordinator or provisional_dependency_coordinator
        )

    async def install_from_registry(
        self,
        plugin_id: str,
        *,
        expected_fingerprint: str,
        progress_reporter=None,
        admission_lease: PluginInstallAdmissionLease | None = None,
    ) -> PluginRegistryInstallResult:
        """Install a plugin and any missing registry-declared dependencies."""

        lease, owns_lease = self._resolve_admission(plugin_id, admission_lease)
        try:
            return await self._install_from_registry_admitted(
                plugin_id,
                expected_fingerprint=expected_fingerprint,
                progress_reporter=progress_reporter,
            )
        finally:
            if owns_lease:
                lease.release()

    async def _install_from_registry_admitted(
        self,
        plugin_id: str,
        *,
        expected_fingerprint: str,
        progress_reporter=None,
        expected_registry_update_source: tuple[str, str] | None = None,
    ) -> PluginRegistryInstallResult:
        self._require_manager()
        if expected_registry_update_source is None:
            self._assert_registry_install_target_available(plugin_id)
        workflow_budget = PluginDependencyWorkflowBudget()
        snapshot = await self._expected_registry_snapshot(
            expected_fingerprint,
            workflow_budget=workflow_budget,
        )
        if (
            expected_registry_update_source is not None
            and (
                snapshot.registry_url,
                snapshot.repo_url,
            )
            != expected_registry_update_source
        ):
            raise PluginRegistrySourceConflictError(
                "The installed plugin comes from a different source. "
                "Uninstall it before installing from this marketplace."
            )
        entries_by_id = self._snapshot_entries(snapshot)
        entry = self._fetch_installable_entry(entries_by_id, plugin_id)
        if expected_registry_update_source is not None:
            installed = self._require_manager().get_package(plugin_id)
            if installed is None or not is_plugin_version_newer(
                entry.version,
                installed.manifest.version,
            ):
                raise PluginRegistryVersionError(
                    "Marketplace updates must use a newer plugin version"
                )
        full_closure = self._resolve_install_closure(
            entry.plugin_id,
            snapshot=snapshot,
            entries_by_id=entries_by_id,
            already_installed=set(),
        )
        try:
            provisional_lease = await _acquire_provisional_dependencies(
                self._provisional_coordinator,
                self._provisional_library_requirements(
                    full_closure,
                    snapshot=snapshot,
                ),
            )
        except ProvisionalDependencyConflictError as exc:
            raise PluginDependencyConflictError(str(exc)) from exc

        try:
            installed_plugin_ids = self._installed_plugin_ids()
            order = await run_plugin_preparation_operation(
                lambda: self._resolve_install_closure(
                    entry.plugin_id,
                    snapshot=snapshot,
                    entries_by_id=entries_by_id,
                    already_installed=installed_plugin_ids,
                )
            )
            temp_root = Path(tempfile.mkdtemp(prefix="magi-plugin-dl-"))
            try:
                prepared: list[tuple[PluginRegistryEntry, Path, PluginManifest]] = []
                for item in order:
                    workflow_budget.ensure_time_remaining()
                    plugin_dir = await self._registry_client.clone_plugin(
                        item,
                        snapshot=snapshot,
                        dest_dir=temp_root,
                        deadline_monotonic=workflow_budget.deadline_monotonic,
                    )
                    manifest = await run_plugin_preparation_operation(
                        lambda item=item, plugin_dir=plugin_dir: (
                            workflow_budget.consume((plugin_dir,)),
                            _validate_registry_package_directory(plugin_dir, item),
                        )[1]
                    )
                    workflow_budget.ensure_time_remaining()
                    await self._assert_registry_snapshot_current(
                        expected_fingerprint,
                        workflow_budget=workflow_budget,
                    )
                    prepared.append((item, plugin_dir, manifest))

                extra_installed: list[str] = []
                target_state: PluginPackageState | None = None
                for item, plugin_dir, manifest in prepared:
                    state = await self._install_prepared_registry_entry(
                        item,
                        plugin_dir=plugin_dir,
                        manifest=manifest,
                        snapshot=snapshot,
                        entries_by_id=entries_by_id,
                        workflow_budget=workflow_budget,
                        provisional_lease=provisional_lease,
                        is_target=item.plugin_id == entry.plugin_id,
                        expected_registry_update_source=expected_registry_update_source,
                        progress_reporter=progress_reporter,
                    )
                    if item.plugin_id == entry.plugin_id:
                        target_state = state
                    else:
                        extra_installed.append(item.plugin_id)
            finally:
                await run_plugin_preparation_operation(lambda: shutil.rmtree(temp_root, True))
        finally:
            await self._release_provisional_dependencies(provisional_lease)

        assert target_state is not None
        return PluginRegistryInstallResult(
            target_state=target_state,
            extra_installed=extra_installed,
        )

    async def update_from_registry(
        self,
        plugin_id: str,
        *,
        expected_fingerprint: str,
        progress_reporter=None,
        admission_lease: PluginInstallAdmissionLease | None = None,
    ) -> PluginPackageState:
        """Update an already-installed external plugin from the registry."""

        lease, owns_lease = self._resolve_admission(plugin_id, admission_lease)
        try:
            return await self._update_from_registry_admitted(
                plugin_id,
                expected_fingerprint=expected_fingerprint,
                progress_reporter=progress_reporter,
            )
        finally:
            if owns_lease:
                lease.release()

    async def _update_from_registry_admitted(
        self,
        plugin_id: str,
        *,
        expected_fingerprint: str,
        progress_reporter=None,
    ) -> PluginPackageState:
        manager = self._require_manager()
        state = manager.get_package(plugin_id)
        if state is None:
            raise PluginPackageNotInstalled(plugin_id)
        if state.manifest.source == "builtin":
            raise BuiltinPluginUpdateError()
        configured = get_config().plugins.packages.get(plugin_id)
        if isinstance(configured, dict):
            configured = PluginSettings.model_validate(configured)
        package_is_verified = await run_plugin_preparation_operation(
            lambda: is_verified_registry_package(state.manifest, configured)
        )
        if not package_is_verified:
            raise PluginRegistrySourceConflictError(
                "The installed plugin does not have a verified marketplace source. "
                "Uninstall it before installing from this marketplace."
            )
        assert configured is not None
        assert configured.registry_source is not None
        assert configured.registry_repo_url is not None

        result = await self._install_from_registry_admitted(
            plugin_id,
            expected_fingerprint=expected_fingerprint,
            progress_reporter=progress_reporter,
            expected_registry_update_source=(
                configured.registry_source,
                configured.registry_repo_url,
            ),
        )
        return result.target_state

    async def install_from_archive(
        self,
        archive_path: Path,
        *,
        approved_manifest: PluginManifest,
        approved_package_sha256: str,
        consented_capabilities: list[PluginCapability],
        progress_reporter=None,
        admission_lease: PluginInstallAdmissionLease | None = None,
    ) -> PluginPackageState:
        """Install a plugin from an uploaded archive."""

        plugin_id = approved_manifest.plugin_id
        lease, owns_lease = self._resolve_admission(plugin_id, admission_lease)
        try:
            return await self._install_from_archive_admitted(
                archive_path,
                approved_manifest=approved_manifest,
                approved_package_sha256=approved_package_sha256,
                consented_capabilities=consented_capabilities,
                progress_reporter=progress_reporter,
            )
        finally:
            if owns_lease:
                lease.release()

    async def _install_from_archive_admitted(
        self,
        archive_path: Path,
        *,
        approved_manifest: PluginManifest,
        approved_package_sha256: str,
        consented_capabilities: list[PluginCapability],
        progress_reporter=None,
    ) -> PluginPackageState:
        manager = self._require_manager()

        def install_approved_archive() -> PluginPackageState:
            if manager.get_package(approved_manifest.plugin_id) is not None:
                raise PluginSideloadConflictError(
                    f"Plugin is already installed: {approved_manifest.plugin_id}"
                )
            inspection = manager.inspect_plugin_archive(archive_path)
            if inspection.package_sha256 != approved_package_sha256:
                raise PluginInstallApprovalMismatchError(
                    "Plugin package no longer matches the inspected content"
                )
            if _approval_manifest_payload(inspection.manifest) != _approval_manifest_payload(
                approved_manifest
            ):
                raise PluginInstallApprovalMismatchError(
                    "Plugin package no longer matches the inspected manifest"
                )
            return manager.install_plugin_from_archive(
                archive_path,
                expected_package_sha256=approved_package_sha256,
                consented_capabilities=consented_capabilities,
                progress_reporter=progress_reporter,
            )

        return await run_plugin_archive_operation(install_approved_archive)

    def uninstall(self, plugin_id: str) -> list[str]:
        """Uninstall a plugin package."""

        return self._require_manager().uninstall_plugin(plugin_id)

    async def _install_prepared_registry_entry(
        self,
        entry: PluginRegistryEntry,
        *,
        plugin_dir: Path,
        manifest: PluginManifest,
        snapshot: PluginRegistrySnapshot,
        entries_by_id: dict[str, PluginRegistryEntry],
        workflow_budget: PluginDependencyWorkflowBudget,
        provisional_lease: ProvisionalDependencyLease,
        is_target: bool,
        expected_registry_update_source: tuple[str, str] | None,
        progress_reporter=None,
    ) -> PluginPackageState:
        if progress_reporter is not None:
            label = "Installing" if is_target else "Installing dependency"
            progress_reporter("install", f"{label}: {entry.name}", None)
        if entry.kind == "library" and self._plugin_manager is not None:
            existing = self._plugin_manager.get_package(entry.plugin_id)
            if existing is not None:
                await run_plugin_preparation_operation(
                    lambda: self._assert_installed_library_reusable(
                        entry,
                        snapshot=snapshot,
                        entries_by_id=entries_by_id,
                    )
                )
                return existing
        dependency_package_sha256 = {
            dep_id: entries_by_id[dep_id].package_sha256 for dep_id in entry.depends_on
        }
        effective_official = bool(snapshot.official_source and entry.official)
        if self._plugin_manager is None:
            raise RuntimeError("Plugin manager is not initialized")

        def report_install_outcome(outcome: PluginDirectoryInstallOutcome) -> None:
            if entry.kind != "library" or not outcome.created_by_this_commit:
                return
            provisional_lease.register_created(
                self._provisional_library_receipt(
                    entry,
                    outcome=outcome,
                    snapshot=snapshot,
                    dependency_package_sha256=dependency_package_sha256,
                ),
                self._detach_provisional_library,
            )

        state = await _run_plugin_preparation_to_completion(
            lambda: self._plugin_manager.install_plugin_from_directory(
                plugin_dir,
                progress_reporter=progress_reporter,
                official=effective_official,
                consented_capabilities=list(entry.capabilities),
                install_origin="registry",
                registry_source=snapshot.registry_url,
                registry_repo_url=snapshot.repo_url,
                package_sha256=entry.package_sha256,
                dependency_package_sha256=dependency_package_sha256,
                dependency_workflow_budget=workflow_budget,
                reject_existing=is_target and expected_registry_update_source is None,
                expected_registry_update_source=(
                    expected_registry_update_source if is_target else None
                ),
                install_outcome_reporter=report_install_outcome,
            )
        )
        return state

    @staticmethod
    def _provisional_library_requirements(
        order: list[PluginRegistryEntry],
        *,
        snapshot: PluginRegistrySnapshot,
    ) -> tuple[ProvisionalLibraryRequirement, ...]:
        """Return dependency-first exact claims for every library in a closure."""

        return tuple(
            ProvisionalLibraryRequirement(
                plugin_id=entry.plugin_id,
                registry_source=snapshot.registry_url,
                registry_repo_url=snapshot.repo_url,
                package_sha256=entry.package_sha256,
            )
            for entry in order
            if entry.kind == "library"
        )

    @staticmethod
    def _provisional_library_receipt(
        entry: PluginRegistryEntry,
        *,
        outcome: PluginDirectoryInstallOutcome,
        snapshot: PluginRegistrySnapshot,
        dependency_package_sha256: dict[str, str],
    ) -> ProvisionalLibraryReceipt:
        return ProvisionalLibraryReceipt(
            requirement=ProvisionalLibraryRequirement(
                plugin_id=entry.plugin_id,
                registry_source=snapshot.registry_url,
                registry_repo_url=snapshot.repo_url,
                package_sha256=entry.package_sha256,
            ),
            dependency_package_sha256=tuple(sorted(dependency_package_sha256.items())),
            plugin_dir=outcome.plugin_dir,
            manifest_path=outcome.manifest_path,
            destination_identity=outcome.destination_identity,
            manifest_identity=outcome.manifest_identity,
        )

    async def _release_provisional_dependencies(
        self,
        lease: ProvisionalDependencyLease,
    ) -> None:
        """Release one closure and delete only exact newly orphaned libraries."""

        await _run_plugin_preparation_to_completion(lease.release)

    def _detach_provisional_library(
        self,
        receipt: ProvisionalLibraryReceipt,
    ) -> ProvisionalLibraryFinalizer | None:
        """Detach an orphan through its creator and return slow finalization."""

        manager = self._require_manager()
        detached_dir = manager.remove_provisional_registry_library(receipt)
        if detached_dir is None:
            return None

        def finalize() -> bool:
            package_files.discard_plugin_transaction_directory(detached_dir)
            if detached_dir.exists():
                raise RuntimeError(
                    "Failed to delete detached provisional dependency: "
                    f"{receipt.requirement.plugin_id}"
                )
            return True

        return finalize

    def _assert_registry_install_target_available(self, plugin_id: str) -> None:
        manager_state = None
        if self._plugin_manager is not None:
            get_package = getattr(self._plugin_manager, "get_package", None)
            if callable(get_package):
                manager_state = get_package(plugin_id)
            elif plugin_id in self._installed_plugin_ids():
                manager_state = True
        if manager_state is not None or package_files.managed_plugin_directory(plugin_id).exists():
            raise PluginPackageConflictError(
                f"Plugin is already installed: {plugin_id}. "
                "Update it from its original source or uninstall it first."
            )

    def _resolve_install_closure(
        self,
        target_id: str,
        *,
        snapshot: PluginRegistrySnapshot,
        entries_by_id: dict[str, PluginRegistryEntry],
        already_installed: set[str],
    ) -> list[PluginRegistryEntry]:
        install_order: list[PluginRegistryEntry] = []
        visiting: set[str] = set()
        resolved: set[str] = set()

        def visit(plugin_id: str, *, is_target: bool = False) -> None:
            if plugin_id in resolved:
                return
            if plugin_id in visiting:
                raise ValueError(f"Cyclic plugin dependency detected involving {plugin_id}")
            if len(resolved) + len(visiting) >= MAX_PLUGIN_DEPENDENCY_CLOSURE:
                raise ValueError("Plugin dependency closure exceeds the supported package limit")
            entry = self._fetch_registry_entry(entries_by_id, plugin_id)
            if is_target:
                if entry.kind != "plugin":
                    raise DirectLibraryInstallError(
                        "Library components cannot be installed directly."
                    )
            elif entry.kind != "library":
                raise DirectLibraryInstallError(
                    "Plugin dependencies must be library packages; "
                    f"{plugin_id} is a runnable plugin."
                )
            is_reused_dependency = not is_target and plugin_id in already_installed
            if is_reused_dependency:
                self._assert_installed_library_reusable(
                    entry,
                    snapshot=snapshot,
                    entries_by_id=entries_by_id,
                )

            visiting.add(plugin_id)
            try:
                for dep_id in entry.depends_on:
                    visit(dep_id)
            finally:
                visiting.discard(plugin_id)
            resolved.add(plugin_id)
            if not is_reused_dependency:
                install_order.append(entry)

        visit(target_id, is_target=True)
        return install_order

    @staticmethod
    def _fetch_installable_entry(
        entries_by_id: dict[str, PluginRegistryEntry],
        plugin_id: str,
    ) -> PluginRegistryEntry:
        entry = PluginInstallService._fetch_registry_entry(entries_by_id, plugin_id)
        if entry.kind == "library":
            raise DirectLibraryInstallError(
                "Library components are installed automatically as plugin dependencies "
                "and cannot be installed directly."
            )
        return entry

    @staticmethod
    def _fetch_registry_entry(
        entries_by_id: dict[str, PluginRegistryEntry],
        plugin_id: str,
    ) -> PluginRegistryEntry:
        entry = entries_by_id.get(plugin_id)
        if entry is None:
            raise PluginRegistryEntryNotFound(plugin_id)
        return entry

    @staticmethod
    def _snapshot_entries(
        snapshot: PluginRegistrySnapshot,
    ) -> dict[str, PluginRegistryEntry]:
        entries: dict[str, PluginRegistryEntry] = {}
        for entry in snapshot.index.plugins:
            if entry.plugin_id in entries:
                raise ValueError(f"Duplicate plugin id in registry: {entry.plugin_id}")
            entries[entry.plugin_id] = entry
        return entries

    async def _expected_registry_snapshot(
        self,
        expected_fingerprint: str,
        *,
        workflow_budget: PluginDependencyWorkflowBudget,
    ) -> PluginRegistrySnapshot:
        snapshot = await self._registry_client.fetch_snapshot(
            deadline_monotonic=workflow_budget.deadline_monotonic,
        )
        self.assert_expected_registry_fingerprint(snapshot, expected_fingerprint)
        return snapshot

    async def _assert_registry_snapshot_current(
        self,
        expected_fingerprint: str,
        *,
        workflow_budget: PluginDependencyWorkflowBudget,
    ) -> None:
        snapshot = await self._registry_client.fetch_snapshot(
            deadline_monotonic=workflow_budget.deadline_monotonic,
        )
        self.assert_expected_registry_fingerprint(snapshot, expected_fingerprint)

    @staticmethod
    def assert_expected_registry_fingerprint(
        snapshot: PluginRegistrySnapshot,
        expected_fingerprint: str,
    ) -> None:
        if snapshot.install_fingerprint != expected_fingerprint:
            raise PluginRegistrySnapshotMismatchError("Plugin registry changed after approval")

    def _assert_installed_library_reusable(
        self,
        entry: PluginRegistryEntry,
        *,
        snapshot: PluginRegistrySnapshot,
        entries_by_id: dict[str, PluginRegistryEntry],
    ) -> None:
        raw_configured = get_config().plugins.packages.get(entry.plugin_id)
        configured = (
            PluginSettings.model_validate(raw_configured) if raw_configured is not None else None
        )
        state = (
            self._plugin_manager.get_package(entry.plugin_id)
            if self._plugin_manager is not None
            else None
        )
        if configured is None or state is None:
            raise PluginDependencyConflictError(
                f"Installed dependency {entry.plugin_id} must be removed and reinstalled"
            )

        expected_dependency_package_sha256 = {
            dependency_id: self._fetch_registry_entry(
                entries_by_id,
                dependency_id,
            ).package_sha256
            for dependency_id in entry.depends_on
        }
        manifest = state.manifest
        valid = (
            manifest.kind == "library"
            and state.trusted
            and configured.trusted
            and configured.install_origin == "registry"
            and configured.registry_source == snapshot.registry_url
            and configured.registry_repo_url == snapshot.repo_url
            and configured.package_sha256 == entry.package_sha256
            and configured.dependency_package_sha256 == expected_dependency_package_sha256
            and is_verified_registry_package(manifest, configured)
        )
        if valid:
            try:
                validate_registry_package(entry, manifest)
            except ValueError:
                valid = False
        if not valid:
            raise PluginDependencyConflictError(
                f"Installed dependency {entry.plugin_id} does not match the approved registry "
                "package; uninstall it before retrying"
            )

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
    def _resolve_admission(
        plugin_id: str,
        supplied: PluginInstallAdmissionLease | None,
    ) -> tuple[PluginInstallAdmissionLease, bool]:
        if supplied is not None:
            if supplied.plugin_id != plugin_id:
                raise ValueError("Plugin install admission does not match the requested package")
            return supplied, False
        return plugin_install_admission.acquire(plugin_id), True


async def _run_plugin_preparation_to_completion(operation):
    """Let a lifecycle commit finish before cancellation releases its claims."""

    task = asyncio.create_task(run_plugin_preparation_operation(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except BaseException:
            pass
        raise


async def _acquire_provisional_dependencies(
    coordinator: ProvisionalDependencyCoordinator,
    requirements: tuple[ProvisionalLibraryRequirement, ...],
) -> ProvisionalDependencyLease:
    """Acquire off-loop and release any lease produced after caller cancellation."""

    task = asyncio.create_task(
        run_plugin_preparation_operation(lambda: coordinator.acquire(requirements))
    )
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        lease: ProvisionalDependencyLease | None = None
        try:
            lease = await task
        except BaseException:
            pass
        if lease is not None:
            await _run_plugin_preparation_to_completion(lease.release)
        raise


def _validate_registry_package_directory(
    source_dir: Path,
    entry: PluginRegistryEntry,
) -> PluginManifest:
    manifest_file = package_files.find_plugin_manifest_in_tree(source_dir)
    if manifest_file is None:
        raise ValueError("Registry package does not contain a plugin.toml")
    verify_package_sha256(
        manifest_file.parent,
        entry.package_sha256,
    )
    manifest = load_plugin_manifest(manifest_file, source="external")
    validate_registry_package(entry, manifest)
    return manifest


def validate_registry_package(
    entry: PluginRegistryEntry,
    manifest: PluginManifest,
) -> None:
    """Bind every shared registry declaration to the extracted manifest."""

    expected: dict[str, Any] = {
        "plugin_id": entry.plugin_id,
        "name": entry.name,
        "name_i18n": entry.name_i18n,
        "version": entry.version,
        "description": entry.description,
        "description_i18n": entry.description_i18n,
        "author": entry.author,
        "icon": entry.icon,
        "data_locality": entry.data_locality,
        "kind": entry.kind,
        "contribution_types": list(entry.contribution_types),
        "depends_on": list(entry.depends_on),
        "platforms": list(entry.platforms),
        "min_sdk_version": entry.min_sdk_version,
        "homepage": entry.homepage,
        "repository": entry.repository,
        "suggestion_descriptor": (
            entry.suggestion_descriptor.model_dump(mode="json")
            if entry.suggestion_descriptor is not None
            else None
        ),
        "capabilities": [capability.model_dump(mode="json") for capability in entry.capabilities],
        "display_group": (
            entry.display_group.model_dump(mode="json") if entry.display_group is not None else None
        ),
    }
    actual: dict[str, Any] = {
        "plugin_id": manifest.plugin_id,
        "name": manifest.name,
        "name_i18n": manifest.name_i18n,
        "version": manifest.version,
        "description": manifest.description,
        "description_i18n": manifest.description_i18n,
        "author": manifest.author,
        "icon": manifest.icon,
        "data_locality": manifest.data_locality
        or (
            manifest.suggestion_descriptor.data_locality
            if manifest.suggestion_descriptor is not None
            else ""
        ),
        "kind": manifest.kind,
        "contribution_types": [
            contribution_type.value for contribution_type in manifest.contribution_types
        ],
        "depends_on": list(manifest.depends_on),
        "platforms": list(manifest.platforms),
        "min_sdk_version": manifest.min_sdk_version,
        "homepage": manifest.homepage,
        "repository": manifest.repository,
        "suggestion_descriptor": (
            manifest.suggestion_descriptor.model_dump(mode="json")
            if manifest.suggestion_descriptor is not None
            else None
        ),
        "capabilities": [
            capability.model_dump(mode="json") for capability in manifest.capabilities
        ],
        "display_group": (
            manifest.display_group.model_dump(mode="json")
            if manifest.display_group is not None
            else None
        ),
    }
    comparable_fields = set(expected)
    for registry_optional_field in {
        "min_sdk_version",
        "homepage",
        "repository",
    }:
        if registry_optional_field not in entry.model_fields_set:
            comparable_fields.discard(registry_optional_field)

    mismatched_fields = [
        field_name
        for field_name in expected
        if field_name in comparable_fields and actual[field_name] != expected[field_name]
    ]
    if mismatched_fields:
        raise ValueError(
            "Registry package manifest does not match its index entry: "
            + ", ".join(mismatched_fields)
        )


def _approval_manifest_payload(manifest: PluginManifest) -> dict[str, Any]:
    return manifest.model_dump(
        mode="json",
        by_alias=True,
        exclude={"plugin_dir", "manifest_path", "source"},
    )
