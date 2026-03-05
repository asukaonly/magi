"""
Path utility helpers for builtin file tools.
"""
from __future__ import annotations

import os


def expand_input_path(path: str | None, default: str = ".") -> str:
    """Expand user/env placeholders in a path string."""
    raw_path = default if path is None else str(path).strip()
    if not raw_path:
        raw_path = default
    return os.path.expandvars(os.path.expanduser(raw_path))


def has_hidden_path_component(path: str) -> bool:
    """Return True if any path segment is hidden (starts with a dot)."""
    normalized = path.replace("\\", "/")
    return any(part.startswith(".") for part in normalized.split("/") if part and part != ".")
