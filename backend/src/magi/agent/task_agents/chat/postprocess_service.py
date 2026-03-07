"""Post-processing and side effects for chat execution results."""
from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from ....core.logger import get_logger
from ....core.runtime.contracts import FactRecord
from ....core.runtime.types import TaskAgentType
from ....events.events import EventTypes
from ....memory.behavior_evolution import SatisfactionLevel
from ....memory.emotional_state import EngagementLevel, InteractionOutcome
from ....memory.growth_memory import InteractionType
from ..common import ExecutionResult, FunctionCallingExecutionResult, IncomingFactKind
from ..explore.constants import EXPLORE_TASK_COMPLETED
from .contracts import ChatParseOutcome, ChatRuntimeContext
from .fact_classifier import WORKER_AGENT_EVENT_TYPES
from .session_service import ChatSessionService

logger = get_logger(__name__)

TOOL_INTERACTION_EVENT_TYPE = "TOOL_INTERACTION"
CHAT_TOOL_LOOP_STEP_EVENT_TYPE = "CHAT_TOOL_LOOP_STEP"


class ChatPostProcessService:
    """Applies side effects for chat execution results."""

    def __init__(
        self,
        *,
        agent_id: str,
        session_service: ChatSessionService,
        get_action_executor: Callable[[], Any],
        memory=None,
        other_memory=None,
        max_fact_memory: int = 200,
    ) -> None:
        self._agent_id = agent_id
        self._session_service = session_service
        self._get_action_executor = get_action_executor
        self._memory = memory
        self._other_memory = other_memory
        self._local_fact_memory: list[FactRecord] = []
        self._max_fact_memory = max_fact_memory

    async def handle(self, context: ChatRuntimeContext, result: ExecutionResult) -> ChatParseOutcome:
        action_executor = self._get_action_executor()
        if action_executor is None or result.skip_emit:
            return ChatParseOutcome(False, False, False, False)
        latest_fact = context.latest_fact
        if not isinstance(latest_fact, FactRecord):
            return ChatParseOutcome(False, False, False, False)
        if context.incoming_fact_kind not in {
            IncomingFactKind.USER_MESSAGE,
            IncomingFactKind.WORKER_UPDATE,
            IncomingFactKind.EXPLORE_TASK_COMPLETED,
        }:
            return ChatParseOutcome(False, False, False, False)

        response_text = str(result.response_text or "").strip()
        if not response_text:
            execution_outcome = (
                result.execution_outcome
                if isinstance(result, FunctionCallingExecutionResult)
                else {}
            )
            if isinstance(execution_outcome, dict) and execution_outcome.get("status") == "failed":
                failure_reason = str(execution_outcome.get("failure_reason") or "EXECUTION_ERROR")
                response_text = f"Execution failed: {failure_reason}"
        if not response_text:
            return ChatParseOutcome(False, False, False, False)

        history_stored = False
        user_message = result.root_user_message or context.latest_user_message
        if latest_fact.event_type == EventTypes.USER_MESSAGE and user_message:
            self._session_service.append_user_message(context.history_key, user_message)
            history_stored = True
        self._session_service.append_assistant_message(context.history_key, response_text)
        history_stored = True

        memory_updated = False
        if user_message:
            memory_updated = await self._record_memory_updates(
                user_id=context.user_id,
                user_message=user_message,
            )

        correlation_id = result.correlation_id or latest_fact.correlation_id
        await action_executor.emit_chat_response_event(
            user_id=context.user_id,
            session_id=context.session_id,
            response=response_text,
            correlation_id=correlation_id,
        )
        now = time.time()
        message_started_at = float(result.message_started_at or latest_fact.timestamp or now)
        response_time = max(0.0, now - message_started_at)
        action_payload = dict(latest_fact.payload) if isinstance(latest_fact.payload, dict) else {}
        action_payload.update(
            {
                "action_type": "ChatResponseAction",
                "response": response_text,
                "execution_time": response_time,
                "user_id": context.user_id,
                "session_id": context.session_id,
                "orchestration_id": result.orchestration_id,
            }
        )
        await action_executor.emit_action_event(
            fact=FactRecord(
                agent_id=latest_fact.agent_id,
                event_type=(
                    EventTypes.AI_RESPONSE
                    if latest_fact.event_type in WORKER_AGENT_EVENT_TYPES or latest_fact.event_type == EXPLORE_TASK_COMPLETED
                    else latest_fact.event_type
                ),
                payload=action_payload,
                agent_type=latest_fact.agent_type,
                agent_instance_id=latest_fact.agent_instance_id,
                timestamp=latest_fact.timestamp,
                correlation_id=correlation_id,
            ),
            success=True,
            error=None,
        )
        return ChatParseOutcome(True, history_stored, memory_updated, False)

    async def record_tool_interaction(self, payload: dict[str, Any]) -> None:
        user_id = str(payload.get("user_id") or self._agent_id)
        session_id = self._session_service.resolve_session_id(user_id, payload.get("session_id"))
        history_key = self._session_service.history_key(user_id, session_id)
        self._session_service.store_tool_interaction(
            history_key,
            {
                "timestamp": time.time(),
                "intent": payload.get("intent") or "unknown",
                "tool_name": str(payload.get("tool_name") or "unknown"),
                "status": "success" if bool(payload.get("success")) else "error",
                "error_code": str(payload.get("error_code") or ""),
                "error_message": str(payload.get("error") or ""),
                "result_summary": str(payload.get("data") or ""),
            },
        )

        action_executor = self._get_action_executor()
        if action_executor is None:
            return
        tool_name = str(payload.get("tool_name") or "unknown")
        arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        execution_time = float(payload.get("execution_time") or 0.0)
        success = bool(payload.get("success"))
        error_text = str(payload.get("error") or "") or None
        await action_executor.emit_action_event(
            fact=FactRecord(
                agent_id=self._agent_id,
                event_type=TOOL_INTERACTION_EVENT_TYPE,
                payload={
                    "action_type": tool_name,
                    "tool_name": tool_name,
                    "params": arguments,
                    "arguments": arguments,
                    "execution_time": execution_time,
                    "user_id": user_id,
                    "session_id": session_id,
                },
                correlation_id=str(payload.get("tool_call_id") or str(uuid.uuid4())),
            ),
            success=success,
            error=error_text,
        )

    async def record_tool_loop_fact(self, payload: dict[str, Any]) -> None:
        user_id = str(payload.get("user_id") or self._agent_id)
        session_id = self._session_service.resolve_session_id(user_id, payload.get("session_id"))
        stage = str(payload.get("stage") or "unknown")
        fact = FactRecord(
            agent_id=f"{TaskAgentType.CHAT.value}:{user_id}",
            event_type=CHAT_TOOL_LOOP_STEP_EVENT_TYPE,
            payload={
                "stage": stage,
                "iteration": payload.get("iteration"),
                "max_iterations": payload.get("max_iterations"),
                "tool_name": payload.get("tool_name"),
                "tool_names": payload.get("tool_names"),
                "tool_count": payload.get("tool_count"),
                "tool_call_id": payload.get("tool_call_id"),
                "success": payload.get("success"),
                "error": payload.get("error"),
                "execution_time": payload.get("execution_time"),
                "response_preview": payload.get("response_preview"),
                "intent": payload.get("intent"),
                "execution_agent_id": payload.get("execution_agent_id"),
                "user_id": user_id,
                "session_id": session_id,
                "timestamp": time.time(),
            },
            agent_type=TaskAgentType.CHAT.value,
            agent_instance_id=user_id,
            timestamp=time.time(),
            correlation_id=str(payload.get("tool_call_id") or str(uuid.uuid4())),
        )
        try:
            from ....runtime import get_agent_runtime

            runtime = get_agent_runtime()
            manager = runtime.get_task_agent_manager()
            await manager.add_fact_to_agent(TaskAgentType.CHAT, user_id, fact)
        except Exception as exc:
            logger.debug("Failed to append loop stage fact via runtime manager: %s", exc)
            self._local_fact_memory.append(fact)
            if len(self._local_fact_memory) > self._max_fact_memory:
                self._local_fact_memory = self._local_fact_memory[-self._max_fact_memory :]

    async def _record_memory_updates(self, *, user_id: str, user_message: str) -> bool:
        updated = False
        if self._memory is not None:
            try:
                await self._memory.record_interaction(
                    user_id=user_id,
                    interaction_type=InteractionType.CHAT,
                    outcome="success",
                    sentiment=0.0,
                    notes=f"Message: {user_message[:100]}...",
                )
                await self._memory.update_after_interaction(
                    outcome=InteractionOutcome.SUCCESS,
                    user_engagement=EngagementLevel.MEDIUM,
                    complexity=0.5,
                )
                await self._memory.record_task_outcome(
                    task_id=f"chat_{int(time.time())}_{user_id}",
                    task_category="chat",
                    user_satisfaction=SatisfactionLevel.NEUTRAL,
                    accepted=True,
                    task_complexity=0.5,
                    task_duration=0.0,
                )
                updated = True
            except Exception as exc:
                logger.warning("Failed to update self memory: %s", exc)
        if self._other_memory is not None:
            try:
                self._other_memory.update_interaction(
                    user_id=user_id,
                    interaction_type="chat",
                    outcome="positive",
                    notes=f"Message: {user_message[:100]}",
                )
                updated = True
            except Exception as exc:
                logger.warning("Failed to update other memory: %s", exc)
        return updated
