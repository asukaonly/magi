"""Plugin package installation and removal helpers."""

from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
import zipfile

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement

from ..awareness.scheduler_contrib import request_sensor_schedule_refresh
from ..config import save_config
from .contracts import PluginManifest, PluginPackageState

logger = logging.getLogger(__name__)


def _filter_installable_dependencies(dependencies: list[str]) -> tuple[list[str], list[str]]:
    installable: list[str] = []
    skipped: list[str] = []
    environment = default_environment()

    for dependency in dependencies:
        try:
            requirement = Requirement(dependency)
        except InvalidRequirement:
            installable.append(dependency)
            continue

        if requirement.marker is not None and not requirement.marker.evaluate(environment):
            skipped.append(dependency)
            continue

        installable.append(dependency)

    return installable, skipped


def replace_plugin_directory(
    source_dir: Path,
    dest_dir: Path,
    *,
    prepare_staging_dir: Callable[[Path], None] | None = None,
    before_swap: Callable[[], None] | None = None,
) -> None:
    """Stage plugin files on disk before swapping them into place.

    The source tree is first copied into a sibling staging directory on the
    target filesystem so dependency installation and validation happen before
    the active plugin directory is touched. The final swap uses directory
    renames with rollback if promotion fails.
    """

    parent_dir = dest_dir.parent
    parent_dir.mkdir(parents=True, exist_ok=True)

    staging_dir = Path(tempfile.mkdtemp(prefix=f".{dest_dir.name}-staging-", dir=parent_dir))
    backup_dir = parent_dir / f".{dest_dir.name}-backup-{uuid.uuid4().hex}"

    try:
        logger.info(
            "Staging plugin directory",
            extra={
                "source_dir": str(source_dir),
                "dest_dir": str(dest_dir),
                "staging_dir": str(staging_dir),
            },
        )
        shutil.rmtree(staging_dir)
        shutil.copytree(source_dir, staging_dir)

        if prepare_staging_dir is not None:
            prepare_staging_dir(staging_dir)

        if before_swap is not None:
            before_swap()

        if dest_dir.exists():
            logger.info(
                "Backing up existing plugin directory",
                extra={"dest_dir": str(dest_dir), "backup_dir": str(backup_dir)},
            )
            dest_dir.replace(backup_dir)

        try:
            staging_dir.replace(dest_dir)
            logger.info(
                "Promoted staged plugin directory",
                extra={"dest_dir": str(dest_dir), "staging_dir": str(staging_dir)},
            )
        except Exception:
            if backup_dir.exists() and not dest_dir.exists():
                backup_dir.replace(dest_dir)
            raise
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)


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

    def install_plugin_from_archive(self, archive_path: Path) -> PluginPackageState:
        """Install a plugin from a .tar.gz or .zip archive.

        The archive must contain a ``plugin.toml`` at the top level or
        inside exactly one subdirectory. The plugin is extracted into
        ``~/.magi/plugins/<plugin_id>/``.
        """
        user_root = self._user_plugins_root()
        user_root.mkdir(parents=True, exist_ok=True)
        logger.info("Installing plugin from archive", extra={"archive_path": str(archive_path)})

        with tempfile.TemporaryDirectory(prefix="magi-plugin-install-") as tmp:
            tmp_path = Path(tmp)
            self._extract_archive(archive_path, tmp_path)
            manifest_file = self._find_manifest_in_tree(tmp_path)
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
                new_manifest = self._load_manifest(staged_dir / "plugin.toml", source="external")
                if new_manifest.dependencies:
                    self._install_dependencies(new_manifest.dependencies, staged_dir)

            replace_plugin_directory(
                source_dir,
                dest_dir,
                prepare_staging_dir=prepare_staging_dir,
                before_swap=(lambda: self.unload_plugin(plugin_id)) if dest_dir.exists() else None,
            )

        self.scan(persist_discovery=True)
        state = self._require_package(plugin_id)
        logger.info("Installed plugin from archive", extra={"plugin_id": plugin_id})
        return state

    def install_plugin_from_directory(self, source_dir: Path) -> PluginPackageState:
        """Install a plugin from a local directory containing a plugin.toml."""
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
            new_manifest = self._load_manifest(staged_dir / "plugin.toml", source="external")
            if new_manifest.dependencies:
                self._install_dependencies(new_manifest.dependencies, staged_dir)

        replace_plugin_directory(
            plugin_source,
            dest_dir,
            prepare_staging_dir=prepare_staging_dir,
            before_swap=(lambda: self.unload_plugin(plugin_id)) if dest_dir.exists() else None,
        )

        self.scan(persist_discovery=True)
        state = self.enable_plugin(plugin_id)
        logger.info("Installed and enabled plugin", extra={"plugin_id": plugin_id})
        return state

    def uninstall_plugin(self, plugin_id: str) -> None:
        """Uninstall a user-installed plugin and remove its files."""
        state = self._require_package(plugin_id)
        if state.manifest.source == "builtin":
            raise ValueError(f"Cannot uninstall builtin plugin: {plugin_id}")

        self.unload_plugin(plugin_id)

        plugin_dir = Path(state.manifest.plugin_dir)
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)

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
    def _user_plugins_root() -> Path:
        return Path("~/.magi/plugins").expanduser()

    @staticmethod
    def _extract_archive(archive_path: Path, dest: Path) -> None:
        """Extract a .tar.gz or .zip archive into *dest*."""
        name = archive_path.name.lower()
        if name.endswith(".tar.gz") or name.endswith(".tgz"):
            with tarfile.open(archive_path, "r:gz") as tf:
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
        installable_dependencies, skipped_dependencies = _filter_installable_dependencies(
            dependencies
        )
        if skipped_dependencies:
            logger.info(
                "Skipping plugin dependencies for current environment",
                extra={"deps": skipped_dependencies, "target": str(plugin_dir)},
            )
        if not installable_dependencies:
            logger.info(
                "No plugin dependencies need installation for current environment",
                extra={"target": str(plugin_dir)},
            )
            return

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
            *installable_dependencies,
        ]
        logger.info(
            "Installing plugin dependencies",
            extra={"deps": installable_dependencies, "target": str(deps_dir)},
        )
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired as exc:
            logger.exception(
                "Plugin dependency installation timed out",
                extra={"deps": installable_dependencies, "target": str(deps_dir)},
            )
            raise RuntimeError(
                f"Timed out installing plugin dependencies after {exc.timeout} seconds: "
                f"{', '.join(installable_dependencies)}"
            ) from exc
        if result.returncode != 0:
            stderr = result.stderr.strip()
            logger.error(
                "Plugin dependency installation failed",
                extra={
                    "deps": installable_dependencies,
                    "target": str(deps_dir),
                    "returncode": result.returncode,
                    "stderr": stderr,
                },
            )
            raise RuntimeError(f"Failed to install plugin dependencies: {stderr}")
        logger.info(
            "Installed plugin dependencies",
            extra={"deps": installable_dependencies, "target": str(deps_dir)},
        )
