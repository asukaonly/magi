"""Runtime event emitter for runtime agents."""

from __future__ import annotations

import time
from typing import Any

from ..core.logger import get_logger
from ..events.backend import MessageBusBackend
from ..events.events import (
    Event,
    EventLevel,
    EventTypes,
    REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY,
)

logger = get_logger(__name__)


def _critical_delivery_metadata() -> dict[str, bool]:
    return {REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY: True}


class RuntimeEventEmitter:
    """Outbound runtime event emitter for task-agent execution results."""

    def __init__(self, message_bus: MessageBusBackend) -> None:
        self._message_bus = message_bus

    async def emit_chat_response_event(
        self,
        user_id: str,
        session_id: str,
        response: str,
        correlation_id: str | None = None,
        turn_id: str | None = None,
        trace_summary: dict[str, Any] | None = None,
        trace_available: bool = False,
    ) -> None:
        response_data = {
            "content": response,
            "author_type": "assistant",
            "content_type": "text",
            "timestamp": time.time(),
            "user_id": user_id,
            "session_id": session_id,
        }
        if turn_id:
            response_data["turn_id"] = turn_id
        if trace_summary is not None:
            response_data["trace_summary"] = trace_summary
            response_data["trace_available"] = trace_available
        await self._message_bus.publish(
            Event(
                type=EventTypes.AI_RESPONSE,
                data=response_data,
                source="runtime_event_emitter",
                level=EventLevel.INFO,
                correlation_id=correlation_id,
                metadata=_critical_delivery_metadata(),
            )
        )
        logger.info(
            "AI_RESPONSE published to message bus",
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id or None,
            correlation_id=correlation_id or None,
            response_chars=len(response),
            trace_available=trace_available,
        )

    async def emit_runtime_event(
        self,
        *,
        event_type: str,
        payload: dict[str, object],
        correlation_id: str | None = None,
        success: bool = True,
    ) -> None:
        await self._message_bus.publish(
            Event(
                type=event_type,
                data=payload,
                source="runtime_event_emitter",
                level=EventLevel.INFO if success else EventLevel.ERROR,
                correlation_id=correlation_id,
                metadata=_critical_delivery_metadata(),
            )
        )
