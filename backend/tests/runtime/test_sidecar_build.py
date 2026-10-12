from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import sys

import pytest

import magi.utils.sidecar_build as sidecar_build
from magi.utils.sidecar_build import (
    build_packaged_data_entries,
    build_pyinstaller_command,
    validate_sqlite_vec_runtime_support,
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
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
    ]
    assert "--hidden-import" in command
    hidden_import_values = [
        command[index + 1] for index, value in enumerate(command[:-1]) if value == "--hidden-import"
    ]
    assert "dependency_injector.errors" in hidden_import_values
    assert "magi.db._alembic_env" in hidden_import_values
    assert {"onnxruntime", "tokenizers", "sherpa_onnx", "kaldifst", "espeakng_loader"} <= set(hidden_import_values)
    collect_all_values = [
        command[index + 1] for index, value in enumerate(command[:-1]) if value == "--collect-all"
    ]
    assert {"sherpa_onnx", "kaldifst", "espeakng_loader"} <= set(collect_all_values)
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
        command[index + 1] for index, value in enumerate(command[:-1]) if value == "--add-data"
    ]
    assert {
        f"{source}{os.pathsep}{destination}"
        for source, destination in [
            (backend_root / "configs", "configs"),
            (backend_root / "personalities", "personalities"),
            (backend_root / "src" / "magi" / "db" / "migrations", "magi/db/migrations"),
            (repo_root / "plugins" / "core-tools", "plugins/core-tools"),
            (repo_root / "skills", "skills"),
        ]
    } <= set(add_data_values)
    assert command[-1] == "run_server.py"


def test_project_checker_is_included_in_desktop_resources() -> None:
    entries = build_packaged_data_entries()
    assert any(
        source.name == "_typescript_check.cjs" and destination == "magi/tools/builtin"
        for source, destination in entries
    )


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


def test_validate_sqlite_vec_runtime_support_rejects_missing_extension_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConnection:
        def close(self) -> None:
            pass

    monkeypatch.setattr(sidecar_build.sqlite3, "connect", lambda _: FakeConnection())

    with pytest.raises(RuntimeError, match="loadable extension support"):
        validate_sqlite_vec_runtime_support()


def test_validate_sqlite_vec_runtime_support_loads_extension(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    try:
        if not hasattr(conn, "enable_load_extension"):
            pytest.skip("Python sqlite3 build does not support loadable extensions")
    finally:
        conn.close()
    observed = []

    class ObservedConnection(sqlite3.Connection):
        def close(self):
            try:
                observed.append(self.execute("SELECT vec_length('[1,2,3]')").fetchone()[0])
            finally:
                super().close()

    original_connect = sqlite3.connect
    monkeypatch.setattr(
        sidecar_build.sqlite3,
        "connect",
        lambda path: original_connect(path, factory=ObservedConnection),
    )
    validate_sqlite_vec_runtime_support()
    assert observed == [3]
