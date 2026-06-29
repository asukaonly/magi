"""Plugin package installation and removal helpers."""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import tempfile

from . import package_files
from ..config import save_config
from .contracts import PluginManifest, PluginPackageState
from .dependency_installation import (
    ALLOW_UNLOCKED_DEPS_ENV,
    BACKEND_PYTHON_ENV,
    PLUGIN_DEPENDENCY_PYTHON_ENV,
    InstallProgressReporter,
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
    "PluginInstallationMixin",
    "UnlockedDependencyError",
    "_build_dependency_install_command",
    "_build_loose_dependency_install_command",
    "_developer_mode_allows_unlocked",
    "_resolve_lock_or_policy",
    "_run_dependency_install_with_progress",
]


def _report_install_progress(
    reporter: InstallProgressReporter | None,
    stage: str,
    message: str,
    progress_pct: float | None = None,
) -> None:
    if reporter is not None:
        reporter(stage, message, progress_pct)


class PluginInstallationMixin:
    """Install and uninstall user plugin packages."""

    _package_states: dict[str, PluginPackageState]

    def _load_manifest(self, manifest_path: Path, *, source: str) -> PluginManifest:
        raise NotImplementedError

    def _require_package(self, plugin_id: str) -> PluginPackageState:
        raise NotImplementedError

    def scan(self, *, persist_discovery: bool = True) -> list[PluginPackageState]:
        raise NotImplementedError

    def enable_plugin(self, plugin_id: str) -> PluginPackageState:
        raise NotImplementedError

    def unload_plugin(self, plugin_id: str) -> None:
        raise NotImplementedError

    def install_plugin_from_archive(
        self,
        archive_path: Path,
        *,
        progress_reporter: InstallProgressReporter | None = None,
    ) -> PluginPackageState:
        """Install a plugin from a .tar.gz or .zip archive.

        The archive must contain a ``plugin.toml`` at the top level or
        inside exactly one subdirectory. The plugin is extracted into
        ``~/.magi/plugins/<plugin_id>/``.
        """
        user_root = package_files.user_plugins_root()
        user_root.mkdir(parents=True, exist_ok=True)
        logger.info("Installing plugin from archive", extra={"archive_path": str(archive_path)})
        _report_install_progress(
            progress_reporter,
            "extract",
            "Extracting plugin archive",
            18.0,
        )

        with tempfile.TemporaryDirectory(prefix="magi-plugin-install-") as tmp:
            tmp_path = Path(tmp)
            package_files.extract_plugin_archive(archive_path, tmp_path)
            manifest_file = package_files.find_plugin_manifest_in_tree(tmp_path)
            if manifest_file is None:
                raise ValueError("Archive does not contain a plugin.toml")
            manifest = self._load_manifest(manifest_file, source="external")
            plugin_id = manifest.plugin_id

            existing = self._package_states.get(plugin_id)
            if existing is not None and existing.manifest.source == "builtin":
                raise ValueError(f"Cannot overwrite builtin plugin: {plugin_id}")

            dest_dir = user_root / plugin_id
            source_dir = manifest_file.parent
            logger.info(
                "Installing external plugin package",
                extra={
                    "plugin_id": plugin_id,
                    "source_dir": str(source_dir),
                    "dest_dir": str(dest_dir),
                    "dependency_count": len(manifest.dependencies),
                },
            )

            def prepare_staging_dir(staged_dir: Path) -> None:
                _report_install_progress(
                    progress_reporter,
                    "stage",
                    "Validating staged plugin package",
                    48.0,
                )
                new_manifest = self._load_manifest(staged_dir / "plugin.toml", source="external")
                if new_manifest.dependencies:
                    if progress_reporter is None:
                        self._install_dependencies(new_manifest.dependencies, staged_dir)
                    else:
                        self._install_dependencies(
                            new_manifest.dependencies,
                            staged_dir,
                            progress_reporter=progress_reporter,
                        )

            package_files.replace_plugin_directory(
                source_dir,
                dest_dir,
                prepare_staging_dir=prepare_staging_dir,
                before_swap=(lambda: self.unload_plugin(plugin_id)) if dest_dir.exists() else None,
            )

        _report_install_progress(progress_reporter, "scan", "Refreshing plugin registry", 88.0)
        self.scan(persist_discovery=True)
        state = self._require_package(plugin_id)
        logger.info("Installed plugin from archive", extra={"plugin_id": plugin_id})
        _report_install_progress(progress_reporter, "completed", "Plugin package installed", 100.0)
        return state

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
            return self._load_manifest(manifest_file, source="external")

    def install_plugin_from_directory(
        self,
        source_dir: Path,
        *,
        progress_reporter: InstallProgressReporter | None = None,
    ) -> PluginPackageState:
        """Install a plugin from a local directory containing a plugin.toml."""
        _report_install_progress(
            progress_reporter,
            "validate",
            "Validating plugin manifest",
            38.0,
        )
        manifest_file = package_files.find_plugin_manifest_in_tree(source_dir)
        if manifest_file is None:
            raise ValueError("Directory does not contain a plugin.toml")
        manifest = self._load_manifest(manifest_file, source="external")
        plugin_id = manifest.plugin_id

        existing = self._package_states.get(plugin_id)
        if existing is not None and existing.manifest.source == "builtin":
            raise ValueError(f"Cannot overwrite builtin plugin: {plugin_id}")

        user_root = package_files.user_plugins_root()
        user_root.mkdir(parents=True, exist_ok=True)
        dest_dir = user_root / plugin_id
        plugin_source = manifest_file.parent
        logger.info(
            "Installing plugin from directory",
            extra={
                "plugin_id": plugin_id,
                "source_dir": str(plugin_source),
                "dest_dir": str(dest_dir),
                "dependency_count": len(manifest.dependencies),
            },
        )

        def prepare_staging_dir(staged_dir: Path) -> None:
            _report_install_progress(
                progress_reporter,
                "stage",
                "Preparing staged plugin package",
                48.0,
            )
            new_manifest = self._load_manifest(staged_dir / "plugin.toml", source="external")
            if new_manifest.dependencies:
                if progress_reporter is None:
                    self._install_dependencies(new_manifest.dependencies, staged_dir)
                else:
                    self._install_dependencies(
                        new_manifest.dependencies,
                        staged_dir,
                        progress_reporter=progress_reporter,
                    )

        package_files.replace_plugin_directory(
            plugin_source,
            dest_dir,
            prepare_staging_dir=prepare_staging_dir,
            before_swap=(lambda: self.unload_plugin(plugin_id)) if dest_dir.exists() else None,
        )

        _report_install_progress(progress_reporter, "scan", "Refreshing plugin registry", 88.0)
        self.scan(persist_discovery=True)
        # Library packages get enabled+trusted by _persist_new_packages and
        # are never loaded as Plugin instances, so skip the enable step
        # (which rejects libraries by design).
        if manifest.kind == "library":
            state = self._require_package(plugin_id)
            logger.info("Installed library package", extra={"plugin_id": plugin_id})
        else:
            _report_install_progress(progress_reporter, "activate", "Enabling plugin package", 94.0)
            state = self.enable_plugin(plugin_id)
            logger.info("Installed and enabled plugin", extra={"plugin_id": plugin_id})
        _report_install_progress(progress_reporter, "completed", "Plugin package installed", 100.0)
        return state

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

        # Refcount guard for direct library removal: the only way a library
        # is allowed to disappear is if no consumer is left. Plugin-driven
        # uninstall handles its own deps via dep-closure GC below.
        if state.manifest.kind == "library":
            consumers = [
                cid for cid in self.iter_consumers(plugin_id) if cid != plugin_id
            ]
            if consumers:
                raise ValueError(
                    f"Cannot uninstall library {plugin_id}: still required by "
                    f"{', '.join(consumers)}"
                )

        self.unload_plugin(plugin_id)

        plugin_dir = Path(state.manifest.plugin_dir)
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)

        save_config({f"plugins.packages.{plugin_id}": None})
        self._package_states.pop(plugin_id, None)

        # Dep-closure GC: walk the just-removed plugin's depends_on and
        # uninstall any library that no longer has consumers. We do this
        # only for plugin-kind removals — libraries don't transitively
        # depend on other libraries in the current model.
        gc_removed: list[str] = []
        if state.manifest.kind != "library":
            for dep_id in state.manifest.depends_on:
                dep_state = self._package_states.get(dep_id)
                if dep_state is None or dep_state.manifest.kind != "library":
                    continue
                if self.iter_consumers(dep_id):
                    continue
                # Recurse via the same path so logging / config cleanup
                # stays consistent.
                try:
                    self.uninstall_plugin(dep_id)
                    gc_removed.append(dep_id)
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
        state = self._package_states.get(plugin_id)
        if state is None:
            return None
        return state.manifest.version

    @staticmethod
    def _install_dependencies(
        dependencies: list[str],
        plugin_dir: Path,
        *,
        progress_reporter: InstallProgressReporter | None = None,
    ) -> None:
        install_plugin_dependencies(
            dependencies,
            plugin_dir,
            progress_reporter=progress_reporter,
        )
