"""Erase diagnostic log history at the destructive product-clear boundary."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import stat
import sys
from typing import Iterable, Iterator


@dataclass(frozen=True)
class DiagnosticLogClearResult:
    """Summary of one best-effort diagnostic log clear."""

    cleared_entries: int
    failed_entries: int


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_within(path: Path, root: Path) -> bool:
    try:
        _absolute_path(path).relative_to(_absolute_path(root))
    except ValueError:
        return False
    return True


def _configured_extra_log_paths() -> tuple[Path, ...]:
    configured = os.environ.get("MAGI_BACKEND_LOG_FILE", "").strip()
    if not configured:
        return ()
    return (Path(configured),)


def _is_link_or_reparse(path_stat: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    file_attributes = getattr(path_stat, "st_file_attributes", 0)
    return stat.S_ISLNK(path_stat.st_mode) or bool(file_attributes & reparse_flag)


def _file_identity(path_stat: os.stat_result) -> tuple[int, int]:
    return (path_stat.st_dev, path_stat.st_ino)


def _safe_directory_identity(path: Path) -> tuple[int, int] | None:
    try:
        path_stat = os.lstat(path)
    except OSError:
        return None
    if _is_link_or_reparse(path_stat) or not stat.S_ISDIR(path_stat.st_mode):
        return None
    return _file_identity(path_stat)


def _directory_identity_matches(path: Path, expected: tuple[int, int]) -> bool:
    return _safe_directory_identity(path) == expected


def _iter_log_handlers() -> Iterator[logging.Handler]:
    seen: set[int] = set()
    loggers: list[logging.Logger] = [logging.getLogger()]
    loggers.extend(
        logger
        for logger in logging.Logger.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)
    )
    for logger in loggers:
        for handler in logger.handlers:
            if id(handler) in seen:
                continue
            seen.add(id(handler))
            yield handler


def _handler_targets_path(
    handler: logging.Handler,
    *,
    log_dirs: tuple[Path, ...],
    extra_log_paths: tuple[Path, ...],
) -> bool:
    if isinstance(handler, logging.StreamHandler) and not isinstance(
        handler,
        logging.FileHandler,
    ):
        stream = handler.stream
        if stream is sys.stdout or stream is sys.stderr:
            return True
        try:
            return stream is not None and stream.fileno() in {1, 2}
        except (AttributeError, OSError, ValueError):
            return False
    if not isinstance(handler, logging.FileHandler):
        return False
    base_filename = getattr(handler, "baseFilename", None)
    if not base_filename:
        return False
    handler_path = _absolute_path(Path(base_filename))
    if any(_is_within(handler_path, logs_dir) for logs_dir in log_dirs):
        return True
    return any(handler_path == _absolute_path(path) for path in extra_log_paths)


@contextmanager
def _locked_handlers(
    handlers: Iterable[logging.Handler],
) -> Iterator[tuple[logging.Handler, ...]]:
    locked = tuple(
        sorted(
            handlers,
            key=lambda handler: str(getattr(handler, "baseFilename", id(handler))),
        )
    )
    for handler in locked:
        handler.acquire()
    try:
        yield locked
    finally:
        for handler in reversed(locked):
            handler.release()


def _clear_open_handler(handler: logging.FileHandler) -> bool:
    stream = handler.stream
    if stream is None:
        return True
    handler_path = _absolute_path(Path(handler.baseFilename))
    parent = handler_path.parent
    parent_identity = _safe_directory_identity(parent)
    if parent_identity is None:
        return False
    try:
        path_stat = os.lstat(handler_path)
        opened_stat = os.fstat(stream.fileno())
        if (
            _is_link_or_reparse(path_stat)
            or not stat.S_ISREG(path_stat.st_mode)
            or not stat.S_ISREG(opened_stat.st_mode)
            or path_stat.st_nlink != 1
            or opened_stat.st_nlink != 1
        ):
            return False
        if _file_identity(path_stat) != _file_identity(opened_stat):
            return False
        if not _directory_identity_matches(parent, parent_identity):
            return False
        stream.flush()
        os.ftruncate(stream.fileno(), 0)
        os.fsync(stream.fileno())
    except (OSError, ValueError):
        return False
    return True


def _flush_stream_handler(handler: logging.StreamHandler) -> bool:
    try:
        handler.flush()
    except (OSError, ValueError):
        return False
    return True


def _is_desktop_owned_log(path: Path) -> bool:
    name = path.name
    return name == "desktop.log" or (
        name.startswith("desktop_") and name.endswith(".log")
    )


def _walk_log_entries(logs_dir: Path) -> tuple[list[Path], int]:
    try:
        root_stat = os.lstat(logs_dir)
    except FileNotFoundError:
        return [], 0
    except OSError:
        return [], 1
    if _is_link_or_reparse(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        return [], 1

    entries: list[Path] = []
    failures = 0
    try:
        children = list(os.scandir(logs_dir))
    except OSError:
        return [], 1
    for child in children:
        path = Path(child.path)
        if _is_desktop_owned_log(path):
            continue
        try:
            if child.is_dir(follow_symlinks=False):
                failures += 1
            else:
                entries.append(path)
        except OSError:
            failures += 1
    return entries, failures


def _clear_path(
    path: Path,
    *,
    expected_parent_identity: tuple[int, int] | None,
) -> bool:
    path = _absolute_path(path)
    parent = path.parent
    parent_identity = expected_parent_identity
    if parent_identity is None:
        return False
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False

    if (
        _is_link_or_reparse(path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
        or path_stat.st_nlink != 1
    ):
        return False

    flags = os.O_WRONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    try:
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode) or opened_stat.st_nlink != 1:
            return False
        if _file_identity(path_stat) != _file_identity(opened_stat):
            return False
        if not _directory_identity_matches(parent, parent_identity):
            return False
        os.ftruncate(descriptor, 0)
        os.fsync(descriptor)
    except OSError:
        return False
    finally:
        os.close(descriptor)
    return True


def _clear_diagnostic_log_history_sync(
    *,
    logs_dir: Path,
    extra_log_paths: tuple[Path, ...],
    handlers: Iterable[logging.Handler] | None,
) -> DiagnosticLogClearResult:
    normalized_log_dirs = (_absolute_path(logs_dir),)
    normalized_extra_paths = tuple(_absolute_path(path) for path in extra_log_paths)
    selected_handlers = tuple(
        handler
        for handler in (handlers if handlers is not None else _iter_log_handlers())
        if _handler_targets_path(
            handler,
            log_dirs=normalized_log_dirs,
            extra_log_paths=normalized_extra_paths,
        )
    )

    failed_entries = 0
    cleared_paths: set[Path] = set()
    with _locked_handlers(selected_handlers) as locked_handlers:
        for handler in locked_handlers:
            if isinstance(handler, logging.FileHandler):
                handler_path = _absolute_path(Path(handler.baseFilename))
                if _clear_open_handler(handler):
                    cleared_paths.add(handler_path)
                else:
                    failed_entries += 1
            elif isinstance(handler, logging.StreamHandler) and not _flush_stream_handler(
                handler
            ):
                failed_entries += 1

        candidates: dict[Path, tuple[int, int] | None] = {}
        for log_dir in normalized_log_dirs:
            directory_identity = _safe_directory_identity(log_dir)
            directory_entries, walk_failures = _walk_log_entries(log_dir)
            failed_entries += walk_failures
            for entry in directory_entries:
                candidates[_absolute_path(entry)] = directory_identity
        for extra_path in normalized_extra_paths:
            absolute_extra_path = _absolute_path(extra_path)
            candidates[absolute_extra_path] = _safe_directory_identity(
                absolute_extra_path.parent
            )
        for path, parent_identity in sorted(candidates.items(), key=lambda item: str(item[0])):
            if _clear_path(path, expected_parent_identity=parent_identity):
                cleared_paths.add(path)
            else:
                failed_entries += 1

    return DiagnosticLogClearResult(
        cleared_entries=len(cleared_paths),
        failed_entries=failed_entries,
    )


async def clear_diagnostic_log_history(
    *,
    logs_dir: Path | None = None,
    extra_log_paths: Iterable[Path] | None = None,
    handlers: Iterable[logging.Handler] | None = None,
) -> DiagnosticLogClearResult:
    """Erase past log contents while keeping active append handles usable."""
    if logs_dir is None:
        from ..utils.runtime import get_runtime_paths

        logs_dir = get_runtime_paths().logs_dir
    resolved_extra_paths = tuple(
        extra_log_paths
        if extra_log_paths is not None
        else _configured_extra_log_paths()
    )
    return await asyncio.to_thread(
        _clear_diagnostic_log_history_sync,
        logs_dir=logs_dir,
        extra_log_paths=resolved_extra_paths,
        handlers=handlers,
    )


__all__ = [
    "DiagnosticLogClearResult",
    "clear_diagnostic_log_history",
]
