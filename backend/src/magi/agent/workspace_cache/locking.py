"""Cross-platform exclusive file lock context manager.

Lifted from the in-tree pattern at ``tools/builtin/file_edit_tool.py``.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import IO, Iterator

_IS_WINDOWS = sys.platform == "win32"

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
