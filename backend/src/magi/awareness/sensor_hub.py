"""Sensor hub: aggregates sensor events into a unified queue."""
from __future__ import annotations

import asyncio
from typing import Optional

from ..core.logger import get_logger
from ..events.backend import MessageBusBackend
from ..events.events import Event, EventTypes
from ..runtime_defaults import DEFAULT_RUNTIME_NAMESPACE, DEFAULT_USER_ID
from .contracts import SensorEvent

logger = get_logger(__name__)


class SensorHub:
    """Collects events from sensors and exposes batched reads for router agent."""

    def __init__(self, message_bus: MessageBusBackend) -> None:
        self._message_bus = message_bus
        self._subscription_id: Optional[str] = None
        self._queue: asyncio.Queue[SensorEvent] = asyncio.Queue()

    async def start(self) -> None:
        if self._subscription_id:
            return
        self._subscription_id = await self._message_bus.subscribe(
            EventTypes.USER_MESSAGE,
            self._on_user_message,
            propagation_mode="broadcast",
        )
        logger.info("SensorHub subscribed to USER_MESSAGE")

    async def stop(self) -> None:
        if not self._subscription_id:
            return
        await self._message_bus.unsubscribe(self._subscription_id)
        self._subscription_id = None
        logger.info("SensorHub unsubscribed from USER_MESSAGE")

    async def push_sensor_event(self, sensor_event: SensorEvent) -> None:
        await self._queue.put(sensor_event)

    async def get_batch(self, max_items: int = 16, timeout_seconds: float = 0.2) -> list[SensorEvent]:
        batch: list[SensorEvent] = []
        try:
            first = await asyncio.wait_for(self._queue.get(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return batch

        batch.append(first)
        while len(batch) < max_items:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    async def _on_user_message(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        content = str(data.get("content") or "").strip()
        attachments = data.get("attachments") if isinstance(data.get("attachments"), list) else []
        if not content:
            if not attachments:
                return

        session_id = str(data.get("session_id") or "").strip()

        sensor_event = SensorEvent(
            sensor_name="user_input_sensor",
            event_type=EventTypes.USER_MESSAGE,
            payload={
                "content": content,
                "attachments": list(attachments),
                "user_id": str(data.get("user_id", DEFAULT_USER_ID)),
                "runtime_namespace": str(
                    data.get("runtime_namespace")
                    or (data.get("metadata") or {}).get("runtime_namespace")
                    or DEFAULT_RUNTIME_NAMESPACE
                ),
                "session_id": session_id,
                "turn_id": str(data.get("turn_id") or "").strip() or None,
                "workspace_path": str(data.get("workspace_path") or "").strip() or None,
                "metadata": data.get("metadata") or {},
                "timestamp": float(data.get("timestamp") or event.timestamp),
            },
            timestamp=float(data.get("timestamp") or event.timestamp),
            correlation_id=event.correlation_id,
        )
        await self.push_sensor_event(sensor_event)
