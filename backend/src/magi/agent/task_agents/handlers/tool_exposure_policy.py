"""Cache-friendly tool exposure policy for function-calling turns."""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from typing import Any

from ...execution.tool_metadata import (
    ToolEffectClass,
    resolve_tool_capability_metadata,
)


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
        tool_registry: Any | None,
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
                tool_registry=tool_registry,
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
        tool_registry: Any | None,
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
        if not extra_tools:
            return True
        if tool_registry is None:
            return False
        current_effects = {
            resolve_tool_capability_metadata(tool_registry, tool).effect_class
            for tool in current_tools
        }
        for tool_name in extra_tools:
            effect_class = resolve_tool_capability_metadata(
                tool_registry,
                tool_name,
            ).effect_class
            if effect_class is ToolEffectClass.READ_ONLY:
                continue
            if effect_class in {ToolEffectClass.UNKNOWN, ToolEffectClass.DESTRUCTIVE}:
                return False
            if effect_class not in current_effects:
                return False
        return True


default_tool_exposure_policy = ToolExposurePolicy()


__all__ = ["ToolExposurePolicy", "default_tool_exposure_policy"]
