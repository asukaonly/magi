"""Exact cleanup for retired user-content locations."""

from __future__ import annotations

import os
from pathlib import Path

from ..utils.runtime import RuntimePaths, get_runtime_paths


def clear_legacy_user_content(runtime_paths: RuntimePaths | None = None) -> int:
    """Delete retired memory files without following links outside Magi paths."""
    paths = runtime_paths or get_runtime_paths()
    deleted = _clear_managed_directory(paths.others_dir)
    for candidate in (
        paths.self_memory_db_path,
        Path(f"{paths.self_memory_db_path}-wal"),
        Path(f"{paths.self_memory_db_path}-shm"),
    ):
        try:
            candidate.unlink(missing_ok=False)
        except FileNotFoundError:
            continue
        else:
            deleted += 1
    return deleted


def _clear_managed_directory(root: Path) -> int:
    if root.is_symlink():
        root.unlink()
        root.mkdir(parents=True, exist_ok=True)
        return 1
    root.mkdir(parents=True, exist_ok=True)
    deleted = 0
    with os.scandir(root) as entries:
        for entry in entries:
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                deleted += _clear_managed_directory(path)
                path.rmdir()
                deleted += 1
            else:
                path.unlink(missing_ok=True)
                deleted += 1
    return deleted


__all__ = ["clear_legacy_user_content"]
