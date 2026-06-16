"""
Path utility helpers for builtin file tools.
"""
from __future__ import annotations

import fnmatch
import os
from typing import Iterable


DEFAULT_EXCLUDE_PATTERNS = (
    "node_modules",
    "dist",
    "build",
    ".git",
    ".venv",
    "__pycache__",
)


def expand_input_path(path: str | None, default: str = ".") -> str:
    """Expand user/env placeholders in a path string."""
    raw_path = default if path is None else str(path).strip()
    if not raw_path:
        raw_path = default
    return os.path.expandvars(os.path.expanduser(raw_path))


def resolve_path_from_workspace(
    path: str | None,
    *,
    workspace: str | None,
    default: str = ".",
) -> str:
    """Resolve a tool path relative to the active workspace when needed."""
    expanded_path = expand_input_path(path, default=default)
    if os.path.isabs(expanded_path):
        return os.path.normpath(expanded_path)

    expanded_workspace = expand_input_path(workspace, default=".")
    return os.path.normpath(os.path.join(expanded_workspace, expanded_path))


def path_within_root(path: str, root: str | None) -> bool:
    """Return True when path resolves to root or a child of root."""
    try:
        resolved_path = os.path.realpath(expand_input_path(path))
        resolved_root = os.path.realpath(expand_input_path(root, default="."))
        return os.path.commonpath([resolved_path, resolved_root]) == resolved_root
    except ValueError:
        return False


def has_hidden_path_component(path: str) -> bool:
    """Return True if any path segment is hidden (starts with a dot)."""
    normalized = path.replace("\\", "/")
    return any(part.startswith(".") for part in normalized.split("/") if part and part != ".")


def normalize_exclude_patterns(exclude: Iterable[str] | None) -> list[str]:
    """Normalize exclude patterns and drop empty values."""
    if exclude is None:
        return list(DEFAULT_EXCLUDE_PATTERNS)
    normalized: list[str] = []
    for item in exclude:
        value = str(item).strip()
        if value:
            normalized.append(value.replace("\\", "/").strip("/"))
    return normalized


def matches_exclude_path(path: str, exclude_patterns: Iterable[str]) -> bool:
    """Return True when the path matches any exclude pattern."""
    normalized_path = path.replace("\\", "/").lstrip("./")
    path_parts = [part for part in normalized_path.split("/") if part and part != "."]
    basename = path_parts[-1] if path_parts else normalized_path

    for raw_pattern in exclude_patterns:
        pattern = str(raw_pattern).strip()
        if not pattern:
            continue
        pattern = pattern.replace("\\", "/").strip("/")
        if not pattern:
            continue
        if pattern in path_parts:
            return True
        if normalized_path.startswith(pattern + "/"):
            return True
        if fnmatch.fnmatch(normalized_path, pattern):
            return True
        if fnmatch.fnmatch(basename, pattern):
            return True

    return False
