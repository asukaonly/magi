"""Atomic file IO + cross-platform exclusive file lock.

Canonical home for pure file-IO helpers shared by the host and plugins.
Plugins import from here; the host re-exports from
magi.agent.workspace_cache.{atomic_io,locking} for back-compat.
"""

from __future__ import annotations

import errno
import json
import os
import secrets
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, Iterable, Iterator, Mapping

_IS_WINDOWS = sys.platform == "win32"
_DEFAULT_MANAGED_READ_MAX_BYTES = 8 * 1024 * 1024


class UnsafeManagedPathError(RuntimeError):
    """Raised when a plugin-managed file path could escape through indirection."""


if _IS_WINDOWS:
    import msvcrt

    def _acquire(f: IO) -> None:
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

    def _release(f: IO) -> None:
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def _acquire(f: IO) -> None:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)

    def _release(f: IO) -> None:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


@contextmanager
def file_lock(f: IO) -> Iterator[None]:
    """Acquire an exclusive lock on the open file handle for the block."""
    _acquire(f)
    try:
        yield
    finally:
        _release(f)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as f:
            with file_lock(f):
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def path_is_link(
    path: str | Path,
    *,
    path_stat: os.stat_result | Any | None = None,
) -> bool:
    """Detect a symbolic link or Windows reparse-point directory link.

    ``Path.is_junction`` is unavailable on older supported Python versions, so
    the file-attribute fallback keeps junction handling consistent on 3.10+.
    """

    normalized = Path(path)
    if normalized.is_symlink():
        return True
    is_junction = getattr(normalized, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    if path_stat is None:
        try:
            path_stat = os.lstat(normalized)
        except FileNotFoundError:
            return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    return bool(getattr(path_stat, "st_file_attributes", 0) & reparse_flag)


def _validate_managed_file_path(
    path: str | Path,
) -> tuple[Path, Path, tuple[int, int]]:
    target = Path(path)
    if target.name in {"", ".", ".."}:
        raise UnsafeManagedPathError("Managed file path must name one file")
    parent = target.parent
    directory_chain = [parent, *parent.parents]
    parent_identity: tuple[int, int] | None = None
    for directory in reversed(directory_chain):
        try:
            directory_stat = os.lstat(directory)
        except FileNotFoundError as exc:
            raise UnsafeManagedPathError(
                "Managed file parent directory does not exist"
            ) from exc
        if path_is_link(directory, path_stat=directory_stat) or not stat.S_ISDIR(
            directory_stat.st_mode
        ):
            raise UnsafeManagedPathError(
                "Managed file parent chain must contain only real directories"
            )
        if directory == parent:
            parent_identity = (directory_stat.st_dev, directory_stat.st_ino)
    if parent_identity is None:
        raise UnsafeManagedPathError("Managed file parent identity is unavailable")
    return target, parent, parent_identity


def _managed_directory_parent_chain_exists(path: Path) -> bool:
    parent = path.parent
    missing_ancestor = False
    for directory in reversed([parent, *parent.parents]):
        try:
            directory_stat = os.lstat(directory)
        except FileNotFoundError:
            missing_ancestor = True
            continue
        if missing_ancestor:
            raise UnsafeManagedPathError(
                "Managed directory parent chain changed during validation"
            )
        if path_is_link(directory, path_stat=directory_stat) or not stat.S_ISDIR(
            directory_stat.st_mode
        ):
            raise UnsafeManagedPathError(
                "Managed directory parent chain must contain only real directories"
            )
    return not missing_ancestor


def _managed_directory_identity(path: Path) -> tuple[int, int] | None:
    if path.name in {"", ".", ".."}:
        raise UnsafeManagedPathError("Managed directory path must name one directory")
    if not _managed_directory_parent_chain_exists(path):
        return None
    try:
        directory_stat = os.lstat(path)
    except FileNotFoundError:
        return None
    if path_is_link(path, path_stat=directory_stat) or not stat.S_ISDIR(
        directory_stat.st_mode
    ):
        raise UnsafeManagedPathError("Managed directory must be a real directory")
    _, validated_directory, identity = _validate_managed_file_path(
        path / ".magi-managed-directory-validation"
    )
    if validated_directory != path or identity != (
        directory_stat.st_dev,
        directory_stat.st_ino,
    ):
        raise UnsafeManagedPathError("Managed directory changed during validation")
    return identity


def _validate_managed_target_type(path: Path) -> os.stat_result | Any | None:
    try:
        target_stat = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISDIR(target_stat.st_mode) and not path_is_link(
        path,
        path_stat=target_stat,
    ):
        raise UnsafeManagedPathError("Managed file target must not be a directory")
    return target_stat


def _validate_managed_read_limit(max_bytes: int) -> int:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    return max_bytes


def _managed_file_is_readable(target_stat: os.stat_result) -> bool:
    return stat.S_ISREG(target_stat.st_mode) and target_stat.st_nlink == 1


def _read_file_descriptor(fd: int, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining > 0:
        chunk = os.read(fd, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    payload = b"".join(chunks)
    if len(payload) > max_bytes:
        raise UnsafeManagedPathError("Managed file exceeds the safe read limit")
    return payload


def _read_managed_posix(path: Path, *, max_bytes: int) -> bytes | None:
    target, parent, parent_identity = _validate_managed_file_path(path)
    directory_fd = _open_managed_directory(
        parent,
        expected_identity=parent_identity,
    )
    file_fd: int | None = None
    try:
        try:
            target_stat = os.stat(
                target.name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return None
        if not _managed_file_is_readable(target_stat):
            return None
        if target_stat.st_size > max_bytes:
            raise UnsafeManagedPathError("Managed file exceeds the safe read limit")

        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            file_fd = os.open(target.name, flags, dir_fd=directory_fd)
        except FileNotFoundError:
            return None
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENXIO}:
                return None
            raise
        opened_stat = os.fstat(file_fd)
        if not _managed_file_is_readable(opened_stat) or (
            opened_stat.st_dev,
            opened_stat.st_ino,
        ) != (target_stat.st_dev, target_stat.st_ino):
            return None
        return _read_file_descriptor(file_fd, max_bytes=max_bytes)
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)


def _read_managed_windows(path: Path, *, max_bytes: int) -> bytes | None:
    target, _, parent_identity = _validate_managed_file_path(path)
    try:
        target_stat = os.lstat(target)
    except FileNotFoundError:
        return None
    if not _managed_file_is_readable(target_stat):
        return None
    if target_stat.st_size > max_bytes:
        raise UnsafeManagedPathError("Managed file exceeds the safe read limit")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    file_fd = os.open(target, flags)
    try:
        _, _, current_identity = _validate_managed_file_path(target)
        opened_stat = os.fstat(file_fd)
        if (
            current_identity != parent_identity
            or not _managed_file_is_readable(opened_stat)
            or (opened_stat.st_dev, opened_stat.st_ino)
            != (target_stat.st_dev, target_stat.st_ino)
        ):
            return None
        return _read_file_descriptor(file_fd, max_bytes=max_bytes)
    finally:
        os.close(file_fd)


def read_managed_bytes(
    path: str | Path,
    *,
    max_bytes: int = _DEFAULT_MANAGED_READ_MAX_BYTES,
) -> bytes | None:
    """Read one bounded plugin state file without following links.

    Missing files, links, hard links, directories, and special files return
    ``None``. An unsafe parent chain or an oversized regular file fails closed.
    """

    normalized_limit = _validate_managed_read_limit(max_bytes)
    target = Path(path)
    try:
        os.lstat(target.parent)
    except FileNotFoundError:
        return None
    if _IS_WINDOWS:
        return _read_managed_windows(target, max_bytes=normalized_limit)
    return _read_managed_posix(target, max_bytes=normalized_limit)


def read_managed_text(
    path: str | Path,
    *,
    encoding: str = "utf-8",
    max_bytes: int = _DEFAULT_MANAGED_READ_MAX_BYTES,
) -> str | None:
    """Read one bounded plugin-managed text file without following links."""

    payload = read_managed_bytes(path, max_bytes=max_bytes)
    return None if payload is None else payload.decode(encoding)


def list_managed_directory_names(path: str | Path) -> list[str]:
    """List names in one real managed directory without following links.

    A missing directory returns an empty list. Linked parents, directory links,
    junctions, and non-directory entries fail closed.
    """

    target = Path(path)
    identity = _managed_directory_identity(target)
    if identity is None:
        return []
    if _IS_WINDOWS:
        with os.scandir(target) as entries:
            names = [entry.name for entry in entries]
        if _managed_directory_identity(target) != identity:
            raise UnsafeManagedPathError("Managed directory changed while listing")
        return sorted(names)

    directory_fd = _open_managed_directory(target, expected_identity=identity)
    try:
        return sorted(str(name) for name in os.listdir(directory_fd))
    finally:
        os.close(directory_fd)


def _open_managed_directory(
    parent: Path,
    *,
    expected_identity: tuple[int, int],
) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = os.open(parent, flags)
    except OSError as exc:
        raise UnsafeManagedPathError(
            "Managed file parent could not be opened safely"
        ) from exc
    directory_stat = os.fstat(directory_fd)
    directory_identity = (directory_stat.st_dev, directory_stat.st_ino)
    if (
        not stat.S_ISDIR(directory_stat.st_mode)
        or directory_identity != expected_identity
    ):
        os.close(directory_fd)
        raise UnsafeManagedPathError("Managed file parent must be a real directory")
    return directory_fd


def _atomic_write_managed_posix(path: Path, data: bytes) -> None:
    _, parent, parent_identity = _validate_managed_file_path(path)
    directory_fd = _open_managed_directory(
        parent,
        expected_identity=parent_identity,
    )
    temp_name = f".{path.name}.{secrets.token_hex(12)}.tmp"
    temp_fd: int | None = None
    try:
        try:
            target_stat = os.stat(
                path.name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            target_stat = None
        if (
            target_stat is not None
            and stat.S_ISDIR(target_stat.st_mode)
            and not path_is_link(path, path_stat=target_stat)
        ):
            raise UnsafeManagedPathError("Managed file target must not be a directory")

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        temp_fd = os.open(temp_name, flags, 0o600, dir_fd=directory_fd)
        with os.fdopen(temp_fd, "wb", closefd=True) as file:
            temp_fd = None
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(
            temp_name,
            path.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    except BaseException:
        if temp_fd is not None:
            os.close(temp_fd)
        try:
            os.unlink(temp_name, dir_fd=directory_fd)
        except OSError:
            pass
        raise
    finally:
        os.close(directory_fd)


def _atomic_write_managed_windows(path: Path, data: bytes) -> None:
    target, parent, parent_identity = _validate_managed_file_path(path)
    _validate_managed_target_type(target)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=parent,
    )
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        _, current_parent, current_identity = _validate_managed_file_path(target)
        if current_parent != parent or current_identity != parent_identity:
            raise UnsafeManagedPathError("Managed file parent changed during write")
        target_stat = _validate_managed_target_type(target)
        if target_stat is not None and stat.S_ISDIR(target_stat.st_mode):
            os.rmdir(target)
            _, current_parent, current_identity = _validate_managed_file_path(target)
            if current_parent != parent or current_identity != parent_identity:
                raise UnsafeManagedPathError("Managed file parent changed during write")
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_managed_bytes(path: str | Path, data: bytes) -> None:
    """Replace one plugin-managed file without following file or parent links.

    The parent directory must already exist and must not be a symbolic link or
    Windows junction. An existing target link is replaced as a link; its target
    is never opened or modified.
    """

    target = Path(path)
    if _IS_WINDOWS:
        _atomic_write_managed_windows(target, data)
        return
    _atomic_write_managed_posix(target, data)


def atomic_write_managed_text(
    path: str | Path,
    text: str,
    encoding: str = "utf-8",
) -> None:
    """Replace one plugin-managed text file without following links."""

    atomic_write_managed_bytes(path, text.encode(encoding))


def remove_managed_file(path: str | Path) -> bool:
    """Remove one plugin-managed non-directory entry without following it.

    Returns ``True`` when an entry was removed and ``False`` when it did not
    exist. Regular files, hard links, symbolic links, junctions, and special
    files are removed as directory entries without opening their targets. A
    real directory is rejected.
    """

    target_path = Path(path)
    try:
        os.lstat(target_path.parent)
    except FileNotFoundError:
        return False
    target, parent, parent_identity = _validate_managed_file_path(target_path)
    if _IS_WINDOWS:
        try:
            target_stat = os.lstat(target)
        except FileNotFoundError:
            return False
        target_is_link = path_is_link(target, path_stat=target_stat)
        if stat.S_ISDIR(target_stat.st_mode) and not target_is_link:
            raise UnsafeManagedPathError("Managed file target must not be a directory")
        if stat.S_ISDIR(target_stat.st_mode):
            os.rmdir(target)
        else:
            os.unlink(target)
        return True

    directory_fd = _open_managed_directory(
        parent,
        expected_identity=parent_identity,
    )
    try:
        try:
            target_stat = os.stat(
                target.name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False
        if stat.S_ISDIR(target_stat.st_mode):
            raise UnsafeManagedPathError("Managed file target must not be a directory")
        os.unlink(target.name, dir_fd=directory_fd)
        os.fsync(directory_fd)
        return True
    finally:
        os.close(directory_fd)


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    """Atomically replace the file at ``path`` with ``text``."""
    _atomic_write(Path(path), text.encode(encoding))


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """Atomically replace the file at ``path`` with ``data``."""
    _atomic_write(Path(path), data)


def append_jsonl_many(
    path: str | Path,
    records: Iterable[Mapping[str, Any]],
) -> None:
    """Append multiple JSON records as one rollback-safe locked write."""
    lines = [
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in records
    ]
    if not lines:
        return
    payload = "".join(lines).encode("utf-8")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a+b") as f:
        with file_lock(f):
            f.seek(0, os.SEEK_END)
            original_size = f.tell()
            try:
                written = f.write(payload)
                if written != len(payload):
                    raise OSError(
                        f"short JSONL write: expected {len(payload)} bytes, wrote {written}"
                    )
                f.flush()
                os.fsync(f.fileno())
            except Exception:
                try:
                    f.seek(original_size)
                    f.truncate()
                    f.flush()
                    os.fsync(f.fileno())
                except Exception as rollback_exc:
                    raise RuntimeError(
                        "JSONL append failed and the original file could not be restored"
                    ) from rollback_exc
                raise


def append_jsonl(path: str | Path, record: Mapping[str, Any]) -> None:
    """Append a JSON-encoded record as a single newline-terminated line."""
    append_jsonl_many(path, (record,))


__all__ = [
    "UnsafeManagedPathError",
    "atomic_write_text",
    "atomic_write_bytes",
    "atomic_write_managed_bytes",
    "atomic_write_managed_text",
    "append_jsonl",
    "append_jsonl_many",
    "file_lock",
    "list_managed_directory_names",
    "path_is_link",
    "read_managed_bytes",
    "read_managed_text",
    "remove_managed_file",
]
