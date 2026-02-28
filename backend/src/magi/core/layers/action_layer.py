"""
Action layer for five-layer architecture.
"""
from __future__ import annotations

from ...core.logger import get_logger
from ...events.backend import MessageBusBackend
from ...events.events import Event, EventLevel, EventTypes
from ...processing.actions import ChatResponseAction
from .contracts import LayerResult, TaskEnvelope
from .stubs import StubActionCapabilities

logger = get_logger(__name__)


class ActionLayer:
    """Unified execution entry for llm/tool/response actions."""

    def __init__(self, chat_agent, message_bus: MessageBusBackend) -> None:
        self._chat_agent = chat_agent
        self._message_bus = message_bus
        self._stub_actions = StubActionCapabilities()

    async def execute(self, task: TaskEnvelope) -> LayerResult:
        if task.decision.stub_capability:
            result = await self._stub_actions.execute(task.decision.stub_capability, task.context)
            await self._emit_stub_response(task, result)
            await self._emit_action_event(task, result)
            return result

        action = ChatResponseAction(
            chain_id=task.context.correlation_id,
            user_id=task.context.user_id,
            user_message=task.context.message,
            session_id=task.context.session_id,
            intent=task.decision.intent,
        )
        output = await self._chat_agent.execute_action(action)
        result = LayerResult(
            success=bool(output.get("success")),
            payload=output,
            error=output.get("error"),
            need_user_intervention=task.decision.need_user_intervention,
        )
        await self._emit_action_event(task, result)
        return result

    async def _emit_action_event(self, task: TaskEnvelope, result: LayerResult) -> None:
        try:
            await self._message_bus.publish(
                Event(
                    type=EventTypes.ACTION_EXECUTED,
                    data={
                        "task_id": task.task_id,
                        "user_id": task.context.user_id,
                        "session_id": task.context.session_id,
                        "intent": task.decision.intent,
                        "success": result.success,
                        "stub_capability": result.stub_capability.value if result.stub_capability else None,
                        "error": result.error,
                    },
                    source="five_layer_action",
                    level=EventLevel.INFO if result.success else EventLevel.ERROR,
                    correlation_id=task.context.correlation_id,
                )
            )
        except Exception as exc:
            logger.warning(f"Failed to emit action event: {exc}")

    async def _emit_stub_response(self, task: TaskEnvelope, result: LayerResult) -> None:
        from ...api.websocket import manager

        room = f"user_{task.context.user_id}"
        response_data = {
            "response": result.payload.get("message", "Capability reserved and not implemented yet."),
            "timestamp": task.context.timestamp,
            "user_id": task.context.user_id,
            "session_id": task.context.session_id,
        }
        await manager.broadcast("agent_response", response_data, room=room)
