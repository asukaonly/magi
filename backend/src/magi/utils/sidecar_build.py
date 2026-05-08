"""Helpers for building the desktop Python sidecar with PyInstaller."""

from __future__ import annotations

import importlib
import importlib.util
import os
import platform
import shutil
import sys
from pathlib import Path

SIDE_EFFECT_HIDDEN_IMPORTS = (
    # dependency_injector C extensions import this module dynamically at runtime.
    "dependency_injector.errors",
    # ssl._encode_hostname calls codecs.lookup('idna') dynamically; PyInstaller
    # cannot detect this so the codec must be listed explicitly.
    "encodings.idna",
    # Alembic loads migration env.py files from packaged data at runtime; those
    # env files import this helper dynamically outside PyInstaller's graph.
    "magi.db._alembic_env",
    # Local embedding / reranker are behind lazy ``try: import`` guards but are
    # mandatory dependencies — always include them.
    "onnxruntime",
    "tokenizers",
    "huggingface_hub",
)

# Packages whose submodules are loaded dynamically and must be collected in
# full so that PyInstaller includes every internal module.
COLLECT_SUBMODULE_PACKAGES = (
    "dependency_injector",
    # jieba lazy-loads dictionary data files from its package directory.
    "jieba",
    # dateparser.search is imported lazily at call sites.
    "dateparser",
)

COLLECT_BINARY_PACKAGES = (
    # sqlite-vec ships its loadable SQLite extension as a package binary.
    "sqlite_vec",
)

# Packages from optional dependency groups that should be bundled when they
# are installed in the build environment.  PyInstaller cannot discover them
# because they are behind ``try: import … except ImportError`` guards.
OPTIONAL_HIDDEN_IMPORTS = (
    # Windows media control (Windows only)
    "winrt.windows.media.control",
)

PACKAGE_DATA_DIRECTORIES = (
    ("configs", "configs"),
    ("personalities", "personalities"),
    ("skills", "skills"),
)

# Only core plugins are shipped inside the sidecar binary.
# Optional plugins are installed at runtime from the plugin registry.
CORE_PLUGIN_IDS = (
    "core-tools",
)

RUNTIME_BINARY_DIRECTORIES = (
    ("runtime/bin/ripgrep", "runtime/bin/ripgrep"),
)


def _platform_key() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def _architecture_key() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64", "x64"}:
        return "x64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    return machine or "unknown"


def _ripgrep_executable_name() -> str:
    return "rg.exe" if os.name == "nt" else "rg"


def _detect_optional_hidden_imports() -> list[str]:
    """Return optional hidden imports that are actually installed."""
    found: list[str] = []
    for module_name in OPTIONAL_HIDDEN_IMPORTS:
        try:
            if importlib.util.find_spec(module_name) is not None:
                found.append(module_name)
        except (ModuleNotFoundError, ValueError):
            pass
    return found


def build_packaged_data_entries(
    *,
    repo_root: Path | None = None,
    backend_root: Path | None = None,
) -> list[tuple[Path, str]]:
    """Return runtime data directories that must ship with the sidecar."""
    resolved_repo_root = (repo_root or Path(__file__).resolve().parents[4]).resolve()
    resolved_backend_root = (backend_root or Path(__file__).resolve().parents[3]).resolve()
    source_roots = {
        "configs": resolved_backend_root,
        "personalities": resolved_backend_root,
        "skills": resolved_repo_root,
    }

    entries: list[tuple[Path, str]] = []
    for source_name, destination_name in PACKAGE_DATA_DIRECTORIES:
        source_path = source_roots[source_name] / source_name
        if source_path.exists():
            entries.append((source_path, destination_name))

    migrations_path = resolved_backend_root / "src" / "magi" / "db" / "migrations"
    if migrations_path.exists():
        entries.append((migrations_path, "magi/db/migrations"))

    # Include only core plugins as individual directories.
    plugins_root = resolved_repo_root / "plugins"
    for plugin_id in CORE_PLUGIN_IDS:
        plugin_path = plugins_root / plugin_id
        if plugin_path.exists():
            entries.append((plugin_path, f"plugins/{plugin_id}"))

    return entries


def build_packaged_binary_entries(
    *,
    repo_root: Path | None = None,
) -> list[tuple[Path, str]]:
    """Return runtime binary files that should ship with the sidecar."""
    resolved_repo_root = (repo_root or Path(__file__).resolve().parents[4]).resolve()
    entries: list[tuple[Path, str]] = []
    executable_name = _ripgrep_executable_name()

    for source_name, destination_name in RUNTIME_BINARY_DIRECTORIES:
        source_path = resolved_repo_root / source_name
        if not source_path.exists():
            continue
        for binary_path in source_path.rglob(executable_name):
            if not binary_path.is_file():
                continue
            relative_parent = binary_path.relative_to(source_path).parent
            destination_path = Path(destination_name) / relative_parent
            entries.append((binary_path, destination_path.as_posix()))

    if entries:
        return entries

    system_ripgrep = shutil.which("rg")
    if system_ripgrep:
        destination = f"runtime/bin/ripgrep/{_platform_key()}-{_architecture_key()}"
        return [(Path(system_ripgrep).resolve(), destination)]

    return []


def build_pyinstaller_command(
    *,
    entry_script: str = "run_server.py",
    name: str = "magi-backend",
    repo_root: Path | None = None,
    backend_root: Path | None = None,
) -> list[str]:
    """Return the PyInstaller command used for desktop sidecar builds."""
    command = [
        "python",
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        name,
    ]
    for module_name in SIDE_EFFECT_HIDDEN_IMPORTS:
        command.extend(["--hidden-import", module_name])
    for module_name in _detect_optional_hidden_imports():
        command.extend(["--hidden-import", module_name])
    for package_name in COLLECT_SUBMODULE_PACKAGES:
        command.extend(["--collect-submodules", package_name])
    for package_name in COLLECT_BINARY_PACKAGES:
        command.extend(["--collect-binaries", package_name])
    for source_path, destination_name in build_packaged_data_entries(
        repo_root=repo_root,
        backend_root=backend_root,
    ):
        command.extend(["--add-data", f"{source_path}{os.pathsep}{destination_name}"])
    for source_path, destination_name in build_packaged_binary_entries(repo_root=repo_root):
        command.extend(["--add-binary", f"{source_path}{os.pathsep}{destination_name}"])
    command.append(entry_script)
    return command
