"""Persist sensor source-item fingerprints to dedupe future ingest."""
from __future__ import annotations
import asyncio
import logging
from typing import Optional

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SensorEventEmitted
from magi.events.payload_helpers import expect_payload, PayloadTypeError

logger = logging.getLogger(__name__)


class SensorStateUpdateSubscriber:
    def __init__(self, *, event_bus, sensor_state_store) -> None:
        self._bus = event_bus
        self._state_store = sensor_state_store
        self._sub_id: Optional[str] = None
        self._inflight: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._sub_id = await self._bus.subscribe(
            EventTypes.SENSOR_EVENT_EMITTED, self._on_event,
        )

    async def stop(self) -> None:
        if self._sub_id is not None:
            try:
                await self._bus.unsubscribe(self._sub_id)
            except Exception:
                logger.exception("sensor_state_subscriber unsubscribe failed")
            self._sub_id = None
        await self.drain()

    async def drain(self) -> None:
        if not self._inflight:
            return
        await asyncio.gather(*list(self._inflight), return_exceptions=True)

    async def _on_event(self, event: Event) -> None:
        try:
            payload = expect_payload(event, SensorEventEmitted)
        except PayloadTypeError:
            return
        if not payload.sensor_fingerprint:
            return
        task = asyncio.create_task(self._safe_persist(payload.sensor_id, payload.sensor_fingerprint))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _safe_persist(self, sensor_id: str, fingerprint: str) -> None:
        try:
            await self._state_store.add_fingerprints(sensor_id, {fingerprint})
        except Exception:
            logger.exception(
                "sensor_state add_fingerprints failed (sensor=%s)", sensor_id,
            )
