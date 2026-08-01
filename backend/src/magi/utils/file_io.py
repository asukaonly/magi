"""Atomic file write utilities."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_temp_prefix(path: Path) -> str:
    """Return the target-owned prefix used for atomic write temp files."""
    target_name = Path(path).name
    return f".{len(target_name)}-{target_name}.atomic-"


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write *content* to *path* atomically via temp-file + rename.

    The parent directory is created if it does not exist.  On the same
    filesystem ``os.replace`` is an atomic operation, so readers will
    never observe a half-written file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=atomic_write_temp_prefix(path),
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # Clean up the temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
