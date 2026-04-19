"""Helpers for building the desktop Python sidecar with PyInstaller."""

from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path

SIDE_EFFECT_HIDDEN_IMPORTS = (
    # dependency_injector C extensions import this module dynamically at runtime.
    "dependency_injector.errors",
    # ssl._encode_hostname calls codecs.lookup('idna') dynamically; PyInstaller
    # cannot detect this so the codec must be listed explicitly.
    "encodings.idna",
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
    # local-embedding extra
    "onnxruntime",
    "tokenizers",
    "huggingface_hub",
    # channels extra
    "telegram",
    # Windows media control (Windows only)
    "winrt.windows.media.control",
)

PACKAGE_DATA_DIRECTORIES = (
    ("configs", "configs"),
    ("personalities", "personalities"),
    ("plugins", "plugins"),
    ("skills", "skills"),
)


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
        "plugins": resolved_repo_root,
        "skills": resolved_repo_root,
    }

    entries: list[tuple[Path, str]] = []
    for source_name, destination_name in PACKAGE_DATA_DIRECTORIES:
        source_path = source_roots[source_name] / source_name
        if source_path.exists():
            entries.append((source_path, destination_name))
    return entries


def build_pyinstaller_command(
    *,
    entry_script: str = "run_server.py",
    name: str = "magi-backend",
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
    for source_path, destination_name in build_packaged_data_entries():
        command.extend(["--add-data", f"{source_path}{os.pathsep}{destination_name}"])
    command.append(entry_script)
    return command
