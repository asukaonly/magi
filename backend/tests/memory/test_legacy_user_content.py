"""Tests for removing retired user-content stores."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from magi_plugin_sdk.fs import UnsafeManagedPathError

from magi.memory.legacy_user_content import clear_legacy_user_content
from magi.utils.runtime import RuntimePaths


def test_clear_legacy_user_content_removes_exact_retired_paths(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    nested = runtime_paths.others_dir / "people" / "private.md"
    nested.parent.mkdir(parents=True)
    nested.write_text("private relationship notes", encoding="utf-8")
    runtime_paths.self_memory_db_path.write_text("private memory", encoding="utf-8")
    Path(f"{runtime_paths.self_memory_db_path}-wal").write_text(
        "private wal",
        encoding="utf-8",
    )
    Path(f"{runtime_paths.self_memory_db_path}-shm").write_text(
        "private shm",
        encoding="utf-8",
    )
    preserved_memory = runtime_paths.memory_db_path
    preserved_memory.write_text("current memory store", encoding="utf-8")
    preserved_config = runtime_paths.config_dir / "settings.yaml"
    preserved_config.parent.mkdir(parents=True, exist_ok=True)
    preserved_config.write_text("keep: true", encoding="utf-8")

    deleted = clear_legacy_user_content(runtime_paths)

    assert deleted == 5
    assert list(runtime_paths.others_dir.iterdir()) == []
    assert not runtime_paths.self_memory_db_path.exists()
    assert not Path(f"{runtime_paths.self_memory_db_path}-wal").exists()
    assert not Path(f"{runtime_paths.self_memory_db_path}-shm").exists()
    assert preserved_memory.read_text(encoding="utf-8") == "current memory store"
    assert preserved_config.read_text(encoding="utf-8") == "keep: true"


def test_clear_legacy_user_content_does_not_follow_symlinks(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    outside = tmp_path / "outside"
    outside.mkdir()
    private_file = outside / "private.md"
    private_file.write_text("must survive", encoding="utf-8")
    link = runtime_paths.others_dir / "outside-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    clear_legacy_user_content(runtime_paths)

    assert not link.exists()
    assert private_file.read_text(encoding="utf-8") == "must survive"


def test_clear_legacy_user_content_replaces_reparse_root_without_following_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    outside = tmp_path / "outside"
    outside.mkdir()
    private_file = outside / "private.md"
    private_file.write_text("must survive", encoding="utf-8")
    runtime_paths.others_dir.rmdir()
    try:
        runtime_paths.others_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory links are unavailable on this platform")

    original_lstat = os.lstat

    def reparse_lstat(path, *args, **kwargs):
        result = original_lstat(path, *args, **kwargs)
        if Path(path) == runtime_paths.others_dir and stat.S_ISLNK(result.st_mode):
            return SimpleNamespace(
                st_mode=stat.S_IFDIR | 0o700,
                st_file_attributes=0x0400,
            )
        return result

    monkeypatch.setattr(os, "lstat", reparse_lstat)

    deleted = clear_legacy_user_content(runtime_paths)

    assert deleted == 1
    assert runtime_paths.others_dir.is_dir()
    assert runtime_paths.others_dir.is_symlink() is False
    assert private_file.read_text(encoding="utf-8") == "must survive"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unsupported")
def test_clear_legacy_user_content_removes_managed_links_and_special_files_only(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    external = tmp_path / "external.db"
    external.write_text("must survive", encoding="utf-8")
    runtime_paths.self_memory_db_path.symlink_to(external)
    wal_path = Path(f"{runtime_paths.self_memory_db_path}-wal")
    os.link(external, wal_path)
    shm_path = Path(f"{runtime_paths.self_memory_db_path}-shm")
    os.mkfifo(shm_path)

    deleted = clear_legacy_user_content(runtime_paths)

    assert deleted == 3
    assert runtime_paths.self_memory_db_path.is_symlink() is False
    assert not wal_path.exists()
    assert not shm_path.exists()
    assert external.read_text(encoding="utf-8") == "must survive"


def test_clear_legacy_user_content_rejects_linked_database_parent(
    tmp_path: Path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    runtime_paths.memory_dir.rmdir()
    outside = tmp_path / "outside-memory"
    outside.mkdir()
    external_database = outside / runtime_paths.self_memory_db_path.name
    external_database.write_text("must survive", encoding="utf-8")
    try:
        runtime_paths.memory_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory links are unavailable on this platform")

    with pytest.raises(UnsafeManagedPathError):
        clear_legacy_user_content(runtime_paths)

    assert external_database.read_text(encoding="utf-8") == "must survive"
