"""
Action executor for runtime agents.
"""
from __future__ import annotations

import time

from ...core.logger import get_logger
from ...api.websocket import manager as ws_manager
from ...events.backend import MessageBusBackend
from ...events.events import Event, EventLevel, EventTypes
from .contracts import FactRecord

logger = get_logger(__name__)


class ActionExecutor:
    """Runtime action emitter for task-agent execution results."""

    def __init__(self, message_bus: MessageBusBackend) -> None:
        self._message_bus = message_bus

    async def emit_chat_response(self, user_id: str, session_id: str, response: str) -> None:
        room = f"user_{user_id}"
        response_data = {
            "response": response,
            "timestamp": time.time(),
            "user_id": user_id,
            "session_id": session_id,
        }
        await ws_manager.broadcast("agent_response", response_data, room=room)

    async def emit_action_event(self, fact: FactRecord, success: bool, error: str | None = None) -> None:
        try:
            await self._message_bus.publish(
                Event(
                    type=EventTypes.ACTION_EXECUTED,
                    data={
                        "agent_id": fact.agent_id,
                        "event_type": fact.event_type,
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
