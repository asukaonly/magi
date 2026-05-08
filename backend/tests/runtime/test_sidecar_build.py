from __future__ import annotations

import os
from pathlib import Path

from magi.utils.sidecar_build import (
    build_packaged_binary_entries,
    build_packaged_data_entries,
    build_pyinstaller_command,
)


def test_build_pyinstaller_command_includes_required_hidden_imports(tmp_path: Path) -> None:
    backend_root = tmp_path / "backend"
    repo_root = tmp_path / "repo"
    (backend_root / "configs").mkdir(parents=True)
    (backend_root / "personalities").mkdir(parents=True)
    (backend_root / "src" / "magi" / "db" / "migrations" / "chat").mkdir(parents=True)
    (repo_root / "plugins" / "core-tools").mkdir(parents=True)
    (repo_root / "skills").mkdir(parents=True)

    command = build_pyinstaller_command(repo_root=repo_root, backend_root=backend_root)

    assert command[:6] == [
        "python",
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
    ]
    assert "--hidden-import" in command
    hidden_import_values = [
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "--hidden-import"
    ]
    assert "dependency_injector.errors" in hidden_import_values
    assert "magi.db._alembic_env" in hidden_import_values
    collect_submodules_values = [
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "--collect-submodules"
    ]
    assert "dependency_injector" in collect_submodules_values
    collect_binaries_values = [
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "--collect-binaries"
    ]
    assert "sqlite_vec" in collect_binaries_values
    add_data_values = [
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "--add-data"
    ]
    assert any(value.endswith(f"{os.pathsep}configs") for value in add_data_values)
    assert any(value.endswith(f"{os.pathsep}personalities") for value in add_data_values)
    assert any(value.endswith(f"{os.pathsep}magi/db/migrations") for value in add_data_values)
    assert any(value.endswith(f"{os.pathsep}plugins/core-tools") for value in add_data_values)
    assert any(value.endswith(f"{os.pathsep}skills") for value in add_data_values)
    assert command[-1] == "run_server.py"


def test_build_packaged_data_entries_uses_repo_and_backend_roots(tmp_path: Path) -> None:
    backend_root = tmp_path / "backend"
    repo_root = tmp_path / "repo"
    (backend_root / "configs").mkdir(parents=True)
    (backend_root / "personalities").mkdir(parents=True)
    (backend_root / "src" / "magi" / "db" / "migrations").mkdir(parents=True)
    (repo_root / "plugins" / "core-tools").mkdir(parents=True)
    (repo_root / "skills").mkdir(parents=True)

    entries = build_packaged_data_entries(
        repo_root=repo_root,
        backend_root=backend_root,
    )

    assert (backend_root / "configs", "configs") in entries
    assert (backend_root / "personalities", "personalities") in entries
    assert (backend_root / "src" / "magi" / "db" / "migrations", "magi/db/migrations") in entries
    assert (repo_root / "plugins" / "core-tools", "plugins/core-tools") in entries
    assert (repo_root / "skills", "skills") in entries


def test_build_packaged_binary_entries_includes_vendored_ripgrep(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    executable_name = "rg.exe" if os.name == "nt" else "rg"
    binary_path = repo_root / "runtime" / "bin" / "ripgrep" / "test-platform" / executable_name
    binary_path.parent.mkdir(parents=True)
    binary_path.write_text("fake ripgrep", encoding="utf-8")

    entries = build_packaged_binary_entries(repo_root=repo_root)

    assert (binary_path, "runtime/bin/ripgrep/test-platform") in entries


def test_build_pyinstaller_command_includes_vendored_ripgrep_binary(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    backend_root = tmp_path / "backend"
    executable_name = "rg.exe" if os.name == "nt" else "rg"
    binary_path = repo_root / "runtime" / "bin" / "ripgrep" / "test-platform" / executable_name
    binary_path.parent.mkdir(parents=True)
    binary_path.write_text("fake ripgrep", encoding="utf-8")
    (backend_root / "configs").mkdir(parents=True)

    command = build_pyinstaller_command(repo_root=repo_root, backend_root=backend_root)
    add_binary_values = [
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "--add-binary"
    ]

    assert f"{binary_path}{os.pathsep}runtime/bin/ripgrep/test-platform" in add_binary_values
