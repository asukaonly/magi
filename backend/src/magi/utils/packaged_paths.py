"""Helpers for resolving packaged resource roots in dev and frozen builds."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def get_repo_root() -> Path:
    """Return the repository root or PyInstaller extraction root."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parents[4]


@lru_cache(maxsize=1)
def get_backend_root() -> Path:
    """Return the backend root or PyInstaller extraction root."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parents[3]
