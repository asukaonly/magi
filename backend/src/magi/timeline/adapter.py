"""Timeline adapter — stores host-rendered TimelineEvent read models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .contracts import TimelineEvent

if TYPE_CHECKING:
    from .service import TimelineService


class TimelineAdapter:
    """Stores host-rendered TimelineEvent objects in the timeline read model."""

    def __init__(self, timeline_service: TimelineService) -> None:
        self._service = timeline_service

    async def on_timeline_event(self, event: TimelineEvent) -> None:
        """Store one pre-rendered timeline event in the timeline read model."""
        await self._service.upsert_event(event)
