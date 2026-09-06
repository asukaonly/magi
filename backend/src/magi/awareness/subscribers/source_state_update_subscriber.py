"""Persist source-item fingerprints to dedupe future ingest."""
from __future__ import annotations
import logging
from typing import Any, Optional

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SourceEventEmitted
from magi.events.payload_helpers import expect_payload, PayloadTypeError

logger = logging.getLogger(__name__)


class SourceStateUpdateSubscriber:
    def __init__(self, *, event_bus, source_state_writer) -> None:
        self._bus = event_bus
        self._writer = source_state_writer
        self._sub_id: Optional[str] = None

    async def start(self) -> None:
        await self._writer.start()
        try:
            self._sub_id = await self._bus.subscribe(
                EventTypes.SOURCE_EVENT_EMITTED, self._on_event,
            )
        except Exception:
            await self._writer.stop()
            raise

    async def stop(self) -> None:
        if self._sub_id is not None:
            try:
                await self._bus.unsubscribe(self._sub_id)
            except Exception:
                logger.exception("source_state_subscriber unsubscribe failed")
            self._sub_id = None
        await self._writer.stop()

    async def drain(self) -> None:
        await self._writer.drain()

    def get_stats(self) -> Any:
        return self._writer.get_stats()

    async def _on_event(self, event: Event) -> None:
        try:
            payload = expect_payload(event, SourceEventEmitted)
        except PayloadTypeError:
            return
        if not payload.source_fingerprint:
            return
        try:
            provenance = dict((payload.output_dict or {}).get("provenance") or {})
            connection_id = provenance.get("source_connection_id")
            if not connection_id:
                raise ValueError("Source fingerprint requires a host-issued connection identity")
            await self._writer.add_fingerprint(f"{connection_id}:{payload.source_id}", payload.source_fingerprint)
        except Exception:
            logger.exception(
                "source_state enqueue fingerprint failed (source=%s)", payload.source_id,
            )
