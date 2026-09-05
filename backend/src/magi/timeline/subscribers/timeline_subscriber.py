"""Project SourceEventEmitted into the timeline read model."""
from __future__ import annotations
import asyncio
import logging
from typing import Optional

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SourceEventEmitted
from magi.events.payload_helpers import expect_payload, PayloadTypeError
from ..contracts import TimelineEvent
from ..source_event_projection import build_timeline_event_dict

logger = logging.getLogger(__name__)


class TimelineSubscriber:
    def __init__(self, *, event_bus, timeline_adapter) -> None:
        self._bus = event_bus
        self._adapter = timeline_adapter
        self._sub_id: Optional[str] = None
        self._inflight: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._sub_id = await self._bus.subscribe(
            EventTypes.SOURCE_EVENT_EMITTED, self._on_event,
        )

    async def stop(self) -> None:
        if self._sub_id is not None:
            try:
                await self._bus.unsubscribe(self._sub_id)
            except Exception:
                logger.exception("timeline_subscriber unsubscribe failed")
            self._sub_id = None
        await self.drain()

    async def drain(self) -> None:
        if not self._inflight:
            return
        await asyncio.gather(*list(self._inflight), return_exceptions=True)

    async def _on_event(self, event: Event) -> None:
        try:
            payload = expect_payload(event, SourceEventEmitted)
        except PayloadTypeError:
            return
        try:
            timeline_event_dict = build_timeline_event_dict(payload, event_id=event.event_id)
            timeline_event = TimelineEvent.from_dict(timeline_event_dict)
        except Exception:
            logger.exception("build timeline event failed (event_id=%s)", event.event_id)
            return
        task = asyncio.create_task(self._safe_dispatch(timeline_event))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _safe_dispatch(self, timeline_event) -> None:
        try:
            await self._adapter.on_timeline_event(timeline_event)
        except Exception:
            logger.exception(
                "timeline_adapter.on_timeline_event failed (event_id=%s)",
                getattr(timeline_event, "event_id", None),
            )
