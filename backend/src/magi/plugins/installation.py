"""Plugin package installation and removal helpers."""

from __future__ import annotations

from collections.abc import Callable
import gzip
import logging
import os
from pathlib import Path
from queue import Empty, Queue
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
import zipfile

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement

from ..awareness.scheduler_contrib import request_sensor_schedule_refresh
from ..config import save_config
from .contracts import PluginManifest, PluginPackageState

logger = logging.getLogger(__name__)
InstallProgressReporter = Callable[[str, str, float | None], None]
PLUGIN_DEPENDENCY_PYTHON_ENV = "MAGI_PLUGIN_PYTHON"
BACKEND_PYTHON_ENV = "MAGI_BACKEND_PYTHON"
ALLOW_UNLOCKED_DEPS_ENV = "MAGI_ALLOW_UNLOCKED_PLUGIN_DEPS"


def _developer_mode_allows_unlocked() -> bool:
    return os.environ.get(ALLOW_UNLOCKED_DEPS_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _report_install_progress(
    reporter: InstallProgressReporter | None,
    stage: str,
    message: str,
    progress_pct: float | None = None,
) -> None:
    if reporter is not None:
        reporter(stage, message, progress_pct)


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


def _is_frozen_runtime() -> bool:
    return bool(getattr(sys, "frozen", False))


def _looks_like_sidecar_executable(executable: str) -> bool:
    name = Path(executable).name.lower()
    return name in {"magi-backend", "magi-backend.exe"}


def _dependency_python_candidates() -> list[str]:
    candidates: list[str] = []
    for env_name in (PLUGIN_DEPENDENCY_PYTHON_ENV, BACKEND_PYTHON_ENV):
        configured = os.environ.get(env_name)
        if configured:
            candidates.append(configured)

    if not _is_frozen_runtime() and sys.executable:
        candidates.append(sys.executable)

    for executable_name in ("python3", "python"):
        discovered = shutil.which(executable_name)
        if discovered:
            candidates.append(discovered)

    unique_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(Path(candidate).expanduser())
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_candidates.append(normalized)
    return unique_candidates


def _probe_python_for_pip(executable: str) -> tuple[bool, str]:
    if _looks_like_sidecar_executable(executable):
        return False, "candidate is the Magi sidecar executable"

    probe = (
        "import importlib.util, sys; "
        "has_pip = importlib.util.find_spec('pip') is not None; "
        "print(f'{sys.version_info.major}.{sys.version_info.minor} {int(has_pip)}')"
    )
    try:
        result = subprocess.run(
            [executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)

    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip() or "probe failed"

    output = result.stdout.strip().split()
    if len(output) != 2:
        return False, "probe returned an unexpected response"

    expected_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if output[0] != expected_version:
        return False, f"Python {output[0]} does not match runtime Python {expected_version}"
    if output[1] != "1":
        return False, "pip is not importable"
    return True, ""


def _resolve_dependency_python_executable() -> str:
    rejected: list[str] = []
    for candidate in _dependency_python_candidates():
        ok, reason = _probe_python_for_pip(candidate)
        if ok:
            return candidate
        rejected.append(f"{candidate}: {reason}")

    expected_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    details = "; ".join(rejected) if rejected else "no candidate Python executable found"
    raise RuntimeError(
        "Cannot install plugin dependencies because no Python interpreter with pip is available. "
        f"Set {PLUGIN_DEPENDENCY_PYTHON_ENV} to a Python {expected_version} executable with pip. "
        f"Checked: {details}"
    )


def _build_dependency_install_command(
    lock_path: Path,
    deps_dir: Path,
    *,
    quiet: bool,
) -> list[str]:
    cmd = [
        _resolve_dependency_python_executable(),
        "-m",
        "pip",
        "install",
        "--target",
        str(deps_dir),
        "--no-user",
        "--disable-pip-version-check",
        "--require-hashes",
        "-r",
        str(lock_path),
    ]
    if quiet:
        cmd.insert(cmd.index("--require-hashes"), "--quiet")
    return cmd


def _build_loose_dependency_install_command(
    dependencies: list[str],
    deps_dir: Path,
    *,
    quiet: bool,
) -> list[str]:
    """Unverified, range-based install. Developer-mode fallback only."""
    cmd = [
        _resolve_dependency_python_executable(),
        "-m",
        "pip",
        "install",
        "--target",
        str(deps_dir),
        "--no-user",
        "--disable-pip-version-check",
        *dependencies,
    ]
    if quiet and dependencies:
        cmd.insert(-len(dependencies), "--quiet")
    return cmd


class UnlockedDependencyError(RuntimeError):
    """Raised when a plugin declares dependencies but ships no requirements.lock."""


def _resolve_lock_or_policy(
    dependencies: list[str],
    plugin_dir: Path,
    *,
    allow_unlocked: bool,
) -> Path | list[str] | None:
    """Decide how to install a plugin's dependencies.

    Returns:
      - None       when the plugin declares no dependencies.
      - Path       to requirements.lock when present (hash-enforced install).
      - list[str]  the raw dependency list when no lock exists AND developer
                   mode permits an unverified loose install.

    Raises UnlockedDependencyError when deps are declared, no lock exists, and
    developer mode is off (the default, secure path).
    """
    if not dependencies:
        return None
    lock_path = plugin_dir / "requirements.lock"
    if lock_path.exists():
        return lock_path
    if allow_unlocked:
        return dependencies
    raise UnlockedDependencyError(
        "This plugin declares dependencies but ships no integrity-locked "
        "requirements.lock. Refusing to install unverified dependencies. "
        "Set MAGI_ALLOW_UNLOCKED_PLUGIN_DEPS=1 to override (developer mode)."
    )


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
        user_root = self._user_plugins_root()
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

            replace_plugin_directory(
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
            self._extract_archive(archive_path, tmp_path)
            manifest_file = self._find_manifest_in_tree(tmp_path)
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

        replace_plugin_directory(
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

        request_sensor_schedule_refresh()
        return gc_removed

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
        """Extract a .tar.gz or .zip archive into *dest*.

        Raises ``ValueError`` for an unsupported, corrupt/truncated, or
        path-unsafe archive. Corrupt-archive errors (``tarfile.ReadError``,
        ``gzip.BadGzipFile``, ``zipfile.BadZipFile``, truncation ``EOFError``)
        are re-raised as ``ValueError`` so upload routes surface a clean HTTP
        400 ("not a valid archive") instead of an unhandled 500.
        """
        name = archive_path.name.lower()
        if name.endswith(".tar.gz") or name.endswith(".tgz"):
            try:
                with tarfile.open(archive_path, "r:gz") as tf:
                    for member in tf.getmembers():
                        if member.name.startswith("/") or ".." in member.name.split("/"):
                            raise ValueError(f"Unsafe path in archive: {member.name}")
                    tf.extractall(dest)
            except (tarfile.TarError, gzip.BadGzipFile, EOFError) as exc:
                raise ValueError(f"Not a valid .tar.gz archive: {exc}") from exc
        elif name.endswith(".zip"):
            try:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    for info in zf.infolist():
                        if info.filename.startswith("/") or ".." in info.filename.split("/"):
                            raise ValueError(f"Unsafe path in archive: {info.filename}")
                        extracted_str = zf.extract(info, dest)
                        if not info.is_dir():
                            # zipfile.extract drops Unix permissions even when the
                            # archive was created on Unix. Recover the mode from
                            # external_attr's upper 16 bits (per PKZIP spec).
                            mode = (info.external_attr >> 16) & 0o777
                            if mode:
                                Path(extracted_str).chmod(mode)
            except zipfile.BadZipFile as exc:
                raise ValueError(f"Not a valid .zip archive: {exc}") from exc
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
    def _install_dependencies(
        dependencies: list[str],
        plugin_dir: Path,
        *,
        progress_reporter: InstallProgressReporter | None = None,
    ) -> None:
        """Install plugin dependencies into a local .deps/ directory.

        Hash-enforced from requirements.lock by default; falls back to a loose,
        unverified install only in developer mode (see _resolve_lock_or_policy).
        """
        allow_unlocked = _developer_mode_allows_unlocked()
        resolved = _resolve_lock_or_policy(
            dependencies, plugin_dir, allow_unlocked=allow_unlocked
        )
        if resolved is None:
            logger.info(
                "No plugin dependencies need installation",
                extra={"target": str(plugin_dir)},
            )
            _report_install_progress(
                progress_reporter,
                "dependencies",
                "No plugin dependencies need installation",
                82.0,
            )
            return

        deps_dir = plugin_dir / ".deps"
        deps_dir.mkdir(exist_ok=True)

        if isinstance(resolved, Path):
            cmd = _build_dependency_install_command(
                resolved, deps_dir, quiet=progress_reporter is None
            )
            install_label = f"Installing locked plugin dependencies from {resolved.name}"
        else:
            logger.warning(
                "Installing UNVERIFIED plugin dependencies (developer mode; no "
                "requirements.lock). This bypasses supply-chain integrity checks.",
                extra={"deps": resolved, "target": str(deps_dir)},
            )
            installable, skipped = _filter_installable_dependencies(resolved)
            if skipped:
                logger.info(
                    "Skipping plugin dependencies for current environment",
                    extra={"deps": skipped, "target": str(deps_dir)},
                )
            if not installable:
                _report_install_progress(
                    progress_reporter,
                    "dependencies",
                    "No plugin dependencies need installation",
                    82.0,
                )
                return
            cmd = _build_loose_dependency_install_command(
                installable, deps_dir, quiet=progress_reporter is None
            )
            install_label = (
                f"Installing UNVERIFIED plugin dependencies: {', '.join(installable)}"
            )

        logger.info(install_label, extra={"target": str(deps_dir), "python": cmd[0]})
        _report_install_progress(progress_reporter, "dependencies", install_label, 56.0)
        try:
            if progress_reporter is None:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            else:
                result = _run_dependency_install_with_progress(cmd, progress_reporter)
        except subprocess.TimeoutExpired as exc:
            logger.exception(
                "Plugin dependency installation timed out",
                extra={"target": str(deps_dir)},
            )
            raise RuntimeError(
                f"Timed out installing plugin dependencies after {exc.timeout} seconds"
            ) from exc
        if result.returncode != 0:
            stderr = result.stderr.strip()
            logger.error(
                "Plugin dependency installation failed",
                extra={
                    "target": str(deps_dir),
                    "returncode": result.returncode,
                    "stderr": stderr,
                },
            )
            raise RuntimeError(f"Plugin dependency installation failed: {stderr}")
        _report_install_progress(
            progress_reporter, "dependencies", "Installed plugin dependencies", 82.0
        )


def _run_dependency_install_with_progress(
    cmd: list[str],
    progress_reporter: InstallProgressReporter,
) -> subprocess.CompletedProcess[str]:
    output_lines: list[str] = []
    output_queue: Queue[str] = Queue()
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def read_output() -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            output_queue.put(line)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    deadline = time.monotonic() + 300

    while process.poll() is None:
        try:
            line = output_queue.get(timeout=0.1)
        except Empty:
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=5)
                raise subprocess.TimeoutExpired(cmd, 300)
            continue
        text = line.strip()
        if text:
            output_lines.append(text)
            _report_install_progress(progress_reporter, "dependencies", text)

    reader.join(timeout=1.0)
    while True:
        try:
            line = output_queue.get_nowait()
        except Empty:
            break
        text = line.strip()
        if text:
            output_lines.append(text)
            _report_install_progress(progress_reporter, "dependencies", text)

    stdout = "\n".join(output_lines)
    return subprocess.CompletedProcess(cmd, process.returncode or 0, stdout=stdout, stderr=stdout)
