"""Atomic file IO + cross-platform exclusive file lock.

Canonical home for pure file-IO helpers shared by the host and plugins.
Plugins import from here; the host re-exports from
magi.agent.workspace_cache.{atomic_io,locking} for back-compat.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, Iterable, Iterator, Mapping

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


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
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
    "atomic_write_text",
    "atomic_write_bytes",
    "append_jsonl",
    "append_jsonl_many",
    "file_lock",
]
