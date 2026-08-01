"""Exact cleanup for retired user-content locations."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from magi_plugin_sdk.fs import (
    list_managed_directory_names,
    path_is_link,
    remove_managed_file,
)

from ..utils.runtime import RuntimePaths, get_runtime_paths


_SQLITE_FILE_SUFFIXES = ("", "-wal", "-shm", "-journal")
_TEMPFILE_RANDOM_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def clear_legacy_user_content(runtime_paths: RuntimePaths | None = None) -> int:
    """Delete retired memory files without following links outside Magi paths."""
    paths = runtime_paths or get_runtime_paths()
    deleted = _clear_managed_directory(paths.others_dir)
    for suffix in _SQLITE_FILE_SUFFIXES:
        candidate = Path(f"{paths.self_memory_db_path}{suffix}")
        if remove_managed_file(candidate):
            deleted += 1
    deleted += _clear_retired_orchestration_temp_files(paths.runtime_dir)
    return deleted


def _clear_retired_orchestration_temp_files(root: Path) -> int:
    """Delete crash leftovers created by the retired anonymous temp writer."""
    deleted = 0
    for name in list_managed_directory_names(root):
        if not _is_retired_orchestration_temp_name(name):
            continue
        if remove_managed_file(root / name):
            deleted += 1
    return deleted


def _is_retired_orchestration_temp_name(name: str) -> bool:
    if not name.startswith("tmp") or not name.endswith(".tmp"):
        return False
    random_part = name[3:-4]
    return len(random_part) == 8 and all(
        character in _TEMPFILE_RANDOM_CHARACTERS for character in random_part
    )


def _clear_managed_directory(root: Path) -> int:
    try:
        root_stat = os.lstat(root)
    except FileNotFoundError:
        root.mkdir(parents=True, exist_ok=True)
        return 0
    if path_is_link(root, path_stat=root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        removed = remove_managed_file(root)
        root.mkdir(parents=True, exist_ok=False)
        return int(removed)

    return _clear_real_directory(root)


def _clear_real_directory(root: Path) -> int:
    deleted = 0
    with os.scandir(root) as entries:
        for entry in entries:
            path = Path(entry.path)
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if path_is_link(path, path_stat=entry_stat) or not stat.S_ISDIR(entry_stat.st_mode):
                if remove_managed_file(path):
                    deleted += 1
                continue

            deleted += _clear_real_directory(path)
            try:
                current_stat = os.lstat(path)
            except FileNotFoundError:
                continue
            if path_is_link(path, path_stat=current_stat) or not stat.S_ISDIR(current_stat.st_mode):
                if remove_managed_file(path):
                    deleted += 1
            else:
                path.rmdir()
                deleted += 1
    return deleted


__all__ = ["clear_legacy_user_content"]
