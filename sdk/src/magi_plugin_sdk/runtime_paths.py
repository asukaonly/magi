"""Resolve process-wide host storage without touching the filesystem."""
from __future__ import annotations

import os
from pathlib import Path


def get_magi_home() -> Path:
    """Return the dedicated application data root from the launch environment."""
    override = os.environ.get("MAGI_HOME")
    if override is None:
        return Path.home() / ".magi"
    path = Path(override)
    if (
        not override
        or not path.is_absolute()
        or path == Path(path.anchor)
        or path == Path.home()
        or ".." in path.parts
    ):
        raise ValueError("MAGI_HOME must name a dedicated absolute data directory")
    return path
