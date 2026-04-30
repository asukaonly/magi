"""Plugin package installation and removal helpers."""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

from ..awareness.scheduler_contrib import request_sensor_schedule_refresh
from ..config import save_config
from .contracts import PluginManifest, PluginPackageState

logger = logging.getLogger(__name__)


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

            if dest_dir.exists():
                self.unload_plugin(plugin_id)
                shutil.rmtree(dest_dir)

            shutil.copytree(source_dir, dest_dir)

            new_manifest = self._load_manifest(dest_dir / "plugin.toml", source="external")
            if new_manifest.dependencies:
                self._install_dependencies(new_manifest.dependencies, dest_dir)

        self.scan(persist_discovery=True)
        state = self._require_package(plugin_id)
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