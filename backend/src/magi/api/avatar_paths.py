"""Helpers for serving personality avatars from static paths."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

BUILTIN_AVATAR_PREFIX = "/static/avatars"
USER_AVATAR_PREFIX = "/static/user-avatars"


def user_avatar_dir() -> Path:
    return Path.home() / ".magi" / "personalities" / "avatar"


def builtin_avatar_dir() -> Path:
    current_file = Path(__file__).resolve()
    candidates = [
        # PyInstaller onedir layout: sidecar-dist/_internal/personalities/avatar.
        current_file.parents[2] / "personalities" / "avatar",
        # Source-tree layout: backend/personalities/avatar.
        current_file.parents[3] / "personalities" / "avatar",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[-1]


def _is_inline_avatar(value: str) -> bool:
    return len(value) <= 4 and any(ord(ch) > 127 for ch in value)


def resolve_avatar_public_url(avatar: str) -> str:
    """Return a public static URL for a stored avatar value."""
    value = (avatar or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://", "/", "data:")):
        return value
    if _is_inline_avatar(value):
        return value

    safe_name = Path(value).name
    if safe_name != value or not safe_name:
        return ""

    if (user_avatar_dir() / safe_name).is_file():
        return f"{USER_AVATAR_PREFIX}/{quote(safe_name)}"
    if (builtin_avatar_dir() / safe_name).is_file():
        return f"{BUILTIN_AVATAR_PREFIX}/{quote(safe_name)}"
    return ""
