"""Action emitter for runtime agents."""

from __future__ import annotations

import time
from typing import Any

from .contracts import ActionEmissionRecord
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


class ActionEmitter:
    """Outbound action event emitter for task-agent execution results."""

    def __init__(self, message_bus: MessageBusBackend) -> None:
        self._message_bus = message_bus

    async def emit_chat_response_event(
        self,
        user_id: str,
        session_id: str,
        response: str,
        correlation_id: str | None = None,
        turn_id: str | None = None,
        orchestration_id: str | None = None,
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
        if orchestration_id:
            response_data["orchestration_id"] = orchestration_id
        if trace_summary is not None:
            response_data["trace_summary"] = trace_summary
            response_data["trace_available"] = trace_available
        await self._message_bus.publish(
            Event(
                type=EventTypes.AI_RESPONSE,
                data=response_data,
                source="runtime_action_emitter",
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
            orchestration_id=orchestration_id or None,
            correlation_id=correlation_id or None,
            response_chars=len(response),
            trace_available=trace_available,
        )

    async def emit_action_event(self, record: ActionEmissionRecord, success: bool, error: str | None = None) -> None:
        try:
            payload = record.payload if isinstance(record.payload, dict) else {}
            action_type = payload.get("action_type")
            if not action_type:
                action_type = payload.get("tool_name")
            if not action_type and record.event_type == EventTypes.USER_MESSAGE:
                action_type = "ChatResponseAction"
            if not action_type:
                action_type = str(record.event_type or "UnknownAction")

            params = payload.get("params")
            if params is None:
                params = payload.get("arguments")
            if params is None:
                params = {}

            execution_time = payload.get("execution_time")
            if execution_time is None:
                execution_time = payload.get("execution_time_ms", 0.0)
            response = payload.get("response")

            await self._message_bus.publish(
                Event(
                    type=EventTypes.ACTION_EXECUTED,
                    data={
                        "agent_id": record.agent_id,
                        "event_type": record.event_type,
                        "action_type": str(action_type),
                        "params": params if isinstance(params, dict) else {},
                        "execution_time": float(execution_time or 0.0),
                        "response": response if isinstance(response, str) else "",
                        "user_id": payload.get("user_id"),
                        "session_id": payload.get("session_id"),
                        "turn_id": payload.get("turn_id"),
                        "orchestration_id": payload.get("orchestration_id"),
                        "success": success,
                        "error": error,
                    },
                    source="runtime_action_emitter",
                    level=EventLevel.INFO if success else EventLevel.ERROR,
                    correlation_id=record.correlation_id,
                    metadata=_critical_delivery_metadata(),
                )
            )
        except Exception as exc:
            logger.warning(f"Failed to publish action execution event: {exc}")

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
                source="runtime_action_emitter",
                level=EventLevel.INFO if success else EventLevel.ERROR,
                correlation_id=correlation_id,
                metadata=_critical_delivery_metadata(),
            )
        )
