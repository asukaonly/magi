"""Protect Magi-owned local data from access by other system accounts."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
from pathlib import Path
import stat
import sys


class PrivateDataProtectionError(RuntimeError):
    """Raised when the Magi data tree cannot be protected without leaving its boundary."""


@dataclass(frozen=True)
class PrivateDataProtectionResult:
    """Count of Magi-owned entries validated and protected during startup."""

    protected_directories: int
    protected_files: int


def protect_private_data_tree(base_dir: Path) -> PrivateDataProtectionResult:
    """Create, validate, and restrict one Magi-owned data tree.

    Unix permissions are repaired directly. Windows access lists are applied by
    the desktop host before Python starts; the worker repeats the boundary walk
    here to reject links and other indirection before it opens private data.
    """

    root = Path(os.path.abspath(os.fspath(base_dir)))
    _ensure_real_root(root)
    if sys.platform == "win32":
        return _validate_windows_tree(root)
    return _protect_unix_tree(root)


def _ensure_real_root(root: Path) -> None:
    try:
        root_stat = os.lstat(root)
    except FileNotFoundError:
        root.parent.mkdir(parents=True, exist_ok=True)
        parent_stat = os.lstat(root.parent)
        if _is_link_or_reparse(parent_stat) or not stat.S_ISDIR(parent_stat.st_mode):
            raise PrivateDataProtectionError("Magi data root parent must be a real directory")
        try:
            root.mkdir(mode=0o700)
        except FileExistsError:
            pass
        root_stat = os.lstat(root)

    if _is_link_or_reparse(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise PrivateDataProtectionError("Magi data root must be a real directory")


def _is_link_or_reparse(path_stat: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        getattr(path_stat, "st_file_attributes", 0) & reparse_flag
    )


def _protect_unix_tree(root: Path) -> PrivateDataProtectionResult:
    current_uid = os.geteuid()
    protected_directories = 0
    protected_files = 0
    stack = [root]

    while stack:
        path = stack.pop()
        path_stat = os.lstat(path)
        _validate_entry(path, path_stat)
        if path_stat.st_uid != current_uid:
            raise PrivateDataProtectionError(
                f"Magi data path is not owned by the current account: {path}"
            )
        if stat.S_ISREG(path_stat.st_mode) and path_stat.st_nlink != 1:
            raise PrivateDataProtectionError(
                f"Magi data file must not have external hard links: {path}"
            )

        if sys.platform == "darwin":
            _clear_macos_extended_acl(path)
        if stat.S_ISDIR(path_stat.st_mode):
            os.chmod(path, 0o700, follow_symlinks=False)
            protected_directories += 1
            try:
                children = sorted(
                    (Path(entry.path) for entry in os.scandir(path)),
                    key=lambda child: child.name,
                    reverse=True,
                )
            except OSError as exc:
                raise PrivateDataProtectionError(
                    f"Failed to enumerate private Magi directory: {path}"
                ) from exc
            stack.extend(children)
        else:
            owner_executable = bool(path_stat.st_mode & stat.S_IXUSR)
            os.chmod(path, 0o700 if owner_executable else 0o600, follow_symlinks=False)
            protected_files += 1

    return PrivateDataProtectionResult(
        protected_directories=protected_directories,
        protected_files=protected_files,
    )


def _validate_windows_tree(root: Path) -> PrivateDataProtectionResult:
    protected_directories = 0
    protected_files = 0
    stack = [root]
    while stack:
        path = stack.pop()
        path_stat = os.lstat(path)
        _validate_entry(path, path_stat)
        if stat.S_ISREG(path_stat.st_mode) and path_stat.st_nlink != 1:
            raise PrivateDataProtectionError(
                f"Magi data file must not have external hard links: {path}"
            )
        if stat.S_ISDIR(path_stat.st_mode):
            protected_directories += 1
            try:
                children = sorted(
                    (Path(entry.path) for entry in os.scandir(path)),
                    key=lambda child: child.name,
                    reverse=True,
                )
            except OSError as exc:
                raise PrivateDataProtectionError(
                    f"Failed to enumerate private Magi directory: {path}"
                ) from exc
            stack.extend(children)
        else:
            protected_files += 1
    return PrivateDataProtectionResult(
        protected_directories=protected_directories,
        protected_files=protected_files,
    )


def _validate_entry(path: Path, path_stat: os.stat_result) -> None:
    if _is_link_or_reparse(path_stat):
        raise PrivateDataProtectionError(f"Magi data path must not be a link: {path}")


def _clear_macos_extended_acl(path: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    acl_init = libc.acl_init
    acl_init.argtypes = [ctypes.c_int]
    acl_init.restype = ctypes.c_void_p
    acl_set_file = libc.acl_set_file
    acl_set_file.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
    acl_set_file.restype = ctypes.c_int
    acl_free = libc.acl_free
    acl_free.argtypes = [ctypes.c_void_p]
    acl_free.restype = ctypes.c_int

    acl = acl_init(0)
    if not acl:
        error = ctypes.get_errno()
        raise PrivateDataProtectionError(
            f"Failed to allocate an empty access-control list: {os.strerror(error)}"
        )
    try:
        if acl_set_file(os.fsencode(path), 0x00000100, acl) != 0:
            error = ctypes.get_errno()
            raise PrivateDataProtectionError(
                f"Failed to remove extended access rules from {path}: {os.strerror(error)}"
            )
    finally:
        acl_free(acl)
