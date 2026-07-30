"""Plugin package installation and removal helpers."""

from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path
import shutil
import tempfile
import uuid
from dataclasses import dataclass

from . import package_files
from ..config import PluginSettings, delete_plugin_package, get_config, save_config
from .operation_execution import plugin_preparation_slot, serialize_plugin_archive_operation
from .contracts import PluginCapability, PluginManifest, PluginPackageState
from .discovery import load_plugin_manifest
from .icon_assets import resolve_plugin_icon
from .package_integrity import package_identity_error
from .registry_provenance import plugin_manifest_fingerprint
from .provisional_dependencies import (
    DirectoryIdentity,
    PathIdentity,
    ProvisionalLibraryReceipt,
)
from .dependency_installation import (
    ALLOW_UNLOCKED_DEPS_ENV,
    BACKEND_PYTHON_ENV,
    PLUGIN_DEPENDENCY_PYTHON_ENV,
    InstallProgressReporter,
    PluginDependencyWorkflowBudget,
    UnlockedDependencyError,
    _build_dependency_install_command,
    _build_loose_dependency_install_command,
    _developer_mode_allows_unlocked,
    _resolve_lock_or_policy,
    _run_dependency_install_with_progress,
    install_plugin_dependencies,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ALLOW_UNLOCKED_DEPS_ENV",
    "BACKEND_PYTHON_ENV",
    "PLUGIN_DEPENDENCY_PYTHON_ENV",
    "InstallProgressReporter",
    "PluginDependencyValidationError",
    "PluginInstallationMixin",
    "PluginDirectoryInstallOutcome",
    "PluginPackageConflictError",
    "PluginRegistrySourceConflictError",
    "UnlockedDependencyError",
    "_build_dependency_install_command",
    "_build_loose_dependency_install_command",
    "_developer_mode_allows_unlocked",
    "_resolve_lock_or_policy",
    "_run_dependency_install_with_progress",
]


class PluginDependencyValidationError(ValueError):
    """Raised when an installed package cannot satisfy a plugin dependency."""


class PluginPackageConflictError(ValueError):
    """Raised when an install would replace an existing package."""


class PluginRegistrySourceConflictError(ValueError):
    """Raised when a registry update does not match the installed source."""


def _report_install_progress(
    reporter: InstallProgressReporter | None,
    stage: str,
    message: str,
    progress_pct: float | None = None,
) -> None:
    if reporter is not None:
        reporter(stage, message, progress_pct)


def _prepare_user_plugins_root() -> Path:
    user_root = package_files.user_plugins_root()
    user_root.mkdir(parents=True, exist_ok=True)
    return user_root


def _extract_archive_manifest(archive_path: Path, tmp_path: Path) -> Path:
    package_files.extract_plugin_archive(archive_path, tmp_path)
    manifest_file = package_files.find_plugin_manifest_in_tree(tmp_path)
    if manifest_file is None:
        raise ValueError("Archive does not contain a plugin.toml")
    return manifest_file


def _find_directory_manifest(source_dir: Path) -> Path:
    manifest_file = package_files.find_plugin_manifest_in_tree(source_dir)
    if manifest_file is None:
        raise ValueError("Directory does not contain a plugin.toml")
    return manifest_file


def _resolve_plugin_destination(user_root: Path, plugin_id: str) -> Path:
    """Resolve one install target and keep it inside the user plugin root."""

    resolved_root = user_root.expanduser().resolve(strict=False)
    destination = (resolved_root / plugin_id).resolve(strict=False)
    if destination == resolved_root or not destination.is_relative_to(resolved_root):
        raise ValueError("Plugin install destination must remain inside the user plugin root")
    return destination


@dataclass(frozen=True)
class _PluginInstallPlan:
    manifest: PluginManifest
    plugin_id: str
    source_dir: Path
    dest_dir: Path


@dataclass(frozen=True)
class _PluginInstallSnapshot:
    package_state: PluginPackageState | None
    config: PluginSettings | None


@dataclass(frozen=True)
class _PluginInstallTarget:
    package_state: PluginPackageState | None
    destination_identity: tuple[int, int, int, int] | None
    manifest_identity: tuple[int, int, int, int] | None
    dependency_targets: tuple["_PluginDependencyTarget", ...] = ()


@dataclass(frozen=True)
class _PluginDependencyTarget:
    plugin_id: str
    package_state: PluginPackageState
    destination_identity: tuple[int, int, int, int] | None
    manifest_identity: tuple[int, int, int, int] | None
    registry_source: str
    registry_repo_url: str
    registry_entry_fingerprint: str
    registry_manifest_fingerprint: str


@dataclass(frozen=True)
class PluginDirectoryInstallOutcome:
    """Result metadata captured by the lifecycle-locked package commit."""

    state: PluginPackageState
    created_by_this_commit: bool
    plugin_dir: str
    manifest_path: str
    destination_identity: DirectoryIdentity
    manifest_identity: PathIdentity


class PluginInstallationMixin:
    """Install and uninstall user plugin packages."""

    _package_states: dict[str, PluginPackageState]

    def _load_manifest(self, manifest_path: Path, *, source: str) -> PluginManifest:
        raise NotImplementedError

    def _require_package(self, plugin_id: str) -> PluginPackageState:
        raise NotImplementedError

    def get_package(self, plugin_id: str) -> PluginPackageState | None:
        raise NotImplementedError

    def scan(self, *, persist_discovery: bool = True) -> list[PluginPackageState]:
        raise NotImplementedError

    def enable_plugin(self, plugin_id: str) -> PluginPackageState:
        raise NotImplementedError

    def load_plugin(self, plugin_id: str) -> PluginPackageState:
        raise NotImplementedError

    def unload_plugin(self, plugin_id: str) -> None:
        raise NotImplementedError

    @serialize_plugin_archive_operation
    def install_plugin_from_archive(
        self,
        archive_path: Path,
        *,
        consented_capabilities: list[PluginCapability],
        progress_reporter: InstallProgressReporter | None = None,
    ) -> PluginPackageState:
        """Install a plugin from a .tar.gz or .zip archive.

        The archive must contain a ``plugin.toml`` at the top level or
        inside exactly one subdirectory. The plugin is extracted into
        ``~/.magi/plugins/<plugin_id>/``.
        """
        user_root = _prepare_user_plugins_root()
        logger.info("Installing plugin from archive", extra={"archive_path": str(archive_path)})
        _report_install_progress(
            progress_reporter,
            "extract",
            "Extracting plugin archive",
            18.0,
        )

        with tempfile.TemporaryDirectory(prefix="magi-plugin-install-") as tmp:
            tmp_path = Path(tmp)
            manifest_file = _extract_archive_manifest(archive_path, tmp_path)
            plan = self._build_install_plan(
                manifest_file,
                user_root,
                install_origin="upload",
            )
            self._reject_sideload_overwrite(plan)
            self._log_install_plan(plan, message="Installing external plugin package")
            outcome = self._replace_plugin_package(
                plan,
                progress_reporter=progress_reporter,
                stage_message="Validating staged plugin package",
                activate_after_swap=False,
                consented_capabilities=consented_capabilities,
                install_origin="upload",
                reject_existing=True,
            )

        logger.info("Installed plugin from archive", extra={"plugin_id": plan.plugin_id})
        _report_install_progress(progress_reporter, "completed", "Plugin package installed", 100.0)
        return outcome.state

    @serialize_plugin_archive_operation
    def inspect_plugin_archive(self, archive_path: Path) -> PluginManifest:
        """Extract + read plugin.toml from an archive WITHOUT installing or
        persisting anything. Used to surface declared capabilities for the
        pre-install consent step (sideload)."""
        with tempfile.TemporaryDirectory(prefix="magi-plugin-inspect-") as tmp:
            tmp_path = Path(tmp)
            package_files.extract_plugin_archive(archive_path, tmp_path)
            manifest_file = package_files.find_plugin_manifest_in_tree(tmp_path)
            if manifest_file is None:
                raise ValueError("Archive does not contain a plugin.toml")
            manifest = self._load_manifest(manifest_file, source="external")
            self._reject_unmanaged_package_dependencies(
                manifest,
                install_origin="upload",
            )
            return manifest.model_copy(
                update={
                    "icon": resolve_plugin_icon(manifest.icon, manifest_file.parent),
                }
            )

    def install_plugin_from_directory(
        self,
        source_dir: Path,
        *,
        progress_reporter: InstallProgressReporter | None = None,
        official: bool | None = None,
        consented_capabilities: list[PluginCapability] | None = None,
        install_origin: str = "local",
        registry_source: str | None = None,
        registry_repo_url: str | None = None,
        registry_entry_fingerprint: str | None = None,
        registry_manifest_fingerprint: str | None = None,
        dependency_entry_fingerprints: dict[str, str] | None = None,
        dependency_workflow_budget: PluginDependencyWorkflowBudget | None = None,
        reject_existing: bool = False,
        expected_registry_update_source: tuple[str, str] | None = None,
        install_outcome_reporter: Callable[[PluginDirectoryInstallOutcome], None] | None = None,
    ) -> PluginPackageState:
        """Install a plugin from a local directory containing a plugin.toml."""
        if install_origin != "registry":
            reject_existing = True
        _report_install_progress(
            progress_reporter,
            "validate",
            "Validating plugin manifest",
            38.0,
        )
        manifest_file = _find_directory_manifest(source_dir)
        plan = self._build_install_plan(
            manifest_file,
            _prepare_user_plugins_root(),
            install_origin=install_origin,
        )
        self._log_install_plan(plan, message="Installing plugin from directory")
        outcome = self._replace_plugin_package(
            plan,
            progress_reporter=progress_reporter,
            stage_message="Preparing staged plugin package",
            activate_after_swap=True,
            official=official,
            consented_capabilities=consented_capabilities,
            install_origin=install_origin,
            registry_source=registry_source,
            registry_repo_url=registry_repo_url,
            registry_entry_fingerprint=registry_entry_fingerprint,
            registry_manifest_fingerprint=registry_manifest_fingerprint,
            dependency_entry_fingerprints=dependency_entry_fingerprints,
            dependency_workflow_budget=dependency_workflow_budget,
            reject_existing=reject_existing,
            expected_registry_update_source=expected_registry_update_source,
        )
        if install_outcome_reporter is not None:
            install_outcome_reporter(outcome)

        if plan.manifest.kind == "library":
            logger.info("Installed library package", extra={"plugin_id": plan.plugin_id})
        else:
            logger.info("Installed and enabled plugin", extra={"plugin_id": plan.plugin_id})
        _report_install_progress(progress_reporter, "completed", "Plugin package installed", 100.0)
        return outcome.state

    def _build_install_plan(
        self,
        manifest_file: Path,
        user_root: Path,
        *,
        install_origin: str,
    ) -> _PluginInstallPlan:
        manifest = self._load_manifest(manifest_file, source="external")
        plugin_id = manifest.plugin_id
        self._reject_builtin_overwrite(plugin_id)
        if install_origin != "registry":
            self._reject_host_reserved_package_id(plugin_id)
        return _PluginInstallPlan(
            manifest=manifest,
            plugin_id=plugin_id,
            source_dir=manifest_file.parent,
            dest_dir=_resolve_plugin_destination(user_root, plugin_id),
        )

    def _reject_builtin_overwrite(self, plugin_id: str) -> None:
        existing = self.get_package(plugin_id)
        if existing is not None and existing.manifest.source == "builtin":
            raise ValueError(f"Cannot overwrite builtin plugin: {plugin_id}")

    @staticmethod
    def _reject_host_reserved_package_id(plugin_id: str) -> None:
        configured = get_config().plugins.packages.get(plugin_id)
        if isinstance(configured, dict):
            configured = PluginSettings.model_validate(configured)
        if configured is not None and configured.source == "builtin":
            raise PluginPackageConflictError(
                f"Cannot replace an installed plugin package: {plugin_id}"
            )

    @staticmethod
    def _reject_unmanaged_package_dependencies(
        manifest: PluginManifest,
        *,
        install_origin: str,
    ) -> None:
        if manifest.depends_on and install_origin != "registry":
            raise PluginDependencyValidationError(
                "Plugins with package dependencies must be installed from the marketplace"
            )

    def _reject_sideload_overwrite(self, plan: _PluginInstallPlan) -> None:
        if self.get_package(plan.plugin_id) is not None or plan.dest_dir.exists():
            raise PluginPackageConflictError(
                f"Cannot replace an installed plugin package: {plan.plugin_id}"
            )

    @staticmethod
    def _assert_registry_update_source(
        plugin_id: str,
        expected_source: tuple[str, str],
    ) -> None:
        configured = get_config().plugins.packages.get(plugin_id)
        if isinstance(configured, dict):
            configured = PluginSettings.model_validate(configured)
        if (
            configured is None
            or configured.install_origin != "registry"
            or configured.registry_source != expected_source[0]
            or configured.registry_repo_url != expected_source[1]
        ):
            raise PluginRegistrySourceConflictError(
                "The installed plugin comes from a different source. "
                "Uninstall it before installing from this marketplace."
            )

    def _log_install_plan(self, plan: _PluginInstallPlan, *, message: str) -> None:
        logger.info(
            message,
            extra={
                "plugin_id": plan.plugin_id,
                "source_dir": str(plan.source_dir),
                "dest_dir": str(plan.dest_dir),
                "dependency_count": len(plan.manifest.dependencies),
            },
        )

    def _replace_plugin_package(
        self,
        plan: _PluginInstallPlan,
        *,
        progress_reporter: InstallProgressReporter | None,
        stage_message: str,
        activate_after_swap: bool,
        official: bool | None = None,
        consented_capabilities: list[PluginCapability] | None,
        install_origin: str,
        registry_source: str | None = None,
        registry_repo_url: str | None = None,
        registry_entry_fingerprint: str | None = None,
        registry_manifest_fingerprint: str | None = None,
        dependency_entry_fingerprints: dict[str, str] | None = None,
        dependency_workflow_budget: PluginDependencyWorkflowBudget | None = None,
        reject_existing: bool,
        expected_registry_update_source: tuple[str, str] | None = None,
    ) -> PluginDirectoryInstallOutcome:
        """Prepare a package without the lifecycle lock, then commit it briefly."""

        self._reject_unmanaged_package_dependencies(
            plan.manifest,
            install_origin=install_origin,
        )
        if reject_existing:
            self._reject_sideload_overwrite(plan)
        if expected_registry_update_source is not None:
            self._assert_registry_update_source(
                plan.plugin_id,
                expected_registry_update_source,
            )
        expected_target = self._capture_plugin_install_target(
            plan,
            validate_dependencies=activate_after_swap,
            registry_source=registry_source,
            registry_repo_url=registry_repo_url,
            dependency_entry_fingerprints=dependency_entry_fingerprints or {},
        )

        def prepare_staging_dir(staged_dir: Path) -> None:
            if dependency_workflow_budget is not None:
                dependency_workflow_budget.ensure_time_remaining()
            _report_install_progress(progress_reporter, "stage", stage_message, 48.0)
            self._install_staged_dependencies(
                staged_dir,
                progress_reporter=progress_reporter,
                workflow_budget=dependency_workflow_budget,
            )

        with plugin_preparation_slot():
            staged_dir = package_files.stage_plugin_directory(
                plan.source_dir,
                plan.dest_dir,
                prepare_staging_dir=prepare_staging_dir,
            )
        backup_dir: Path | None = None
        try:
            if dependency_workflow_budget is not None:
                dependency_workflow_budget.ensure_time_remaining()
            outcome, backup_dir = self._commit_staged_plugin_package(
                plan,
                staged_dir=staged_dir,
                progress_reporter=progress_reporter,
                activate_after_swap=activate_after_swap,
                official=official,
                consented_capabilities=consented_capabilities,
                install_origin=install_origin,
                registry_source=registry_source,
                registry_repo_url=registry_repo_url,
                registry_entry_fingerprint=registry_entry_fingerprint,
                registry_manifest_fingerprint=registry_manifest_fingerprint,
                dependency_entry_fingerprints=dependency_entry_fingerprints or {},
                reject_existing=reject_existing,
                expected_registry_update_source=expected_registry_update_source,
                expected_target=expected_target,
            )
            return outcome
        finally:
            package_files.discard_plugin_transaction_directory(staged_dir)
            package_files.discard_plugin_transaction_directory(backup_dir)

    def _commit_staged_plugin_package(
        self,
        plan: _PluginInstallPlan,
        *,
        staged_dir: Path,
        progress_reporter: InstallProgressReporter | None,
        activate_after_swap: bool,
        official: bool | None,
        consented_capabilities: list[PluginCapability] | None,
        install_origin: str,
        registry_source: str | None,
        registry_repo_url: str | None,
        registry_entry_fingerprint: str | None,
        registry_manifest_fingerprint: str | None,
        dependency_entry_fingerprints: dict[str, str],
        reject_existing: bool,
        expected_registry_update_source: tuple[str, str] | None,
        expected_target: _PluginInstallTarget,
    ) -> tuple[PluginDirectoryInstallOutcome, Path | None]:
        """Commit an already-prepared package as one lifecycle mutation.

        ``PluginManager`` wraps this hook with its lifecycle write lock. Keep
        extraction, copying, dependency preparation, and transaction cleanup
        in ``_replace_plugin_package`` so this critical section stays short.
        """

        reusable_library = self._reuse_matching_registry_library(
            plan,
            install_origin=install_origin,
            registry_source=registry_source,
            registry_repo_url=registry_repo_url,
            registry_entry_fingerprint=registry_entry_fingerprint,
            registry_manifest_fingerprint=registry_manifest_fingerprint,
            dependency_entry_fingerprints=dependency_entry_fingerprints,
        )
        if reusable_library is not None:
            return (
                self._build_directory_install_outcome(
                    reusable_library,
                    created_by_this_commit=False,
                ),
                None,
            )

        if reject_existing:
            self._reject_sideload_overwrite(plan)
        if expected_registry_update_source is not None:
            self._assert_registry_update_source(
                plan.plugin_id,
                expected_registry_update_source,
            )
        self._assert_plugin_install_target_unchanged(
            plan,
            expected_target,
            validate_dependencies=activate_after_swap,
            registry_source=registry_source,
            registry_repo_url=registry_repo_url,
            dependency_entry_fingerprints=dependency_entry_fingerprints,
        )

        snapshot = self._snapshot_install_state(plan.plugin_id)
        installed_state: PluginPackageState | None = None
        installed_outcome: PluginDirectoryInstallOutcome | None = None
        config_write_attempted = False
        state_restored = False
        created_by_this_commit = bool(
            snapshot.package_state is None
            and snapshot.config is None
            and expected_target.destination_identity is None
            and expected_target.manifest_identity is None
        )
        config_updates = self._build_install_config_updates(
            plan,
            snapshot=snapshot,
            activate_after_swap=activate_after_swap,
            official=official,
            consented_capabilities=consented_capabilities,
            install_origin=install_origin,
            registry_source=registry_source,
            registry_repo_url=registry_repo_url,
            registry_entry_fingerprint=registry_entry_fingerprint,
            registry_manifest_fingerprint=registry_manifest_fingerprint,
            dependency_entry_fingerprints=dependency_entry_fingerprints,
            reset_existing_config=reject_existing,
        )

        def persist_install_config() -> None:
            nonlocal config_write_attempted
            if not config_updates:
                return
            config_write_attempted = True
            if not save_config(config_updates):
                raise RuntimeError("Failed to persist plugin installation state")

        def validate_promoted_dir() -> None:
            nonlocal installed_outcome, installed_state

            if activate_after_swap:
                # Persist the new package identity before discovery so stale or
                # orphaned configuration cannot project trust onto the new files.
                persist_install_config()
            _report_install_progress(
                progress_reporter,
                "scan",
                "Refreshing plugin registry",
                88.0,
            )
            self.scan(persist_discovery=False)
            state = self._require_package(plan.plugin_id)
            if not package_files.is_managed_plugin_manifest_path(
                plan.plugin_id,
                state.manifest.manifest_path,
            ) or plugin_manifest_fingerprint(state.manifest) != plugin_manifest_fingerprint(
                plan.manifest
            ):
                raise RuntimeError(
                    "Plugin discovery did not resolve the newly published managed package"
                )

            should_load = activate_after_swap or bool(
                snapshot.package_state is not None and snapshot.package_state.loaded
            )
            if not activate_after_swap:
                state.enabled = False
                state.trusted = False
                state.current_settings = {}
            if should_load:
                if activate_after_swap:
                    _report_install_progress(
                        progress_reporter,
                        "activate",
                        "Enabling plugin package",
                        94.0,
                    )
                    state.enabled = True
                    state.trusted = True
                state = self.load_plugin(plan.plugin_id)

            installed_state = state
            installed_outcome = self._build_directory_install_outcome(
                state,
                created_by_this_commit=created_by_this_commit,
            )

        def restore_previous_install() -> None:
            nonlocal state_restored
            state_restored = True
            self.unload_plugin(plan.plugin_id)
            if config_write_attempted:
                self._restore_plugin_config(plan.plugin_id, snapshot.config)

            self.scan(persist_discovery=False)
            previous_state = snapshot.package_state
            if previous_state is None:
                return

            restored_state = self._require_package(plan.plugin_id)
            restored_state.enabled = previous_state.enabled
            restored_state.trusted = previous_state.trusted
            restored_state.healthy = previous_state.healthy
            restored_state.last_error = previous_state.last_error
            restored_state.current_settings = dict(previous_state.current_settings)
            if previous_state.loaded:
                self.load_plugin(plan.plugin_id)

        try:
            if not activate_after_swap:
                persist_install_config()
            backup_dir = package_files.promote_staged_plugin_directory(
                staged_dir,
                plan.dest_dir,
                before_swap=(
                    (lambda: self.unload_plugin(plan.plugin_id)) if plan.dest_dir.exists() else None
                ),
                after_swap=validate_promoted_dir,
                after_rollback=restore_previous_install,
            )
        except BaseException:
            if config_write_attempted and not state_restored:
                restore_previous_install()
            raise
        if installed_state is None or installed_outcome is None:
            raise RuntimeError("Plugin installation completed without a package state")
        return installed_outcome, backup_dir

    def _build_directory_install_outcome(
        self,
        state: PluginPackageState,
        *,
        created_by_this_commit: bool,
    ) -> PluginDirectoryInstallOutcome:
        """Freeze the published generation while the lifecycle lock is held."""

        plugin_dir = Path(state.manifest.plugin_dir).expanduser().resolve(strict=False)
        manifest_path = Path(state.manifest.manifest_path).expanduser().resolve(strict=False)
        destination_identity = self._directory_identity(plugin_dir)
        manifest_identity = self._path_identity(manifest_path)
        if destination_identity is None or manifest_identity is None:
            raise RuntimeError(
                f"Installed plugin generation disappeared during commit: {state.manifest.plugin_id}"
            )
        return PluginDirectoryInstallOutcome(
            state=state,
            created_by_this_commit=created_by_this_commit,
            plugin_dir=str(plugin_dir),
            manifest_path=str(manifest_path),
            destination_identity=destination_identity,
            manifest_identity=manifest_identity,
        )

    def _reuse_matching_registry_library(
        self,
        plan: _PluginInstallPlan,
        *,
        install_origin: str,
        registry_source: str | None,
        registry_repo_url: str | None,
        registry_entry_fingerprint: str | None,
        registry_manifest_fingerprint: str | None,
        dependency_entry_fingerprints: dict[str, str],
    ) -> PluginPackageState | None:
        """Reuse an identical library that another install committed first.

        Registry libraries are immutable while installed. This check runs
        under the manager lifecycle lock, closing the race between a
        dependency-closure plan and its final package commit.
        """

        if plan.manifest.kind != "library" or install_origin != "registry":
            return None

        state = self._package_states.get(plan.plugin_id)
        raw_configured = get_config().plugins.packages.get(plan.plugin_id)
        destination_exists = plan.dest_dir.exists()
        if state is None and raw_configured is None and not destination_exists:
            return None

        try:
            configured = (
                PluginSettings.model_validate(raw_configured)
                if raw_configured is not None
                else None
            )
            disk_manifest = self._load_manifest(
                plan.dest_dir / "plugin.toml",
                source="external",
            )
        except Exception as exc:
            raise PluginDependencyValidationError(
                f"Installed dependency {plan.plugin_id} does not match the "
                "approved registry package; uninstall it before retrying"
            ) from exc

        expected_manifest_fingerprint = plugin_manifest_fingerprint(plan.manifest)
        valid = (
            state is not None
            and configured is not None
            and destination_exists
            and registry_source is not None
            and registry_repo_url is not None
            and registry_entry_fingerprint is not None
            and registry_manifest_fingerprint == expected_manifest_fingerprint
            and state.manifest.kind == "library"
            and state.manifest.source == "external"
            and state.enabled
            and state.trusted
            and configured.enabled
            and configured.trusted
            and configured.install_origin == "registry"
            and configured.registry_source == registry_source
            and configured.registry_repo_url == registry_repo_url
            and configured.registry_entry_fingerprint == registry_entry_fingerprint
            and configured.registry_manifest_fingerprint == registry_manifest_fingerprint
            and configured.dependency_entry_fingerprints == dependency_entry_fingerprints
            and plugin_manifest_fingerprint(state.manifest) == expected_manifest_fingerprint
            and plugin_manifest_fingerprint(disk_manifest) == expected_manifest_fingerprint
            and Path(state.manifest.plugin_dir).resolve(strict=False)
            == plan.dest_dir.resolve(strict=False)
        )
        if not valid:
            raise PluginDependencyValidationError(
                f"Installed dependency {plan.plugin_id} does not match the "
                "approved registry package; uninstall it before retrying"
            )

        self._capture_plugin_dependencies(
            state.manifest,
            registry_source=registry_source,
            registry_repo_url=registry_repo_url,
            dependency_entry_fingerprints=dependency_entry_fingerprints,
        )
        return state

    def _capture_plugin_install_target(
        self,
        plan: _PluginInstallPlan,
        *,
        validate_dependencies: bool,
        registry_source: str | None,
        registry_repo_url: str | None,
        dependency_entry_fingerprints: dict[str, str],
    ) -> _PluginInstallTarget:
        """Capture the package identity that a prepared install may replace."""

        state = self._package_states.get(plan.plugin_id)
        dependency_targets = (
            self._capture_plugin_dependencies(
                plan.manifest,
                registry_source=registry_source,
                registry_repo_url=registry_repo_url,
                dependency_entry_fingerprints=dependency_entry_fingerprints,
            )
            if validate_dependencies
            else ()
        )
        return _PluginInstallTarget(
            package_state=state,
            destination_identity=self._path_identity(plan.dest_dir),
            manifest_identity=self._path_identity(plan.dest_dir / "plugin.toml"),
            dependency_targets=dependency_targets,
        )

    def _assert_plugin_install_target_unchanged(
        self,
        plan: _PluginInstallPlan,
        expected: _PluginInstallTarget,
        *,
        validate_dependencies: bool,
        registry_source: str | None,
        registry_repo_url: str | None,
        dependency_entry_fingerprints: dict[str, str],
    ) -> None:
        current = self._capture_plugin_install_target(
            plan,
            validate_dependencies=validate_dependencies,
            registry_source=registry_source,
            registry_repo_url=registry_repo_url,
            dependency_entry_fingerprints=dependency_entry_fingerprints,
        )
        dependencies_unchanged = len(current.dependency_targets) == len(
            expected.dependency_targets
        ) and all(
            current_dependency.plugin_id == expected_dependency.plugin_id
            and current_dependency.destination_identity == expected_dependency.destination_identity
            and current_dependency.manifest_identity == expected_dependency.manifest_identity
            and current_dependency.registry_source == expected_dependency.registry_source
            and current_dependency.registry_repo_url == expected_dependency.registry_repo_url
            and current_dependency.registry_entry_fingerprint
            == expected_dependency.registry_entry_fingerprint
            and current_dependency.registry_manifest_fingerprint
            == expected_dependency.registry_manifest_fingerprint
            for current_dependency, expected_dependency in zip(
                current.dependency_targets,
                expected.dependency_targets,
                strict=True,
            )
        )
        if (
            current.package_state is not expected.package_state
            or current.destination_identity != expected.destination_identity
            or current.manifest_identity != expected.manifest_identity
            or not dependencies_unchanged
        ):
            raise ValueError(
                f"Plugin install target changed while the package was being prepared: "
                f"{plan.plugin_id}"
            )

    def _capture_plugin_dependencies(
        self,
        manifest: PluginManifest,
        *,
        registry_source: str | None,
        registry_repo_url: str | None,
        dependency_entry_fingerprints: dict[str, str],
    ) -> tuple[_PluginDependencyTarget, ...]:
        """Validate and capture the full library closure under the lifecycle lock."""

        targets: list[_PluginDependencyTarget] = []
        visiting: set[str] = set()
        resolved: dict[str, tuple[str, str, str]] = {}

        def capture(
            consumer: PluginManifest,
            *,
            source: str | None,
            repo_url: str | None,
            expected_fingerprints: dict[str, str],
        ) -> None:
            dependency_ids = list(consumer.depends_on)
            if not dependency_ids:
                if expected_fingerprints:
                    raise PluginDependencyValidationError(
                        f"Plugin {consumer.plugin_id} has unexpected dependency provenance"
                    )
                return
            if consumer.source != "builtin" and (
                source is None
                or repo_url is None
                or set(expected_fingerprints) != set(dependency_ids)
            ):
                raise PluginDependencyValidationError(
                    f"Plugin {consumer.plugin_id} has incomplete registry dependency provenance"
                )

            for dependency_id in dependency_ids:
                if dependency_id in visiting:
                    raise PluginDependencyValidationError(
                        f"Cyclic plugin dependency detected involving {dependency_id}"
                    )
                state = self._package_states.get(dependency_id)
                if state is None:
                    raise PluginDependencyValidationError(
                        f"Plugin {consumer.plugin_id} depends on missing package: {dependency_id}"
                    )
                dependency_dir = Path(state.manifest.plugin_dir)
                if state.manifest.kind != "library" or not dependency_dir.is_dir():
                    raise PluginDependencyValidationError(
                        f"Plugin dependency {dependency_id} must be an installed library package"
                    )
                manifest_path = (
                    Path(state.manifest.manifest_path)
                    if state.manifest.manifest_path
                    else dependency_dir / "plugin.toml"
                )

                if consumer.source == "builtin":
                    if state.manifest.source != "builtin":
                        raise PluginDependencyValidationError(
                            f"Builtin plugin {consumer.plugin_id} cannot use an external dependency"
                        )
                    configured: PluginSettings | None = None
                    expectation = ("builtin", "builtin", "builtin")
                    target = _PluginDependencyTarget(
                        plugin_id=dependency_id,
                        package_state=state,
                        destination_identity=self._path_identity(dependency_dir),
                        manifest_identity=self._path_identity(manifest_path),
                        registry_source="builtin",
                        registry_repo_url="builtin",
                        registry_entry_fingerprint="builtin",
                        registry_manifest_fingerprint=plugin_manifest_fingerprint(state.manifest),
                    )
                else:
                    raw_configured = get_config().plugins.packages.get(dependency_id)
                    configured = (
                        PluginSettings.model_validate(raw_configured)
                        if raw_configured is not None
                        else None
                    )
                    expected_entry_fingerprint = expected_fingerprints[dependency_id]
                    expectation = (source or "", repo_url or "", expected_entry_fingerprint)
                    if (
                        configured is None
                        or not state.enabled
                        or not state.trusted
                        or not configured.enabled
                        or not configured.trusted
                        or configured.install_origin != "registry"
                        or configured.registry_source != source
                        or configured.registry_repo_url != repo_url
                        or configured.registry_entry_fingerprint != expected_entry_fingerprint
                        or not configured.registry_manifest_fingerprint
                        or configured.registry_manifest_fingerprint
                        != plugin_manifest_fingerprint(state.manifest)
                    ):
                        raise PluginDependencyValidationError(
                            f"Installed dependency {dependency_id} does not match the "
                            "approved registry package; uninstall it before retrying"
                        )
                    target = _PluginDependencyTarget(
                        plugin_id=dependency_id,
                        package_state=state,
                        destination_identity=self._path_identity(dependency_dir),
                        manifest_identity=self._path_identity(manifest_path),
                        registry_source=configured.registry_source,
                        registry_repo_url=configured.registry_repo_url,
                        registry_entry_fingerprint=configured.registry_entry_fingerprint,
                        registry_manifest_fingerprint=(configured.registry_manifest_fingerprint),
                    )

                previous_expectation = resolved.get(dependency_id)
                if previous_expectation is not None:
                    if previous_expectation != expectation:
                        raise PluginDependencyValidationError(
                            f"Plugin dependency {dependency_id} has conflicting provenance"
                        )
                    continue

                targets.append(target)
                visiting.add(dependency_id)
                try:
                    capture(
                        state.manifest,
                        source=(configured.registry_source if configured is not None else None),
                        repo_url=(configured.registry_repo_url if configured is not None else None),
                        expected_fingerprints=(
                            dict(configured.dependency_entry_fingerprints)
                            if configured is not None
                            else {}
                        ),
                    )
                finally:
                    visiting.discard(dependency_id)
                resolved[dependency_id] = expectation

        capture(
            manifest,
            source=registry_source,
            repo_url=registry_repo_url,
            expected_fingerprints=dependency_entry_fingerprints,
        )
        return tuple(targets)

    @staticmethod
    def _path_identity(path: Path) -> tuple[int, int, int, int] | None:
        try:
            metadata = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            return None
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
        )

    def _snapshot_install_state(self, plugin_id: str) -> _PluginInstallSnapshot:
        state = self._package_states.get(plugin_id)
        package_state = state.model_copy(deep=True) if state is not None else None
        configured = get_config().plugins.packages.get(plugin_id)
        config = (
            PluginSettings.model_validate(configured).model_copy(deep=True)
            if configured is not None
            else None
        )
        return _PluginInstallSnapshot(package_state=package_state, config=config)

    @staticmethod
    def _build_install_config_updates(
        plan: _PluginInstallPlan,
        *,
        snapshot: _PluginInstallSnapshot,
        activate_after_swap: bool,
        official: bool | None,
        consented_capabilities: list[PluginCapability] | None,
        install_origin: str,
        registry_source: str | None,
        registry_repo_url: str | None,
        registry_entry_fingerprint: str | None,
        registry_manifest_fingerprint: str | None,
        dependency_entry_fingerprints: dict[str, str],
        reset_existing_config: bool,
    ) -> dict[str, object]:
        prefix = f"plugins.packages.{plan.plugin_id}"
        if activate_after_swap:
            updates: dict[str, object] = {
                f"{prefix}.enabled": True,
                f"{prefix}.trusted": True,
                f"{prefix}.source": plan.manifest.source,
                f"{prefix}.manifest_path": str(plan.dest_dir / "plugin.toml"),
            }
        else:
            updates = {
                f"{prefix}.enabled": False,
                f"{prefix}.trusted": False,
                f"{prefix}.source": plan.manifest.source,
                f"{prefix}.manifest_path": str(plan.dest_dir / "plugin.toml"),
                f"{prefix}.official": False,
                f"{prefix}.consented_capabilities": [
                    capability.model_dump(mode="json")
                    for capability in (consented_capabilities or [])
                ],
                f"{prefix}.settings": {},
            }

        if snapshot.config is None or reset_existing_config:
            updates[f"{prefix}.official"] = False
            updates[f"{prefix}.settings"] = {}
        if official is not None:
            updates[f"{prefix}.official"] = official
        if consented_capabilities is not None:
            updates[f"{prefix}.consented_capabilities"] = [
                capability.model_dump(mode="json") for capability in consented_capabilities
            ]
        updates[f"{prefix}.install_origin"] = install_origin
        updates[f"{prefix}.registry_source"] = registry_source
        updates[f"{prefix}.registry_repo_url"] = registry_repo_url
        updates[f"{prefix}.registry_entry_fingerprint"] = registry_entry_fingerprint
        updates[f"{prefix}.registry_manifest_fingerprint"] = registry_manifest_fingerprint
        updates[f"{prefix}.dependency_entry_fingerprints"] = dict(dependency_entry_fingerprints)
        return updates

    @staticmethod
    def _restore_plugin_config(plugin_id: str, config: PluginSettings | None) -> None:
        prefix = f"plugins.packages.{plugin_id}"
        if config is None:
            if plugin_id not in get_config().plugins.packages:
                return
            if not delete_plugin_package(plugin_id):
                raise RuntimeError(f"Failed to restore plugin configuration: {plugin_id}")
            return
        else:
            updates = {
                f"{prefix}.{field_name}": value
                for field_name, value in config.model_dump(mode="json").items()
            }
        if not save_config(updates):
            raise RuntimeError(f"Failed to restore plugin configuration: {plugin_id}")

    def _install_staged_dependencies(
        self,
        staged_dir: Path,
        *,
        progress_reporter: InstallProgressReporter | None,
        workflow_budget: PluginDependencyWorkflowBudget | None = None,
    ) -> None:
        new_manifest = self._load_manifest(staged_dir / "plugin.toml", source="external")
        if not new_manifest.dependencies:
            return
        if progress_reporter is None:
            self._install_dependencies(
                new_manifest.dependencies,
                staged_dir,
                workflow_budget=workflow_budget,
            )
            return
        self._install_dependencies(
            new_manifest.dependencies,
            staged_dir,
            progress_reporter=progress_reporter,
            workflow_budget=workflow_budget,
        )

    @staticmethod
    def _managed_uninstall_directory(state: PluginPackageState) -> Path:
        """Return a host-owned package directory or reject destructive removal."""

        plugin_id = state.manifest.plugin_id
        if not package_files.is_managed_plugin_manifest_path(
            plugin_id,
            state.manifest.manifest_path,
        ):
            raise ValueError(
                "Only plugins in Magi's managed plugin directory can be uninstalled. "
                "Disable this plugin or remove its scan path instead."
            )
        return package_files.managed_plugin_directory(plugin_id)

    def remove_provisional_registry_library(
        self,
        receipt: ProvisionalLibraryReceipt,
    ) -> Path | None:
        """Detach one exact, newly published registry library if it is orphaned.

        The manager wraps this method with its lifecycle lock. The returned
        private directory is intentionally deleted by the caller after that
        lock is released.
        """

        requirement = receipt.requirement
        plugin_id = requirement.plugin_id
        state = self._package_states.get(plugin_id)
        raw_configured = get_config().plugins.packages.get(plugin_id)
        configured = (
            PluginSettings.model_validate(raw_configured) if raw_configured is not None else None
        )
        if state is None or configured is None:
            return None

        plugin_dir = Path(state.manifest.plugin_dir).expanduser().resolve(strict=False)
        manifest_path = Path(state.manifest.manifest_path).expanduser().resolve(strict=False)
        expected_plugin_dir = Path(receipt.plugin_dir).expanduser().resolve(strict=False)
        expected_manifest_path = Path(receipt.manifest_path).expanduser().resolve(strict=False)
        identity_matches = bool(
            state.manifest.kind == "library"
            and state.manifest.source == "external"
            and state.enabled
            and state.trusted
            and configured.enabled
            and configured.trusted
            and configured.install_origin == "registry"
            and configured.registry_source == requirement.registry_source
            and configured.registry_repo_url == requirement.registry_repo_url
            and configured.registry_entry_fingerprint == requirement.registry_entry_fingerprint
            and configured.registry_manifest_fingerprint == receipt.registry_manifest_fingerprint
            and tuple(sorted(configured.dependency_entry_fingerprints.items()))
            == receipt.dependency_entry_fingerprints
            and plugin_manifest_fingerprint(state.manifest) == receipt.registry_manifest_fingerprint
            and plugin_dir == expected_plugin_dir
            and manifest_path == expected_manifest_path
            and package_files.is_managed_plugin_manifest_path(plugin_id, manifest_path)
            and self._directory_identity(plugin_dir) == receipt.destination_identity
            and self._path_identity(manifest_path) == receipt.manifest_identity
        )
        if not identity_matches:
            logger.warning(
                "plugin.provisional_dependency_identity_changed plugin_id=%s",
                plugin_id,
            )
            return None
        if self.iter_consumers(plugin_id) or self._has_managed_configured_consumer(plugin_id):
            return None

        was_loaded = state.loaded
        self.unload_plugin(plugin_id)
        backup_dir = (
            plugin_dir.parent.parent
            / f".{plugin_dir.parent.name}-{plugin_id}-provisional-{uuid.uuid4().hex}"
        )
        try:
            plugin_dir.replace(backup_dir)
            if not delete_plugin_package(plugin_id):
                raise RuntimeError(
                    f"Failed to remove provisional plugin configuration: {plugin_id}"
                )
        except BaseException:
            if backup_dir.exists() and not plugin_dir.exists():
                backup_dir.replace(plugin_dir)
            state.loaded = was_loaded
            self._restore_plugin_config(plugin_id, configured)
            raise

        self._package_states.pop(plugin_id, None)
        self._request_sensor_schedule_refresh()
        return backup_dir

    @staticmethod
    def _directory_identity(path: Path) -> tuple[int, int] | None:
        try:
            metadata = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            return None
        return metadata.st_dev, metadata.st_ino

    @staticmethod
    def _has_managed_configured_consumer(library_id: str) -> bool:
        """Conservatively detect consumers not present in this manager instance."""

        package_configs = list(get_config().plugins.packages.items())
        for consumer_id, raw_configured in package_configs:
            if consumer_id == library_id:
                continue
            raw_dependency_fingerprints = (
                raw_configured.get("dependency_entry_fingerprints", {})
                if isinstance(raw_configured, dict)
                else getattr(raw_configured, "dependency_entry_fingerprints", {})
            )
            claims_dependency = library_id in raw_dependency_fingerprints
            try:
                configured = PluginSettings.model_validate(raw_configured)
            except (TypeError, ValueError):
                if claims_dependency:
                    logger.warning(
                        "plugin.provisional_dependency_consumer_config_invalid "
                        "plugin_id=%s consumer_id=%s",
                        library_id,
                        consumer_id,
                    )
                    return True
                continue

            if not configured.manifest_path:
                if claims_dependency:
                    return True
                continue
            manifest_path = Path(configured.manifest_path).expanduser().resolve(strict=False)
            if not package_files.is_managed_plugin_manifest_path(
                consumer_id,
                manifest_path,
            ):
                if claims_dependency:
                    return True
                continue
            try:
                manifest = load_plugin_manifest(manifest_path, source="external")
            except (OSError, ValueError):
                if claims_dependency:
                    logger.warning(
                        "plugin.provisional_dependency_consumer_manifest_invalid "
                        "plugin_id=%s consumer_id=%s",
                        library_id,
                        consumer_id,
                    )
                    return True
                continue
            if library_id not in manifest.depends_on:
                if claims_dependency:
                    return True
                continue
            if package_identity_error(manifest, configured) is not None:
                return True
            return True
        return False

    def uninstall_plugin(self, plugin_id: str) -> list[str]:
        """Uninstall a user-installed plugin and remove its files.

        Returns the list of additional plugin_ids that were also removed
        as part of dep-closure garbage collection (i.e. library packages
        whose only consumer was the plugin being uninstalled). The list is
        empty for the common case.

        A library package can only be uninstalled directly when no other
        installed plugin still declares it in ``depends_on`` — otherwise
        the call is rejected.
        """
        state = self._require_package(plugin_id)
        if state.manifest.source == "builtin":
            raise ValueError(f"Cannot uninstall builtin plugin: {plugin_id}")
        plugin_dir = self._managed_uninstall_directory(state)

        # Refcount guard for direct library removal: the only way a library
        # is allowed to disappear is if no consumer is left. Plugin-driven
        # uninstall handles its own deps via dep-closure GC below.
        if state.manifest.kind == "library":
            consumers = [cid for cid in self.iter_consumers(plugin_id) if cid != plugin_id]
            if consumers:
                raise ValueError(
                    f"Cannot uninstall library {plugin_id}: still required by "
                    f"{', '.join(consumers)}"
                )

        self.unload_plugin(plugin_id)

        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)

        if not delete_plugin_package(plugin_id):
            raise RuntimeError(f"Failed to remove plugin configuration: {plugin_id}")
        self._package_states.pop(plugin_id, None)

        # Dep-closure GC: recursively remove dependency libraries that no
        # installed package still references.
        gc_removed: list[str] = []
        for dep_id in state.manifest.depends_on:
            dep_state = self._package_states.get(dep_id)
            if dep_state is None or dep_state.manifest.kind != "library":
                continue
            if self.iter_consumers(dep_id):
                continue
            try:
                nested_removed = self.uninstall_plugin(dep_id)
                gc_removed.append(dep_id)
                gc_removed.extend(nested_removed)
            except Exception:
                logger.warning(
                    "plugin.dep_gc_failed plugin_id=%s dep_id=%s",
                    plugin_id,
                    dep_id,
                    exc_info=True,
                )

        self._request_sensor_schedule_refresh()
        return gc_removed

    def check_installed_version(self, plugin_id: str) -> str | None:
        """Return the installed version of a plugin, or None if not installed."""
        state = self.get_package(plugin_id)
        if state is None:
            return None
        return state.manifest.version

    @staticmethod
    def _install_dependencies(
        dependencies: list[str],
        plugin_dir: Path,
        *,
        progress_reporter: InstallProgressReporter | None = None,
        workflow_budget: PluginDependencyWorkflowBudget | None = None,
    ) -> None:
        install_plugin_dependencies(
            dependencies,
            plugin_dir,
            progress_reporter=progress_reporter,
            workflow_budget=workflow_budget,
        )
