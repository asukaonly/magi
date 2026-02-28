"""
Sensor layer for five-layer architecture.
"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

from ...events.backend import MessageBusBackend
from ...events.events import Event, EventTypes
from ...core.logger import get_logger
from .contracts import LayerContext
from .stubs import build_default_stub_sensors, StubSensor

logger = get_logger(__name__)


class SensorLayer:
    """Consumes message bus events and emits normalized layer contexts."""

    def __init__(
        self,
        message_bus: MessageBusBackend,
        on_context: Callable[[LayerContext], Awaitable[None]],
    ) -> None:
        self._message_bus = message_bus
        self._on_context = on_context
        self._subscription_id: Optional[str] = None
        self._stub_sensors: list[StubSensor] = build_default_stub_sensors()

    async def start(self) -> None:
        if self._subscription_id:
            return
        self._subscription_id = await self._message_bus.subscribe(
            EventTypes.USER_MESSAGE,
            self._handle_user_message,
            propagation_mode="broadcast",
        )
        logger.info("SensorLayer subscribed to USER_MESSAGE")

    async def stop(self) -> None:
        if not self._subscription_id:
            return
        await self._message_bus.unsubscribe(self._subscription_id)
        self._subscription_id = None
        logger.info("SensorLayer unsubscribed from USER_MESSAGE")

    def get_stub_sensors(self) -> list[dict[str, str]]:
        """Expose reserved sensor registry for introspection endpoints."""
        return [sensor.to_dict() for sensor in self._stub_sensors]

    async def _handle_user_message(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        message = str(data.get("message", "")).strip()
        user_id = str(data.get("user_id", "web_user"))
        session_id = str(data.get("session_id") or "")
        if not message:
            return
        if not session_id:
            # Session should already be resolved in API; fallback keeps chain robust.
            session_id = "default-session"
        context = LayerContext(
            user_id=user_id,
            message=message,
            session_id=session_id,
            metadata=data.get("metadata") or {},
            timestamp=float(data.get("timestamp") or event.timestamp),
            correlation_id=event.correlation_id,
        )
        await self._on_context(context)
