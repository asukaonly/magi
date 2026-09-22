"""Exclusive worker ownership and supervising-process lifetime checks."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import stat
import sys
import threading
from typing import IO

from .private_data import protect_private_data_tree, protect_private_directory

_lease_lock = threading.Lock()
_active_lease: int | None = None
_active_root: Path | None = None


def owns_audited_root(root: Path) -> bool:
    """Only the live worker lease may reuse its completed tree audit."""
    with _lease_lock:
        return _active_lease is not None and _active_root == Path(os.path.abspath(root))


def duplicate_worker_lease() -> int | None:
    """Retain the Unix runtime lease until an owned plugin family exits."""
    with _lease_lock:
        return os.dup(_active_lease) if os.name != "nt" and _active_lease is not None else None


class WorkerInstance:
    """Hold the data-root lease until runtime and plugin shutdown finish."""

    def __init__(self, root: Path, parent_pid: int | None = None) -> None:
        self._shutdown_timeout = float(os.environ.pop("MAGI_WORKER_SHUTDOWN_TIMEOUT_SECS", "30"))
        if not 1 <= self._shutdown_timeout <= 60:
            raise ValueError("Worker shutdown timeout must be between 1 and 60 seconds")
        self._root = root
        self._parent_pid = parent_pid
        self._file: IO[bytes] | None = None
        self._stop = threading.Event()
        self._monitor: threading.Thread | None = None

    def __enter__(self) -> WorkerInstance:
        global _active_lease, _active_root
        protect_private_directory(self._root)
        runtime_dir = self._root / "runtime"
        protect_private_directory(runtime_dir)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(runtime_dir / "worker.lock", flags, 0o600)
        self._file = os.fdopen(fd, "r+b")
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise OSError("Worker lease must be a private regular file")
            if os.name != "nt" and metadata.st_uid != os.geteuid():
                raise OSError("Worker lease belongs to another account")
            if os.name == "nt":
                import msvcrt

                if os.fstat(fd).st_size == 0:
                    self._file.write(b"0")
                    self._file.flush()
                self._file.seek(0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._file.close()
            self._file = None
            raise RuntimeError("A Python runtime already owns this Magi data directory") from error
        try:
            protect_private_data_tree(self._root)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        if self._parent_pid is not None:
            if self._parent_pid <= 0 or os.getppid() != self._parent_pid:
                self.__exit__(None, None, None)
                raise RuntimeError("The supervising process is no longer the worker parent")
            self._monitor = threading.Thread(target=self._watch_owner, name="magi-parent-monitor", daemon=True)
            self._monitor.start()
        with _lease_lock:
            _active_lease = fd
            _active_root = Path(os.path.abspath(self._root))
        return self

    def __exit__(self, *_exc: object) -> None:
        global _active_lease, _active_root
        self._stop.set()
        if self._monitor is not None:
            self._monitor.join(timeout=1)
        if self._file is not None:
            with _lease_lock:
                if _active_lease == self._file.fileno():
                    _active_lease = None
                    _active_root = None
                self._file.close()
            self._file = None

    def _watch_owner(self) -> None:
        # Only the supervisor owns this inherited pipe. EOF also covers SIGKILL.
        try:
            os.read(sys.stdin.fileno(), 1)
        except OSError:
            pass
        if not self._stop.is_set():
            os.kill(os.getpid(), signal.SIGTERM)
            if not self._stop.wait(self._shutdown_timeout):
                os._exit(70)
