"""Hooks API router — read-only inspection of registered hooks.

Exposes the live ``HookRegistry`` state so the frontend Settings UI can
show which hooks are loaded and from where.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...core.container import get_container

logger = logging.getLogger(__name__)

hooks_router = APIRouter(prefix="/api/hooks", tags=["hooks"])


class HookEntryResponse(BaseModel):
    event_type: str
    matcher: Optional[str] = None
    source: Optional[str] = None


class HooksListResponse(BaseModel):
    total: int = Field(default=0)
    entries: List[HookEntryResponse] = Field(default_factory=list)


def _resolve_registry():
    try:
        registry = get_container().hook_registry()
    except Exception:
        return None
    if registry is None or type(registry).__name__ == "object":
        return None
    return registry


@hooks_router.get("", response_model=HooksListResponse)
async def list_hooks() -> HooksListResponse:
    """Return the registered hooks grouped by event type."""
    registry = _resolve_registry()
    if registry is None:
        return HooksListResponse(total=0, entries=[])
    entries: list[HookEntryResponse] = []
    # Snapshot under lock to avoid TOCTOU.
    with registry._lock:  # noqa: SLF001 — internal access is intentional
        handlers_by_event = {
            event_type: list(handlers)
            for event_type, handlers in registry._handlers.items()  # noqa: SLF001
        }
        matchers = dict(registry._matchers)  # noqa: SLF001
        sources = dict(registry._sources)  # noqa: SLF001
    for event_type, handlers in handlers_by_event.items():
        for handler in handlers:
            entries.append(
                HookEntryResponse(
                    event_type=event_type.value,
                    matcher=matchers.get(id(handler)),
                    source=sources.get(id(handler)),
                )
            )
    return HooksListResponse(total=len(entries), entries=entries)


__all__ = ["hooks_router"]
