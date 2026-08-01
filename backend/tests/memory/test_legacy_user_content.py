"""Tests for removing retired user-content stores."""

from __future__ import annotations

from pathlib import Path

import pytest

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
