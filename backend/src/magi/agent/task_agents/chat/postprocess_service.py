"""Post-processing and side effects for chat execution results."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from ....core.logger import get_logger
from ....awareness.contracts import ActionEmissionRecord
from ....agent.runtime.contracts import FactRecord
from ....agent.runtime.types import TaskAgentType
from ....agent.trace import (
    now_wall_ms,
)
from ....events.events import EventTypes
from ....personality.behavior_evolution import SatisfactionLevel
from ....personality.emotional_state import EngagementLevel, InteractionOutcome
from ....personality.growth_memory import InteractionType
from ....memory.l3.models import TaskOutcomePacket
from ....runtime_trace import (
    RuntimeNotificationRecord,
    RuntimeTraceStore,
    TraceIntentResolutionRecord,
    TraceLlmCallRecord,
    TraceSpanRecord,
    TraceTurnRecord,
)
from ..common import ExecutionResult, FunctionCallingExecutionResult, IncomingFactKind
from ..explore.constants import EXPLORE_TASK_COMPLETED
from .contracts import ChatParseOutcome, ChatRuntimeContext
from .fact_classifier import WORKER_AGENT_EVENT_TYPES
from .history_service import ChatHistoryService

if TYPE_CHECKING:
    from ....api.services.chat_trace_read_service import ChatTraceReadService

logger = get_logger(__name__)

TOOL_INTERACTION_EVENT_TYPE = "TOOL_INTERACTION"
CHAT_TOOL_LOOP_STEP_EVENT_TYPE = "CHAT_TOOL_LOOP_STEP"


class ChatPostProcessService:
    """Applies side effects for chat execution results."""

    def __init__(
        self,
        *,
        agent_id: str,
        history_service: ChatHistoryService,
        get_action_emitter: Callable[[], Any],
        get_task_agent_manager: Callable[[], Any | None],
        get_sensor_hub: Callable[[], Any | None],
        memory=None,
        other_memory=None,
        unified_memory=None,
        max_fact_memory: int = 200,
        trace_read_service: "ChatTraceReadService | None" = None,
        runtime_trace_store: RuntimeTraceStore | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._history_service = history_service
        self._get_action_emitter = get_action_emitter
        self._get_task_agent_manager = get_task_agent_manager
        self._get_sensor_hub = get_sensor_hub
        self._memory = memory
        self._other_memory = other_memory
        self._unified_memory = unified_memory
        self._local_fact_memory: list[FactRecord] = []
        self._max_fact_memory = max_fact_memory
        self._trace_read_service = trace_read_service
        self._runtime_trace_store = runtime_trace_store
        self._started_turn_traces: set[str] = set()

    async def handle(self, context: ChatRuntimeContext, result: ExecutionResult) -> ChatParseOutcome:
        action_emitter = self._get_action_emitter()
        if action_emitter is None or result.skip_emit:
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
            self._history_service.append_user_message(context.history_key, user_message)
            history_stored = True
        self._history_service.append_assistant_message(context.history_key, response_text)
        history_stored = True

        memory_updated = False
        if user_message:
            memory_updated = await self._record_memory_updates(
                user_id=context.user_id,
                user_message=user_message,
            )
        task_reflection_updated = await self._record_task_reflection(
            context=context,
            result=result,
            user_message=user_message,
            response_text=response_text,
        )
        memory_updated = memory_updated or task_reflection_updated

        correlation_id = result.correlation_id or latest_fact.correlation_id
        turn_id = result.turn_id or self._resolve_turn_id(context, latest_fact.payload if isinstance(latest_fact.payload, dict) else {})
        now_ms = now_wall_ms()
        started_at_ms = self._resolve_started_at_ms(result, latest_fact)

        await self._emit_result_llm_trace(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
            llm_trace=getattr(result, "llm_trace", {}),
            started_at_ms=started_at_ms,
            user_message=context.latest_user_message,
        )

        await self._emit_response_trace(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
            response_text=response_text,
            started_at_ms=started_at_ms,
            ended_at_ms=now_ms,
            orchestration_id=result.orchestration_id,
            mode=self._normalize_mode(result.mode),
            user_message=context.latest_user_message,
        )

        # Fetch trace summary before emitting the response event
        trace_summary = None
        trace_available = False
        if self._trace_read_service and turn_id:
            try:
                snapshot = self._trace_read_service.get_trace_snapshot(
                    user_id=context.user_id,
                    session_id=context.session_id,
                    turn_id=turn_id,
                )
                if isinstance(snapshot, dict):
                    trace_summary = snapshot.get("summary")
                    trace_available = bool(snapshot.get("summary", {}).get("trace_available"))
            except Exception as exc:
                logger.debug("Failed to fetch trace snapshot for AI_RESPONSE event: %s", exc)

        await self._emit_agent_response_notification(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
            response_text=response_text,
            orchestration_id=result.orchestration_id,
            trace_summary=trace_summary,
            trace_available=trace_available,
            ux_plan=result.ux_plan,
        )

        await action_emitter.emit_chat_response_event(
            user_id=context.user_id,
            session_id=context.session_id,
            response=response_text,
            correlation_id=correlation_id,
            turn_id=turn_id,
            orchestration_id=result.orchestration_id,
            trace_summary=trace_summary,
            trace_available=trace_available,
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
                "turn_id": turn_id,
            }
        )
        await action_emitter.emit_action_event(
            record=ActionEmissionRecord(
                agent_id=latest_fact.agent_id,
                event_type=(
                    EventTypes.AI_RESPONSE
                    if latest_fact.event_type in WORKER_AGENT_EVENT_TYPES or latest_fact.event_type == EXPLORE_TASK_COMPLETED
                    else latest_fact.event_type
                ),
                payload=action_payload,
                correlation_id=correlation_id,
            ),
            success=True,
            error=None,
        )
        return ChatParseOutcome(True, history_stored, memory_updated, False)

    async def record_intent_resolution(self, context: ChatRuntimeContext, decision: Any) -> None:
        latest_fact = context.latest_fact
        if self._runtime_trace_store is None or not isinstance(latest_fact, FactRecord):
            return
        turn_id = self._resolve_turn_id(context, latest_fact.payload if isinstance(latest_fact.payload, dict) else {})
        if not turn_id:
            return
        trace_id = self._build_trace_id(turn_id)
        started_at_ms = self._resolve_started_at_ms(None, latest_fact)
        await self._ensure_turn_trace_started(
            trace_id=trace_id,
            turn_id=turn_id,
            user_id=context.user_id,
            session_id=context.session_id,
            started_at_ms=started_at_ms,
            user_message=context.latest_user_message,
            mode=self._normalize_mode(getattr(decision, "execution_mode", None)),
        )
        ended_at_ms = now_wall_ms()
        span_id = self._build_span_id(turn_id, "intent_resolution")
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=turn_id,
                parent_span_id=self._build_root_span_id(turn_id),
                node_type="intent_resolution",
                name="Intent resolution",
                status="completed",
                result_preview=str(getattr(decision, "intent", "") or "")[:240] or None,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=max(0, ended_at_ms - started_at_ms),
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await self._runtime_trace_store.upsert_intent_resolution(
            TraceIntentResolutionRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=turn_id,
                intent=str(getattr(decision, "intent", "") or ""),
                execution_mode=self._normalize_mode(getattr(decision, "execution_mode", None)),
                route_reason=str(getattr(decision, "reasoning", "") or "") or None,
                selected_tools_json=json.dumps(list(getattr(decision, "tools", []) or [])),
                selected_worker_type=(
                    str(getattr(getattr(decision, "orchestration_plan", None), "default_leaf_type", "") or "")
                    or None
                ),
            )
        )
        await self._emit_turn_ux_plan_notification(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
            ux_plan=self._serialize_ux_plan(decision),
        )

    async def _record_task_reflection(
        self,
        *,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        user_message: str,
        response_text: str,
    ) -> bool:
        if self._unified_memory is None:
            return False
        if not user_message or not response_text:
            return False
        if not self._should_record_task_reflection(context=context, result=result):
            return False

        event_ids = await self._collect_reflection_event_ids(
            user_id=context.user_id,
            session_id=context.session_id,
        )
        if not event_ids:
            return False

        task_id = str(
            result.orchestration_id
            or (context.latest_fact.payload.get("orchestration_id") if isinstance(context.latest_fact, FactRecord) and isinstance(context.latest_fact.payload, dict) else "")
            or f"task_reflection_{int(time.time())}"
        ).strip()
        packet = TaskOutcomePacket(
            task_id=task_id,
            user_id=context.user_id,
            task_kind="user_goal_task",
            task_title=user_message[:120],
            task_status="completed",
            user_goal=user_message,
            result_summary=response_text,
            evidence_event_ids=event_ids,
        )
        try:
            summary = await self._unified_memory.persist_task_outcome_reflection(packet)
            return summary is not None
        except Exception as exc:
            logger.warning("Failed to persist task reflection: %s", exc)
            return False

    def _should_record_task_reflection(
        self,
        *,
        context: ChatRuntimeContext,
        result: ExecutionResult,
    ) -> bool:
        if context.incoming_fact_kind == IncomingFactKind.EXPLORE_TASK_COMPLETED:
            return True
        return context.incoming_fact_kind == IncomingFactKind.WORKER_UPDATE and bool(result.orchestration_id)

    async def _collect_reflection_event_ids(
        self,
        *,
        user_id: str,
        session_id: str,
        limit: int = 6,
    ) -> list[str]:
        l1_store = getattr(self._unified_memory, "l1", None)
        if l1_store is None or not hasattr(l1_store, "query_events"):
            return []
        try:
            events = await l1_store.query_events(
                user_id=user_id,
                session_id=session_id,
                cognition_eligible=True,
                limit=limit,
            )
        except Exception as exc:
            logger.debug("Failed to query reflection evidence events: %s", exc)
            return []
        return [str(event.get("event_id") or "").strip() for event in events if str(event.get("event_id") or "").strip()]

    async def record_tool_interaction(self, payload: dict[str, Any]) -> None:
        user_id = str(payload.get("user_id") or self._agent_id)
        session_id = self._history_service.require_session_id(user_id, payload.get("session_id"))
        history_key = self._history_service.history_key(user_id, session_id)
        turn_id = str(payload.get("turn_id") or "").strip() or None
        self._history_service.store_tool_interaction(
            history_key,
            {
                "timestamp": time.time(),
                "intent": payload.get("intent") or "unknown",
                "tool_name": str(payload.get("tool_name") or "unknown"),
                "status": "success" if bool(payload.get("success")) else "error",
                "error_code": str(payload.get("error_code") or ""),
                "error_message": str(payload.get("error") or ""),
                "result_summary": str(payload.get("data") or ""),
                "result_data": payload.get("data") if isinstance(payload.get("data"), dict) else {},
                "turn_id": turn_id,
            },
        )

        action_emitter = self._get_action_emitter()
        if action_emitter is None:
            return
        tool_name = str(payload.get("tool_name") or "unknown")
        arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        execution_time = float(payload.get("execution_time") or 0.0)
        success = bool(payload.get("success"))
        error_text = str(payload.get("error") or "") or None
        await action_emitter.emit_action_event(
            record=ActionEmissionRecord(
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
                    "turn_id": turn_id,
                    "orchestration_id": payload.get("orchestration_id"),
                    "tool_call_id": payload.get("tool_call_id"),
                    "iteration": payload.get("iteration"),
                },
                correlation_id=str(payload.get("tool_call_id") or str(uuid.uuid4())),
            ),
            success=success,
            error=error_text,
        )
        await action_emitter.emit_runtime_event(
            event_type=TOOL_INTERACTION_EVENT_TYPE,
            payload={
                "tool_name": tool_name,
                "tool_call_id": payload.get("tool_call_id"),
                "arguments": arguments,
                "success": success,
                "error": error_text,
                "error_code": payload.get("error_code"),
                "execution_time": execution_time,
                "data": payload.get("data"),
                "intent": payload.get("intent"),
                "iteration": payload.get("iteration"),
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "timestamp": time.time(),
            },
            correlation_id=str(payload.get("tool_call_id") or str(uuid.uuid4())),
            success=success,
        )
        await self._emit_trace_update_notification(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )

    async def record_tool_loop_fact(self, payload: dict[str, Any]) -> None:
        user_id = str(payload.get("user_id") or self._agent_id)
        session_id = self._history_service.require_session_id(user_id, payload.get("session_id"))
        stage = str(payload.get("stage") or "unknown")
        turn_id = str(payload.get("turn_id") or "").strip() or None
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
                "llm_trace": payload.get("llm_trace") if isinstance(payload.get("llm_trace"), dict) else None,
                "response_preview": payload.get("response_preview"),
                "intent": payload.get("intent"),
                "execution_agent_id": payload.get("execution_agent_id"),
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "timestamp": time.time(),
            },
            agent_type=TaskAgentType.CHAT.value,
            agent_instance_id=user_id,
            timestamp=time.time(),
            correlation_id=str(payload.get("tool_call_id") or str(uuid.uuid4())),
        )
        manager = self._get_task_agent_manager()
        if manager is None:
            self._local_fact_memory.append(fact)
            if len(self._local_fact_memory) > self._max_fact_memory:
                self._local_fact_memory = self._local_fact_memory[-self._max_fact_memory :]
        else:
            try:
                await manager.add_fact_to_agent(TaskAgentType.CHAT, user_id, fact)
            except Exception as exc:
                logger.debug("Failed to append loop stage fact via runtime manager: %s", exc)
                self._local_fact_memory.append(fact)
                if len(self._local_fact_memory) > self._max_fact_memory:
                    self._local_fact_memory = self._local_fact_memory[-self._max_fact_memory :]
        action_emitter = self._get_action_emitter()
        if action_emitter is not None:
            await action_emitter.emit_runtime_event(
                event_type=CHAT_TOOL_LOOP_STEP_EVENT_TYPE,
                payload=dict(fact.payload),
                correlation_id=fact.correlation_id,
                success=bool(payload.get("success", True)),
            )
        await self._emit_trace_update_notification(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )

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

    def _resolve_turn_id(self, context: ChatRuntimeContext, payload: dict[str, Any]) -> str | None:
        latest_payload = context.latest_payload
        typed_turn_id = str(getattr(latest_payload, "turn_id", "") or "").strip()
        if typed_turn_id:
            return typed_turn_id
        raw_turn_id = str(payload.get("turn_id") or "").strip()
        return raw_turn_id or None

    async def _emit_response_trace(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        response_text: str,
        started_at_ms: int,
        ended_at_ms: int,
        orchestration_id: str | None,
        mode: str,
        user_message: str,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if self._runtime_trace_store is None or not normalized_turn_id:
            return
        trace_id = self._build_trace_id(normalized_turn_id)
        await self._ensure_turn_trace_started(
            trace_id=trace_id,
            turn_id=normalized_turn_id,
            user_id=user_id,
            session_id=session_id,
            started_at_ms=started_at_ms,
            user_message=user_message,
            mode=mode,
        )
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_span_id(normalized_turn_id, "response_emit"),
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                parent_span_id=self._build_root_span_id(normalized_turn_id),
                node_type="response_emit",
                name="Response emission",
                status="completed",
                result_preview=response_text[:240] or None,
                started_at_ms=ended_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=0,
                created_at_ms=ended_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_root_span_id(normalized_turn_id),
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                parent_span_id=None,
                node_type="turn",
                name="Chat turn",
                status="completed",
                result_preview=response_text[:240] or None,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=max(0, ended_at_ms - started_at_ms),
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await self._runtime_trace_store.upsert_turn(
            TraceTurnRecord(
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                session_id=session_id,
                user_id=user_id,
                status="completed",
                mode=mode,
                orchestration_id=orchestration_id,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=max(0, ended_at_ms - started_at_ms),
                user_message_preview=user_message[:240] or None,
                response_preview=response_text[:240] or None,
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )

    async def _ensure_turn_trace_started(
        self,
        *,
        trace_id: str,
        turn_id: str,
        user_id: str,
        session_id: str,
        started_at_ms: int,
        user_message: str,
        mode: str,
    ) -> None:
        if self._runtime_trace_store is None or turn_id in self._started_turn_traces:
            return
        await self._runtime_trace_store.upsert_turn(
            TraceTurnRecord(
                trace_id=trace_id,
                turn_id=turn_id,
                session_id=session_id,
                user_id=user_id,
                status="running",
                mode=mode,
                started_at_ms=started_at_ms,
                user_message_preview=user_message[:240] or None,
                created_at_ms=started_at_ms,
                updated_at_ms=started_at_ms,
            )
        )
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_root_span_id(turn_id),
                trace_id=trace_id,
                turn_id=turn_id,
                parent_span_id=None,
                node_type="turn",
                name="Chat turn",
                status="running",
                started_at_ms=started_at_ms,
                created_at_ms=started_at_ms,
                updated_at_ms=started_at_ms,
            )
        )
        self._started_turn_traces.add(turn_id)

    async def _emit_agent_response_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        response_text: str,
        orchestration_id: str | None,
        trace_summary: dict[str, Any] | None,
        trace_available: bool,
        ux_plan: dict[str, Any] | None,
    ) -> None:
        if self._runtime_trace_store is None:
            return
        payload = {
            "content": response_text,
            "author_type": "assistant",
            "content_type": "text",
            "timestamp": time.time(),
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "orchestration_id": orchestration_id,
            "trace_summary": trace_summary,
            "trace_available": trace_available,
            "ux_plan": ux_plan,
        }
        await self._runtime_trace_store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="agent_response",
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                payload_json=json.dumps(payload, ensure_ascii=False),
                created_at_ms=now_wall_ms(),
            )
        )

    async def _emit_turn_ux_plan_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        ux_plan: dict[str, Any] | None,
    ) -> None:
        if self._runtime_trace_store is None or not turn_id or not ux_plan:
            return
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "ux_plan": ux_plan,
            "timestamp": time.time(),
        }
        await self._runtime_trace_store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="turn_ux_plan",
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                payload_json=json.dumps(payload, ensure_ascii=False),
                created_at_ms=now_wall_ms(),
            )
        )

    async def _emit_trace_update_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
    ) -> None:
        if self._runtime_trace_store is None or not turn_id:
            return
        await self._runtime_trace_store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="trace_update",
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                payload_json="{}",
                created_at_ms=now_wall_ms(),
            )
        )

    @staticmethod
    def _build_trace_id(turn_id: str) -> str:
        return f"trace:{turn_id}"

    @staticmethod
    def _build_root_span_id(turn_id: str) -> str:
        return f"{turn_id}:turn"

    @staticmethod
    def _build_span_id(turn_id: str, suffix: str) -> str:
        return f"{turn_id}:{suffix}"

    @staticmethod
    def _serialize_ux_plan(decision: Any) -> dict[str, Any] | None:
        plan = getattr(decision, "ux_plan", None)
        if plan is None:
            return None
        to_dict = getattr(plan, "to_dict", None)
        if callable(to_dict):
            payload = to_dict()
            return payload if isinstance(payload, dict) else None
        return plan if isinstance(plan, dict) else None

    @staticmethod
    def _resolve_started_at_ms(result: ExecutionResult | None, latest_fact: FactRecord) -> int:
        raw_timestamp = (
            float(result.message_started_at)
            if result is not None and result.message_started_at is not None
            else float(latest_fact.timestamp or time.time())
        )
        return max(0, int(raw_timestamp * 1000))

    async def _emit_loop_llm_trace(
        self,
        *,
        action_emitter: Any,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        stage: str,
        iteration: Any,
        execution_agent_id: Any,
        llm_trace: Any,
        response_preview: Any,
        tool_count: Any,
        tool_names: Any,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id or not isinstance(llm_trace, dict):
            return
        duration_ms = max(0, int(llm_trace.get("duration_ms") or 0))
        ended_at_ms = now_wall_ms()
        started_at_ms = max(0, ended_at_ms - duration_ms)
        _ = (action_emitter, user_id, session_id, tool_count, tool_names, response_preview, execution_agent_id)
        if self._runtime_trace_store is None:
            return
        span_id = self._build_span_id(
            normalized_turn_id,
            f"llm_call:{stage}:{int(iteration or 0)}",
        )
        trace_id = self._build_trace_id(normalized_turn_id)
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                parent_span_id=self._build_span_id(normalized_turn_id, f"iteration:{int(iteration or 0)}"),
                node_type="llm_call",
                name="Function-calling LLM call",
                status="completed",
                iteration=int(iteration or 0),
                execution_agent_id=str(execution_agent_id or "") or None,
                result_preview=str(response_preview or "")[:240] or None,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=duration_ms,
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await self._runtime_trace_store.upsert_llm_call(
            TraceLlmCallRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                provider=str(llm_trace.get("provider") or "unknown"),
                model=str(llm_trace.get("model") or "unknown"),
                input_tokens=int(llm_trace.get("input_tokens") or 0),
                output_tokens=int(llm_trace.get("output_tokens") or 0),
                reasoning_tokens=int(llm_trace.get("reasoning_tokens") or 0),
                cache_read_tokens=int(llm_trace.get("cache_read_tokens") or 0),
                cache_write_tokens=int(llm_trace.get("cache_write_tokens") or 0),
                thinking_enabled=bool(llm_trace.get("thinking_enabled")),
                response_preview=str(response_preview or "")[:240] or None,
            )
        )

    async def _emit_result_llm_trace(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        llm_trace: Any,
        started_at_ms: int,
        user_message: str,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if self._runtime_trace_store is None or not normalized_turn_id or not isinstance(llm_trace, dict) or not llm_trace:
            return
        trace_id = self._build_trace_id(normalized_turn_id)
        await self._ensure_turn_trace_started(
            trace_id=trace_id,
            turn_id=normalized_turn_id,
            user_id=user_id,
            session_id=session_id,
            started_at_ms=started_at_ms,
            user_message=user_message,
            mode="direct_llm",
        )
        duration_ms = max(0, int(llm_trace.get("duration_ms") or 0))
        ended_at_ms = max(started_at_ms, started_at_ms + duration_ms)
        span_id = self._build_span_id(normalized_turn_id, "llm_call:direct")
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                parent_span_id=self._build_root_span_id(normalized_turn_id),
                node_type="llm_call",
                name="Main LLM call",
                status="completed",
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=duration_ms,
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await self._runtime_trace_store.upsert_llm_call(
            TraceLlmCallRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=normalized_turn_id,
                provider=str(llm_trace.get("provider") or "unknown"),
                model=str(llm_trace.get("model") or "unknown"),
                input_tokens=int(llm_trace.get("input_tokens") or 0),
                output_tokens=int(llm_trace.get("output_tokens") or 0),
                reasoning_tokens=int(llm_trace.get("reasoning_tokens") or 0),
                cache_read_tokens=int(llm_trace.get("cache_read_tokens") or 0),
                cache_write_tokens=int(llm_trace.get("cache_write_tokens") or 0),
                thinking_enabled=bool(llm_trace.get("thinking_enabled")),
            )
        )

    @staticmethod
    def _normalize_mode(mode: Any) -> str:
        return str(getattr(mode, "value", mode) or "unknown")
