"""Subscribes to domain events on the bus and routes them into UnifiedMemoryStore.

Heavy work (translation + DB writes) is offloaded onto asyncio.create_task so the
event-bus publish loop is never blocked. Tests can call drain() to await all
inflight ingest tasks before assertions or before shutdown.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Set

from magi.events.events import Event, EventTypes, published_memory_epoch
from magi.memory.event_translation import translate

logger = logging.getLogger(__name__)


_SUBSCRIBED_EVENT_TYPES = (
    EventTypes.TOOL_INVOCATION_COMPLETED,
    EventTypes.SPAN_COMPLETED,
    EventTypes.USER_MESSAGE_RECEIVED,
    EventTypes.ASSISTANT_RESPONSE_PRODUCED,
    EventTypes.SENSOR_EVENT_EMITTED,
    EventTypes.TASK_STARTED,
    EventTypes.TASK_COMPLETED,
    EventTypes.TASK_FAILED,
    EventTypes.SKILL_INVOCATION_COMPLETED,
)


class MemoryIngestionSubscriber:
    def __init__(self, *, event_bus, unified_memory):
        self._bus = event_bus
        self._unified = unified_memory
        self._sub_ids: list[str] = []
        self._inflight: Set[asyncio.Task] = set()

    async def start(self) -> None:
        for event_type in _SUBSCRIBED_EVENT_TYPES:
            sid = await self._bus.subscribe(event_type, self._on_event)
            self._sub_ids.append(sid)

    async def stop(self) -> None:
        for sid in list(self._sub_ids):
            try:
                await self._bus.unsubscribe(sid)
            except Exception:
                logger.exception("memory ingestion subscriber unsubscribe failed")
        self._sub_ids.clear()
        await self.drain()

    async def drain(self) -> None:
        if not self._inflight:
            return
        await asyncio.gather(*list(self._inflight), return_exceptions=True)

    async def _on_event(self, event: Event) -> None:
        expected_epoch = published_memory_epoch(event)
        if expected_epoch is None:
            logger.error(
                "memory ingest rejected event without a valid publication epoch: "
                "event_type=%s",
                event.type,
            )
            return
        memory_event = translate(event)
        if memory_event is None:
            return
        task = asyncio.create_task(self._safe_ingest(memory_event, expected_epoch))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _safe_ingest(self, memory_event, expected_epoch: int) -> None:
        try:
            await self._unified.ingest_event(
                memory_event,
                expected_epoch=expected_epoch,
            )
        except Exception:
            logger.exception("memory ingest failed for event_type=%s", memory_event.event_type)
