"""Private filesystem primitives for crash-safe memory restore transactions."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import stat
from typing import BinaryIO

from .errors import MemoryPortabilityError

COPY_CHUNK_BYTES = 1024 * 1024
SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def create_private_directory(path: Path) -> Path:
    """Create one owner-only real directory and return its absolute path."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    try:
        absolute.mkdir(mode=0o700, parents=True, exist_ok=False)
        if os.name != "nt":
            absolute.chmod(0o700)
    except OSError as exc:
        raise MemoryPortabilityError(
            "restore_staging_failed",
            "Private restore staging could not be created.",
            status_code=500,
        ) from exc
    return absolute


def require_real_directory(path: Path, *, label: str) -> Path:
    """Require an existing directory without following a final link."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    try:
        details = absolute.lstat()
    except OSError as exc:
        raise MemoryPortabilityError(
            "restore_target_unavailable",
            f"The {label} is unavailable.",
            status_code=500,
        ) from exc
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        raise MemoryPortabilityError(
            "restore_target_invalid",
            f"The {label} must be a real directory.",
            status_code=500,
        )
    return absolute


def require_regular_single_link(path: Path, *, label: str) -> os.stat_result:
    """Require one regular, singly linked file without following a link."""

    try:
        details = Path(path).lstat()
    except OSError as exc:
        raise MemoryPortabilityError(
            "restore_file_unavailable",
            f"A required {label} is unavailable.",
            status_code=500,
        ) from exc
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise MemoryPortabilityError(
            "restore_file_invalid",
            f"A required {label} is not a private regular file.",
            status_code=500,
        )
    return details


def open_private_exclusive(path: Path) -> BinaryIO:
    """Open one new owner-only regular file without following a final link."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(Path(path), flags, 0o600)
    return os.fdopen(descriptor, "wb")


def fingerprint_file(path: Path) -> tuple[int, str]:
    """Hash one stable private regular file and return ``(size, sha256)``."""

    before = require_regular_single_link(path, label="restore file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(Path(path), flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if opened.st_dev != before.st_dev or opened.st_ino != before.st_ino:
                raise OSError("file identity changed")
            digest = hashlib.sha256()
            size = 0
            while chunk := handle.read(COPY_CHUNK_BYTES):
                size += len(chunk)
                digest.update(chunk)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise MemoryPortabilityError(
            "restore_file_changed",
            "A restore file changed while it was being verified.",
        ) from exc
    if (
        size != before.st_size
        or after.st_dev != before.st_dev
        or after.st_ino != before.st_ino
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
    ):
        raise MemoryPortabilityError(
            "restore_file_changed",
            "A restore file changed while it was being verified.",
        )
    return size, digest.hexdigest()


def copy_private_file(
    source: Path,
    destination: Path,
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> tuple[int, str]:
    """Copy one stable regular file to a new private path and verify it."""

    source = Path(source)
    destination = Path(destination)
    before = require_regular_single_link(source, label="restore source file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    digest = hashlib.sha256()
    copied = 0
    try:
        descriptor = os.open(source, flags)
        with (
            os.fdopen(descriptor, "rb") as input_handle,
            open_private_exclusive(destination) as output_handle,
        ):
            opened = os.fstat(input_handle.fileno())
            if opened.st_dev != before.st_dev or opened.st_ino != before.st_ino:
                raise OSError("file identity changed")
            while chunk := input_handle.read(COPY_CHUNK_BYTES):
                copied += len(chunk)
                if expected_size is not None and copied > expected_size:
                    raise MemoryPortabilityError(
                        "candidate_changed",
                        "The inspected restore candidate changed after validation.",
                    )
                digest.update(chunk)
                output_handle.write(chunk)
            output_handle.flush()
            os.fsync(output_handle.fileno())
            after = os.fstat(input_handle.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    actual_sha256 = digest.hexdigest()
    if (
        copied != before.st_size
        or after.st_dev != before.st_dev
        or after.st_ino != before.st_ino
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or (expected_size is not None and copied != expected_size)
        or (expected_sha256 is not None and actual_sha256 != expected_sha256)
    ):
        destination.unlink(missing_ok=True)
        raise MemoryPortabilityError(
            "candidate_changed",
            "The inspected restore candidate changed after validation.",
        )
    if os.name != "nt":
        destination.chmod(0o600)
    return copied, actual_sha256


def sqlite_backup_private(source: Path, destination: Path) -> tuple[int, str]:
    """Create a complete private SQLite backup that includes committed WAL state."""

    source = Path(source)
    destination = Path(destination)
    require_regular_single_link(source, label="live memory database")
    try:
        with open_private_exclusive(destination):
            pass
        source_uri = source.resolve(strict=True).as_uri() + "?mode=ro"
        with sqlite3.connect(source_uri, uri=True, timeout=30.0) as source_db:
            with sqlite3.connect(destination, timeout=30.0) as destination_db:
                source_db.backup(destination_db, pages=1024)
                destination_db.commit()
                integrity_rows = destination_db.execute("PRAGMA integrity_check").fetchall()
                foreign_key_rows = destination_db.execute("PRAGMA foreign_key_check").fetchall()
                if integrity_rows != [("ok",)] or foreign_key_rows:
                    raise sqlite3.DatabaseError("database validation failed")
        if os.name != "nt":
            destination.chmod(0o600)
        fsync_file(destination)
        return fingerprint_file(destination)
    except MemoryPortabilityError:
        destination.unlink(missing_ok=True)
        raise
    except (OSError, sqlite3.DatabaseError) as exc:
        destination.unlink(missing_ok=True)
        raise MemoryPortabilityError(
            "restore_rollback_snapshot_failed",
            "The current memory database could not be snapshotted for rollback.",
            status_code=500,
        ) from exc


def iter_private_tree_files(root: Path) -> Iterator[tuple[Path, Path]]:
    """Yield stable regular files below a real directory without following links."""

    root = require_real_directory(root, label="restore file tree")
    stack: list[tuple[Path, Path]] = [(root, Path())]
    while stack:
        directory, relative_directory = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name, reverse=True)
        except OSError as exc:
            raise MemoryPortabilityError(
                "restore_file_unavailable",
                "A restore file tree could not be enumerated.",
                status_code=500,
            ) from exc
        for entry in entries:
            relative_path = relative_directory / entry.name
            try:
                details = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise MemoryPortabilityError(
                    "restore_file_unavailable",
                    "A restore file tree changed while it was being inspected.",
                    status_code=500,
                ) from exc
            path = Path(entry.path)
            if stat.S_ISLNK(details.st_mode):
                raise MemoryPortabilityError(
                    "restore_file_invalid",
                    "A restore file tree contains a symbolic link.",
                    status_code=500,
                )
            if stat.S_ISDIR(details.st_mode):
                stack.append((path, relative_path))
                continue
            if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
                raise MemoryPortabilityError(
                    "restore_file_invalid",
                    "A restore file tree contains an unsupported file.",
                    status_code=500,
                )
            yield path, relative_path


def tree_fingerprint(
    root: Path,
    *,
    path_validator: Callable[[str], bool] | None = None,
) -> tuple[int, int, str]:
    """Return ``(file_count, total_bytes, digest)`` for a private file tree."""

    records: list[tuple[str, int, str]] = []
    for source, relative_path in iter_private_tree_files(root):
        relative = relative_path.as_posix()
        if path_validator is not None and not path_validator(relative):
            raise MemoryPortabilityError(
                "restore_file_invalid",
                "A restore file tree contains an unexpected path.",
                status_code=500,
            )
        size, sha256 = fingerprint_file(source)
        records.append((relative, size, sha256))
    records.sort(key=lambda item: item[0])
    digest = hashlib.sha256()
    total_bytes = 0
    for relative, size, sha256 in records:
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(sha256))
        total_bytes += size
    return len(records), total_bytes, digest.hexdigest()


def copy_private_tree(
    source: Path,
    destination: Path,
    *,
    path_validator: Callable[[str], bool] | None = None,
) -> tuple[int, int, str]:
    """Copy a private regular-file tree without links into a new owner-only tree."""

    destination = create_private_directory(destination)
    try:
        for source_file, relative_path in iter_private_tree_files(source):
            relative = relative_path.as_posix()
            if path_validator is not None and not path_validator(relative):
                raise MemoryPortabilityError(
                    "restore_file_invalid",
                    "A restore file tree contains an unexpected path.",
                    status_code=500,
                )
            destination_file = destination.joinpath(*relative_path.parts)
            destination_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name != "nt":
                destination_file.parent.chmod(0o700)
            copy_private_file(source_file, destination_file)
        fsync_tree(destination)
        return tree_fingerprint(destination, path_validator=path_validator)
    except BaseException:
        remove_owned_path(destination)
        raise


def fsync_file(path: Path) -> None:
    """Synchronize one regular file to stable storage."""

    descriptor = os.open(Path(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_directory(path: Path) -> None:
    """Synchronize directory entry changes where the platform supports it."""

    if os.name == "nt":
        return
    descriptor = os.open(Path(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_tree(root: Path) -> None:
    """Synchronize every file and directory in a private tree, children first."""

    directories = {Path(root)}
    for file_path, relative_path in iter_private_tree_files(root):
        fsync_file(file_path)
        current = Path(root).joinpath(*relative_path.parts).parent
        while current != Path(root).parent:
            directories.add(current)
            if current == Path(root):
                break
            current = current.parent
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        fsync_directory(directory)


def remove_owned_path(path: Path) -> None:
    """Remove one exact transaction-owned path without following a link."""

    path = Path(path)
    try:
        details = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(details.st_mode):
        shutil.rmtree(path)
    else:
        path.unlink()
    fsync_directory(path.parent)


def remove_sqlite_family(path: Path) -> None:
    """Remove one SQLite database path and its owned sidecars without following links."""

    for candidate in (Path(path), *(Path(f"{path}{suffix}") for suffix in SQLITE_SIDECAR_SUFFIXES)):
        try:
            details = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(details.st_mode):
            raise MemoryPortabilityError(
                "restore_target_invalid",
                "A SQLite restore target conflicts with a directory.",
                status_code=500,
            )
        candidate.unlink()
    fsync_directory(Path(path).parent)


def ensure_free_space(requirements: Sequence[tuple[Path, int]]) -> None:
    """Require aggregate free space per filesystem before creating restore artifacts."""

    by_device: dict[int, tuple[Path, int]] = {}
    for raw_directory, raw_bytes in requirements:
        directory = require_real_directory(raw_directory, label="restore filesystem")
        try:
            device = int(directory.stat().st_dev)
        except OSError as exc:
            raise MemoryPortabilityError(
                "free_space_unknown",
                "Available restore space could not be checked.",
                status_code=500,
            ) from exc
        representative, current = by_device.get(device, (directory, 0))
        by_device[device] = (representative, current + max(0, int(raw_bytes)))

    for directory, required_bytes in by_device.values():
        try:
            free_bytes = shutil.disk_usage(directory).free
        except OSError as exc:
            raise MemoryPortabilityError(
                "free_space_unknown",
                "Available restore space could not be checked.",
                status_code=500,
            ) from exc
        if free_bytes < required_bytes:
            raise MemoryPortabilityError(
                "insufficient_space",
                "There is not enough free space to stage and roll back this restore.",
            )


__all__ = [
    "COPY_CHUNK_BYTES",
    "SQLITE_SIDECAR_SUFFIXES",
    "copy_private_file",
    "copy_private_tree",
    "create_private_directory",
    "ensure_free_space",
    "fingerprint_file",
    "fsync_directory",
    "fsync_file",
    "fsync_tree",
    "iter_private_tree_files",
    "open_private_exclusive",
    "remove_owned_path",
    "remove_sqlite_family",
    "require_real_directory",
    "require_regular_single_link",
    "sqlite_backup_private",
    "tree_fingerprint",
]
