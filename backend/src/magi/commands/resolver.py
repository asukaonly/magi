"""Resolve which tools the user may invoke directly via the `/`-picker.

A tool is user-invocable when **any** of the following hold:

1. Its ``ToolSchema.metadata`` contains ``user_invocable: true``.
2. Its name appears in the optional whitelist
   ``~/.magi/config/user_invocable_tools.toml`` under ``allow = [...]``.

Resolution is best-effort: a missing/unreadable whitelist file is treated as
empty, not an error. The whitelist is cached on first read and reloaded
when its mtime changes — operators can edit the file without restarting.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from threading import Lock

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - mirrors loader.py
    import tomli as tomllib

from ..tools.registry import ToolRegistry
from ..utils.runtime import get_runtime_paths

logger = logging.getLogger(__name__)


class UserInvocableResolver:
    """Singleton-like resolver — keeps the whitelist mtime-cached."""

    def __init__(self, whitelist_path: Path | None = None) -> None:
        self._lock = Lock()
        self._whitelist_path = whitelist_path
        self._cached_mtime: float | None = None
        self._cached_allow: set[str] = set()

    def _resolve_whitelist_path(self) -> Path:
        if self._whitelist_path is not None:
            return self._whitelist_path
        return get_runtime_paths().config_dir / "user_invocable_tools.toml"

    def _load_whitelist(self) -> set[str]:
        path = self._resolve_whitelist_path()
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            with self._lock:
                self._cached_allow = set()
                self._cached_mtime = None
            return set()
        with self._lock:
            if self._cached_mtime == mtime:
                return self._cached_allow
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            logger.warning("Could not load %s: %s", path, exc)
            return set()
        raw = data.get("allow", [])
        allow = {str(item).strip() for item in raw if isinstance(item, str) and item.strip()}
        with self._lock:
            self._cached_allow = allow
            self._cached_mtime = mtime
        return allow

    def is_user_invocable(self, registry: ToolRegistry, tool_name: str) -> bool:
        if not tool_name:
            return False
        if tool_name in self._load_whitelist():
            return True
        tool = registry.get_tool(tool_name)
        if tool is None:
            return False
        schema = tool.get_schema()
        metadata = getattr(schema, "metadata", None) or {}
        return bool(metadata.get("user_invocable"))

    def list_user_invocable(self, registry: ToolRegistry) -> list[str]:
        whitelist = self._load_whitelist()
        out: list[str] = []
        for name in registry.list_tools():
            tool = registry.get_tool(name)
            if tool is None:
                continue
            schema = tool.get_schema()
            metadata = getattr(schema, "metadata", None) or {}
            if name in whitelist or metadata.get("user_invocable"):
                out.append(name)
        return sorted(out)


_default_resolver: UserInvocableResolver | None = None


def get_default_resolver() -> UserInvocableResolver:
    global _default_resolver
    if _default_resolver is None:
        _default_resolver = UserInvocableResolver()
    return _default_resolver


def reset_default_resolver() -> None:
    """Reset for tests."""
    global _default_resolver
    _default_resolver = None
