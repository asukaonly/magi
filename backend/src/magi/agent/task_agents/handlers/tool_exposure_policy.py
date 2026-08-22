"""Cache-friendly tool exposure policy for function-calling turns."""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field


_WRITE_TOOL_NAMES = {
    "agent",
    "bash",
    "powershell",
    "file_edit",
    "file_write",
    "file_rollback",
    "batch_create",
    "detach_to_background",
    "schedule",
    "todo_write",
}
_WRITE_TOOL_MARKERS = (
    "write",
    "edit",
    "delete",
    "remove",
    "create",
    "update",
    "patch",
    "rollback",
    "commit",
    "push",
    "send",
    "execute",
    "shell",
    "bash",
    "powershell",
)
_NON_REUSABLE_EXTRA_TOOLS = {"agent"}


@dataclass(slots=True, frozen=True)
class _CachedToolExposure:
    tools: tuple[str, ...]
    updated_at: float


def _normalize_tools(
    tools: Sequence[str],
    *,
    registered_tools: Collection[str] | None,
) -> list[str]:
    registered = set(registered_tools) if registered_tools else None
    normalized: list[str] = []
    for raw_name in tools:
        name = str(raw_name or "").strip()
        if not name or name in normalized:
            continue
        if registered is not None and name not in registered:
            continue
        normalized.append(name)
    return normalized


def _looks_write_capable(tool_name: str) -> bool:
    normalized = tool_name.replace("-", "_").lower()
    if normalized in _WRITE_TOOL_NAMES:
        return True
    return any(marker in normalized for marker in _WRITE_TOOL_MARKERS)


@dataclass(slots=True)
class ToolExposurePolicy:
    """Reuse recent tool supersets when that improves provider prompt caching."""

    ttl_seconds: float = 600.0
    max_reused_tools: int = 8
    clock: Callable[[], float] = time.monotonic
    _cache: dict[str, _CachedToolExposure] = field(default_factory=dict)

    def resolve(
        self,
        *,
        session_key: str,
        requested_tools: Sequence[str],
        registered_tools: Collection[str] | None,
        may_write: bool,
    ) -> list[str]:
        current = _normalize_tools(
            requested_tools,
            registered_tools=registered_tools,
        )
        key = str(session_key or "").strip()
        if not key:
            return current

        now = self.clock()
        cached = self._cache.get(key)
        if cached is not None:
            cached_tools = _normalize_tools(
                list(cached.tools),
                registered_tools=registered_tools,
            )
            if self._can_reuse(
                cached_tools=cached_tools,
                current_tools=current,
                cached_at=cached.updated_at,
                now=now,
                may_write=may_write,
            ):
                self._cache[key] = _CachedToolExposure(
                    tools=tuple(cached_tools),
                    updated_at=now,
                )
                return cached_tools

        self._cache[key] = _CachedToolExposure(tools=tuple(current), updated_at=now)
        return current

    def clear(self) -> None:
        self._cache.clear()

    def _can_reuse(
        self,
        *,
        cached_tools: list[str],
        current_tools: list[str],
        cached_at: float,
        now: float,
        may_write: bool,
    ) -> bool:
        if not cached_tools or len(cached_tools) > self.max_reused_tools:
            return False
        if now - cached_at > self.ttl_seconds:
            return False
        current_set = set(current_tools)
        cached_set = set(cached_tools)
        if not cached_set.issuperset(current_set):
            return False
        extra_tools = cached_set - current_set
        if extra_tools.intersection(_NON_REUSABLE_EXTRA_TOOLS):
            return False
        if may_write:
            return True
        return not any(_looks_write_capable(tool) for tool in extra_tools)


default_tool_exposure_policy = ToolExposurePolicy()


__all__ = ["ToolExposurePolicy", "default_tool_exposure_policy"]
