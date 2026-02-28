"""
Action executor for runtime agents.
"""
from __future__ import annotations

from ...core.logger import get_logger
from ...events.backend import MessageBusBackend
from ...events.events import Event, EventLevel, EventTypes
from ...processing.actions import ChatResponseAction
from .contracts import FactRecord

logger = get_logger(__name__)


class ActionExecutor:
    """Executes actions derived from agent facts."""

    def __init__(self, chat_agent, message_bus: MessageBusBackend) -> None:
        self._chat_agent = chat_agent
        self._message_bus = message_bus

    async def execute_chat_fact(self, fact: FactRecord) -> dict:
        payload = fact.payload
        action = ChatResponseAction(
            chain_id=fact.correlation_id or "",
            user_id=str(payload.get("user_id", "web_user")),
            user_message=str(payload.get("message", "")),
            session_id=str(payload.get("session_id") or None) if payload.get("session_id") else None,
            intent="chat",
            timestamp=float(payload.get("timestamp", fact.timestamp)),
        )
        result = await self._chat_agent.execute_action(action)
        await self._emit_action_event(fact, result)
        return result

    async def _emit_action_event(self, fact: FactRecord, result: dict) -> None:
        try:
            await self._message_bus.publish(
                Event(
                    type=EventTypes.ACTION_EXECUTED,
                    data={
                        "agent_id": fact.agent_id,
                        "event_type": fact.event_type,
                        "success": bool(result.get("success")),
                        "error": result.get("error"),
                    },
                    source="runtime_action_executor",
                    level=EventLevel.INFO if result.get("success") else EventLevel.ERROR,
                    correlation_id=fact.correlation_id,
                )
            )
        except Exception as exc:
            logger.warning(f"Failed to publish action execution event: {exc}")
