"""
Action executor for runtime agents.
"""
from __future__ import annotations

import time

from ...core.logger import get_logger
from ...events.backend import MessageBusBackend
from ...events.events import Event, EventLevel, EventTypes
from .contracts import FactRecord

logger = get_logger(__name__)


class ActionExecutor:
    """Runtime action emitter for task-agent execution results."""

    def __init__(self, message_bus: MessageBusBackend) -> None:
        self._message_bus = message_bus

    async def emit_chat_response_event(self, user_id: str, session_id: str, response: str) -> None:
        response_data = {
            "response": response,
            "timestamp": time.time(),
            "user_id": user_id,
            "session_id": session_id,
        }
        await self._message_bus.publish(
            Event(
                type=EventTypes.AI_RESPONSE,
                data=response_data,
                source="runtime_action_executor",
                level=EventLevel.INFO,
            )
        )

    async def emit_action_event(self, fact: FactRecord, success: bool, error: str | None = None) -> None:
        try:
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            action_type = payload.get("action_type")
            if not action_type:
                action_type = payload.get("tool_name")
            if not action_type and fact.event_type == EventTypes.USER_MESSAGE:
                action_type = "ChatResponseAction"
            if not action_type:
                action_type = str(fact.event_type or "UnknownAction")

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
                        "agent_id": fact.agent_id,
                        "event_type": fact.event_type,
                        "action_type": str(action_type),
                        "params": params if isinstance(params, dict) else {},
                        "execution_time": float(execution_time or 0.0),
                        "response": response if isinstance(response, str) else "",
                        "user_id": payload.get("user_id"),
                        "session_id": payload.get("session_id"),
                        "success": success,
                        "error": error,
                    },
                    source="runtime_action_executor",
                    level=EventLevel.INFO if success else EventLevel.ERROR,
                    correlation_id=fact.correlation_id,
                )
            )
        except Exception as exc:
            logger.warning(f"Failed to publish action execution event: {exc}")
