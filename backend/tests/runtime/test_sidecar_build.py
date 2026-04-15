from __future__ import annotations

import os
from pathlib import Path

from magi.utils.sidecar_build import build_packaged_data_entries, build_pyinstaller_command


def test_build_pyinstaller_command_includes_required_hidden_imports() -> None:
    command = build_pyinstaller_command()

    assert command[:6] == [
        "python",
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
    ]
    assert "--hidden-import" in command
    hidden_import_values = [
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "--hidden-import"
    ]
    assert "dependency_injector.errors" in hidden_import_values
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
    assert any(value.endswith(f"{os.pathsep}plugins") for value in add_data_values)
    assert any(value.endswith(f"{os.pathsep}skills") for value in add_data_values)
    assert command[-1] == "run_server.py"


def test_build_packaged_data_entries_uses_repo_and_backend_roots(tmp_path: Path) -> None:
    backend_root = tmp_path / "backend"
    repo_root = tmp_path / "repo"
    (backend_root / "configs").mkdir(parents=True)
    (backend_root / "personalities").mkdir(parents=True)
    (repo_root / "plugins").mkdir(parents=True)
    (repo_root / "skills").mkdir(parents=True)

    entries = build_packaged_data_entries(
        repo_root=repo_root,
        backend_root=backend_root,
    )

    assert (backend_root / "configs", "configs") in entries
    assert (backend_root / "personalities", "personalities") in entries
    assert (repo_root / "plugins", "plugins") in entries
    assert (repo_root / "skills", "skills") in entries
