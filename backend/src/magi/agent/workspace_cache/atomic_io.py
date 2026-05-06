"""Atomic file write and JSONL append helpers."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .locking import file_lock


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


def append_jsonl(path: str | Path, record: Mapping[str, Any]) -> None:
    """Append a JSON-encoded record as a single newline-terminated line."""
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "ab") as f:
        with file_lock(f):
            f.write(line.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
