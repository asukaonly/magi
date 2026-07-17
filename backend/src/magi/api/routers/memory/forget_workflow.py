"""HTTP-facing adapters for unified source-event forgetting."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


async def delete_user_event(
    memory: Any,
    *,
    event_id: str,
) -> bool:
    """Delegate one user deletion to the memory-domain coordinator."""
    return bool(
        await memory.forget_source_event(
            event_id,
            reason="user_delete_event",
        )
    )


async def delete_known_user_events(
    memory: Any,
    *,
    event_ids: Iterable[str],
    reason: str,
) -> int:
    """Delegate one known set to the memory-domain coordinator."""
    return int(await memory.forget_known_source_events(event_ids, reason=reason))


__all__ = [
    "delete_known_user_events",
    "delete_user_event",
]
