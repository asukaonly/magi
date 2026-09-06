"""Private, atomic JSON persistence for the host connection registry."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import threading
from typing import Iterator

from ..utils.file_io import atomic_write_text
from ..utils.private_data import protect_private_data_tree

_LOCK = threading.RLock()


@contextmanager
def connection_file_lock(root: Path) -> Iterator[None]:
    """Serialize read-modify-write in this process and across host processes."""
    with _LOCK:
        protect_private_data_tree(root)
        descriptor = os.open(root / "state.lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(descriptor, "a+b") as handle:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_connection_json(path: Path, payload: str) -> None:
    """Commit a complete registry and flush the directory rename on Unix."""
    atomic_write_text(path, payload)
    if os.name != "nt":
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
