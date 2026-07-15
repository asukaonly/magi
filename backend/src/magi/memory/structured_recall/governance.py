"""Shared correction governance for structured L1 recall expansion."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


EventIdBlocklist = Callable[[list[str]], Awaitable[set[str]]]


async def exclude_governed_events(
    events: list[dict[str, Any]],
    *,
    event_id_blocklist: EventIdBlocklist | None,
) -> list[dict[str, Any]]:
    """Remove blocked events before structured totals and coverage are computed."""
    if event_id_blocklist is None:
        return events
    event_ids = [str(event.get("event_id") or "").strip() for event in events]
    blocked = {
        str(event_id).strip()
        for event_id in await event_id_blocklist(event_ids)
        if str(event_id).strip()
    }
    return [
        event
        for event in events
        if str(event.get("event_id") or "").strip()
        and str(event.get("event_id") or "").strip() not in blocked
    ]


__all__ = ["EventIdBlocklist", "exclude_governed_events"]
