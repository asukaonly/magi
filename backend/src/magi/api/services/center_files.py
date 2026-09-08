"""Bounded filesystem browsing for explicit center-owner path selection."""
from __future__ import annotations

import asyncio
import heapq
import os
from pathlib import Path
from threading import BoundedSemaphore
from typing import Literal

from pydantic import BaseModel

_SLOTS = BoundedSemaphore(4)
_MAX_SCANNED_ENTRIES = 100_000


class CenterPathError(Exception):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class CenterFileEntry(BaseModel):
    name: str
    path: str
    kind: Literal["directory", "file"]


class CenterDirectory(BaseModel):
    path: str
    parent: str | None
    entries: list[CenterFileEntry]
    next_after: str | None
    selected_file: str | None


def _directory(value: str | None) -> Path:
    path = Path(value).expanduser() if value else Path.home()
    if not path.is_absolute() or "\0" in str(path):
        raise CenterPathError("invalid_center_path")
    path = path.resolve(strict=True)
    if not path.is_dir():
        raise CenterPathError("center_path_not_directory")
    return path


def _browse(value: str | None, directories_only: bool, after: str | None,
            prefix: str, show_hidden: bool, limit: int, resolve_file: bool = False) -> CenterDirectory:
    selected = None
    if value and resolve_file:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            raise CenterPathError("invalid_center_path")
        if candidate.is_file():
            selected = str(candidate.resolve(strict=True))
            value = str(candidate.parent)
    path = _directory(value)

    def candidates():
        with os.scandir(path) as iterator:
            for index, entry in enumerate(iterator):
                if index >= _MAX_SCANNED_ENTRIES:
                    raise CenterPathError("center_directory_too_large", 413)
                if (after is not None and entry.name <= after) or not entry.name.startswith(prefix):
                    continue
                if not show_hidden and entry.name.startswith("."):
                    continue
                try:
                    directory = entry.is_dir()
                    if not directory and (directories_only or not entry.is_file()):
                        continue
                except FileNotFoundError:
                    continue
                yield CenterFileEntry(name=entry.name, path=str(path / entry.name),
                                      kind="directory" if directory else "file")

    entries = heapq.nsmallest(limit + 1, candidates(), key=lambda item: item.name)
    return CenterDirectory(path=str(path), parent=str(path.parent) if path.parent != path else None,
                           selected_file=selected, entries=entries[:limit], next_after=entries[limit - 1].name if len(entries) > limit else None)


def _guarded(operation):
    # A timed-out filesystem call retains its slot until its actual thread exits.
    if not _SLOTS.acquire(blocking=False):
        raise CenterPathError("center_files_busy", 503)
    try:
        return operation()
    except FileNotFoundError as error:
        raise CenterPathError("center_path_not_found", 404) from error
    except PermissionError as error:
        raise CenterPathError("center_path_denied", 403) from error
    except OSError as error:
        raise CenterPathError("center_path_unavailable", 400) from error
    finally:
        _SLOTS.release()


async def browse_center_directory(path: str | None, *, directories_only: bool = False,
                                  after: str | None = None, prefix: str = "",
                                  show_hidden: bool = False, limit: int = 200, resolve_file: bool = False) -> CenterDirectory:
    """List one bounded page of paths on the center, never on the client."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(
            _guarded, lambda: _browse(path, directories_only, after, prefix, show_hidden, limit, resolve_file)), timeout=5)
    except TimeoutError as error:
        raise CenterPathError("center_files_timeout", 503) from error


async def create_center_directory(parent: str, name: str) -> CenterDirectory:
    """Create one explicitly named child directory without shell expansion."""
    if name in {"", ".", ".."} or any(char in name for char in ("/", "\\", "\0")):
        raise CenterPathError("invalid_center_directory_name")

    def create() -> CenterDirectory:
        target = _directory(parent) / name
        if target.is_symlink():
            raise CenterPathError("invalid_center_directory_name")
        target.mkdir(exist_ok=True)
        return _browse(str(target), False, None, "", False, 200)

    try:
        return await asyncio.wait_for(asyncio.to_thread(_guarded, create), timeout=5)
    except TimeoutError as error:
        raise CenterPathError("center_files_timeout", 503) from error
