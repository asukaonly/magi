"""Post-processing and side effects for chat execution results."""
from __future__ import annotations

import inspect
import json
import time
import uuid
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from ....core.logger import get_logger
from ....awareness.contracts import ActionEmissionRecord
from ....agent.runtime.contracts import FactRecord
from ....agent.trace import (
    now_wall_ms,
)
from ....chat import ChatMessageRecord, ChatProjector, ChatStore
from ....events.events import EventTypes
from ....personality.interaction_analyzer import analyze_interaction, DEFAULT_ANALYSIS
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
from .postprocess_components import ChatOutcomeWriter, ChatRuntimeNotifier
from .session_run_coordinator import TurnSupersession

if TYPE_CHECKING:
    from ....api.services.chat_trace_read_service import ChatTraceReadService

logger = get_logger(__name__)

TOOL_INTERACTION_EVENT_TYPE = "TOOL_INTERACTION"
CHAT_TOOL_LOOP_STEP_EVENT_TYPE = "CHAT_TOOL_LOOP_STEP"
MEMORY_QUERY_ACTIVE_TACTIC = "memory_query_active"
REPLAN_AFTER_TOOL_FAILURE_TACTIC = "replan_after_tool_failure"
TACTIC_TTL_SECONDS = 900


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
        unified_memory=None,
        max_fact_memory: int = 200,
        trace_read_service: "ChatTraceReadService | None" = None,
        runtime_trace_store: RuntimeTraceStore | None = None,
        chat_store: ChatStore | None = None,
        chat_projector: ChatProjector | None = None,
        complete_session_run: Callable[[str, str, int], Any] | None = None,
        resolve_session_run_status: Callable[[str, str, int], Any] | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._history_service = history_service
        self._get_action_emitter = get_action_emitter
        self._get_task_agent_manager = get_task_agent_manager
        self._get_sensor_hub = get_sensor_hub
        self._memory = memory
        self._unified_memory = unified_memory
        self._chat_store = chat_store
        self._local_fact_memory: list[FactRecord] = []
        self._max_fact_memory = max_fact_memory
        self._trace_read_service = trace_read_service
        self._runtime_trace_store = runtime_trace_store
        self._chat_outcome_writer = ChatOutcomeWriter(
            chat_store=chat_store,
            chat_projector=chat_projector,
            trace_id_factory=self._build_trace_id,
        )
        self._runtime_notifier = ChatRuntimeNotifier(runtime_trace_store=runtime_trace_store)
        self._started_turn_traces: set[str] = set()
        self._complete_session_run = complete_session_run
        self._resolve_session_run_status = resolve_session_run_status

    async def persist_turn_supersessions(
        self,
        *,
        superseded_turns: list[TurnSupersession],
        updated_at_ms: int,
    ) -> None:
        """Persist merged/interrupted turn states before new execution continues."""
        for superseded_turn in superseded_turns:
            await self._chat_outcome_writer.persist_turn_supersession(
                turn_id=superseded_turn.turn_id,
                anchor_turn_id=superseded_turn.anchor_turn_id,
                reason=superseded_turn.reason,
                updated_at_ms=updated_at_ms,
            )
            await self._persist_trace_supersession(
                turn_id=superseded_turn.turn_id,
                anchor_turn_id=superseded_turn.anchor_turn_id,
                reason=superseded_turn.reason,
                updated_at_ms=updated_at_ms,
            )

    async def handle(self, context: ChatRuntimeContext, result: ExecutionResult) -> ChatParseOutcome:
        action_emitter = self._get_action_emitter()
        latest_fact = context.latest_fact
        if not isinstance(latest_fact, FactRecord):
            return ChatParseOutcome(False, False, False, False)
        if context.incoming_fact_kind not in {
            IncomingFactKind.USER_MESSAGE,
            IncomingFactKind.WORKER_UPDATE,
            IncomingFactKind.EXPLORE_TASK_COMPLETED,
        }:
            return ChatParseOutcome(False, False, False, False)
        ux_plan = result.ux_plan if isinstance(result.ux_plan, dict) else {}

        if result.skip_emit:
            if await self._complete_turn_without_visible_response(
                context=context,
                result=result,
                latest_fact=latest_fact,
                ux_plan=ux_plan,
            ):
                return ChatParseOutcome(False, False, False, False)
            return ChatParseOutcome(False, False, False, False)
        if action_emitter is None:
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
            if await self._complete_turn_without_visible_response(
                context=context,
                result=result,
                latest_fact=latest_fact,
                ux_plan=ux_plan,
            ):
                return ChatParseOutcome(False, False, False, False)
            return ChatParseOutcome(False, False, False, False)

        if self._session_run_status(context) in {"cancelling", "cancelled"}:
            await self._finalize_session_run(context)
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
                response_text=response_text,
            )
        task_reflection_updated = await self._record_task_reflection(
            context=context,
            result=result,
            user_message=user_message,
            response_text=response_text,
        )
        memory_updated = memory_updated or task_reflection_updated

        # Bootstrap L2 extraction — runs only during early persona turns
        if user_message:
            await self._maybe_run_bootstrap_extraction(
                user_id=context.user_id,
                user_message=user_message,
                response_text=response_text,
            )

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

        await self._persist_final_chat_outcome(
            turn_id=turn_id,
            response_text=response_text,
            started_at_ms=started_at_ms,
            completed_at_ms=now_ms,
            orchestration_id=result.orchestration_id,
            execution_mode=self._normalize_mode(result.mode),
            ux_plan=ux_plan,
            run_id=context.session_run_id,
            run_revision=context.session_run_revision,
            run_disposition=context.session_run_disposition,
            reply_to_message_id=await self._resolve_result_reply_anchor_message_id(
                context=context,
                turn_id=turn_id,
            ),
        )
        await self._finalize_session_run(context)
        notification_message = await self._get_notification_chat_message(
            turn_id=turn_id,
            ux_plan=ux_plan,
        )
        notification_message_id = notification_message.message_id if notification_message is not None else None
        notification_message_kind = notification_message.message_kind if notification_message is not None else None
        notification_response_text = response_text
        if str((ux_plan or {}).get("assistant_surface_mode") or "").strip() == "reaction_only":
            notification_response_text = self._resolve_reaction_notification_text(ux_plan, fallback=response_text)
            notification_message_id = None
            notification_message_kind = "assistant_reaction"
        final_message = notification_message if notification_message and notification_message.message_kind == "assistant_final" else None
        await self._project_final_chat_message(context=context, final_message=final_message)

        if not getattr(result, "streamed", False):
            await self._emit_agent_response_notification(
                user_id=context.user_id,
                session_id=context.session_id,
                turn_id=turn_id,
                response_text=notification_response_text,
                orchestration_id=result.orchestration_id,
                trace_summary=trace_summary,
                trace_available=trace_available,
                ux_plan=result.ux_plan,
                message_id=notification_message_id,
                message_kind=notification_message_kind,
            )
        else:
            # Streaming turns skip agent_response; emit a completion control event so the
            # frontend knows the turn is done and can unlock the input.
            await self.emit_execution_control_notification(
                user_id=context.user_id,
                session_id=context.session_id,
                turn_id=turn_id,
                run_id=context.session_run_id,
                orchestration_id=result.orchestration_id,
                state="completed",
                can_cancel=False,
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

    async def _complete_turn_without_visible_response(
        self,
        *,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        latest_fact: FactRecord,
        ux_plan: dict[str, Any],
    ) -> bool:
        response_mode = str(ux_plan.get("assistant_surface_mode") or "").strip()
        if response_mode not in {"none", "reaction_only"}:
            return False
        turn_id = result.turn_id or self._resolve_turn_id(
            context,
            latest_fact.payload if isinstance(latest_fact.payload, dict) else {},
        )
        now_ms = now_wall_ms()
        started_at_ms = self._resolve_started_at_ms(result, latest_fact)
        await self._persist_final_chat_outcome(
            turn_id=turn_id,
            response_text="",
            started_at_ms=started_at_ms,
            completed_at_ms=now_ms,
            orchestration_id=result.orchestration_id,
            execution_mode=self._normalize_mode(result.mode),
            ux_plan=ux_plan,
            run_id=context.session_run_id,
            run_revision=context.session_run_revision,
            run_disposition=context.session_run_disposition,
            reply_to_message_id=await self._resolve_result_reply_anchor_message_id(
                context=context,
                turn_id=turn_id,
            ),
        )
        await self._finalize_session_run(context)
        return True

    async def _finalize_session_run(self, context: ChatRuntimeContext) -> None:
        if self._complete_session_run is None:
            return
        run_id = str(context.session_run_id or "").strip()
        if not run_id:
            return
        revision = int(context.session_run_revision or 0)
        try:
            completion = self._complete_session_run(
                context.session_id,
                run_id,
                revision,
            )
            if inspect.isawaitable(completion):
                await completion
        except Exception as exc:
            logger.warning(
                "Failed to complete chat session run",
                session_id=context.session_id,
                run_id=run_id,
                revision=revision,
                error=str(exc),
            )
            return
        status = self._session_run_status(context)
        if status == "cancelled":
            active_run = context.active_run
            await self.emit_execution_control_notification(
                user_id=context.user_id,
                session_id=context.session_id,
                turn_id=(
                    str((active_run.cancel_anchor_turn_id if active_run is not None else None) or "").strip()
                    or str((active_run.root_turn_id if active_run is not None else None) or "").strip()
                    or None
                ),
                run_id=run_id,
                orchestration_id=(
                    str(context.active_orchestrations[0].get("orchestration_id") or "").strip()
                    if context.active_orchestrations
                    and isinstance(context.active_orchestrations[0], dict)
                    else None
                ),
                state="cancelled",
                can_cancel=False,
                label="Run cancelled",
            )
        await self._notify_memory_session_end(context.session_id)

    async def _notify_memory_session_end(self, session_id: str | None) -> None:
        """Fire-and-forget L2 session-end review so memory can flush remaining
        staged events and reconcile all entities touched during the session."""
        if not session_id or self._unified_memory is None:
            return
        on_session_end = getattr(self._unified_memory, "on_session_end", None)
        if on_session_end is None:
            return
        try:
            await on_session_end(session_id)
        except Exception:
            logger.warning(
                "L2 session-end review failed",
                session_id=session_id,
                exc_info=True,
            )

    def _session_run_status(self, context: ChatRuntimeContext) -> str | None:
        if self._resolve_session_run_status is None:
            return None
        run_id = str(context.session_run_id or "").strip()
        if not run_id:
            return None
        revision = int(context.session_run_revision or 0)
        try:
            status = self._resolve_session_run_status(
                context.session_id,
                run_id,
                revision,
            )
            if inspect.isawaitable(status):
                return None
        except Exception as exc:
            logger.warning(
                "Failed to resolve chat session run status",
                session_id=context.session_id,
                run_id=run_id,
                revision=revision,
                error=str(exc),
            )
            return None
        normalized = str(status or "").strip()
        return normalized or None

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
        llm_trace = getattr(decision, "llm_trace", None)
        if isinstance(llm_trace, dict) and llm_trace:
            await self._runtime_trace_store.upsert_llm_call(
                TraceLlmCallRecord(
                    span_id=span_id,
                    trace_id=trace_id,
                    turn_id=turn_id,
                    provider=str(llm_trace.get("provider") or "unknown"),
                    model=str(llm_trace.get("model") or "unknown"),
                    input_tokens=int(llm_trace.get("input_tokens") or 0),
                    output_tokens=int(llm_trace.get("output_tokens") or 0),
                    reasoning_tokens=int(llm_trace.get("reasoning_tokens") or 0),
                    cache_read_tokens=int(llm_trace.get("cache_read_tokens") or 0),
                    cache_write_tokens=int(llm_trace.get("cache_write_tokens") or 0),
                    thinking_enabled=bool(llm_trace.get("thinking_enabled")),
                    request_preview=(context.latest_user_message or "")[:240] or None,
                    response_preview=str(getattr(decision, "intent", "") or "")[:240] or None,
                )
            )
        ux_plan = self._serialize_ux_plan(decision)
        await self._persist_turn_ux_plan(
            turn_id=turn_id,
            execution_mode=self._normalize_mode(getattr(decision, "execution_mode", None)),
            ux_plan=ux_plan,
            updated_at_ms=ended_at_ms,
            run_id=context.session_run_id,
            run_revision=context.session_run_revision,
            run_disposition=context.session_run_disposition,
        )
        turn_ux_message = await self._get_turn_ux_chat_message(
            turn_id=turn_id,
            ux_plan=ux_plan,
        )
        await self._emit_turn_ux_plan_notification(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
            ux_plan=ux_plan,
            message_id=turn_ux_message.message_id if turn_ux_message is not None else None,
            message_kind=turn_ux_message.message_kind if turn_ux_message is not None else None,
            timestamp_ms=turn_ux_message.created_at_ms if turn_ux_message is not None else None,
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
        if success and tool_name == "memory_query":
            await self._record_temporary_tactic(
                session_id=session_id,
                tactic_type=MEMORY_QUERY_ACTIVE_TACTIC,
                tactic_payload={
                    "tool_name": tool_name,
                    "turn_id": turn_id,
                    "iteration": payload.get("iteration"),
                    "intent": payload.get("intent"),
                    "arguments": arguments,
                },
                source_event_id=str(payload.get("tool_call_id") or turn_id or tool_name),
            )
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
        if stage == "iteration_all_tools_failed" and bool(payload.get("replan_allowed")):
            await self._record_temporary_tactic(
                session_id=session_id,
                tactic_type=REPLAN_AFTER_TOOL_FAILURE_TACTIC,
                tactic_payload={
                    "turn_id": turn_id,
                    "iteration": payload.get("iteration"),
                    "replan_allowed": True,
                    "consecutive_failed_iterations": payload.get("consecutive_failed_iterations"),
                    "tool_names": list(payload.get("tool_names") or []),
                },
                source_event_id=str(turn_id or stage),
            )
        runtime_payload = {
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
            "replan_allowed": payload.get("replan_allowed"),
            "consecutive_failed_iterations": payload.get("consecutive_failed_iterations"),
            "llm_trace": payload.get("llm_trace") if isinstance(payload.get("llm_trace"), dict) else None,
            "response_preview": payload.get("response_preview"),
            "intent": payload.get("intent"),
            "execution_agent_id": payload.get("execution_agent_id"),
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "timestamp": time.time(),
        }
        correlation_id = str(payload.get("tool_call_id") or str(uuid.uuid4()))
        action_emitter = self._get_action_emitter()
        if action_emitter is not None:
            await action_emitter.emit_runtime_event(
                event_type=CHAT_TOOL_LOOP_STEP_EVENT_TYPE,
                payload=runtime_payload,
                correlation_id=correlation_id,
                success=bool(payload.get("success", True)),
            )
        await self._emit_trace_update_notification(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )
        context_usage = payload.get("context_usage")
        if isinstance(context_usage, dict):
            await self._emit_context_usage_notification(
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                context_usage=context_usage,
            )

    async def _record_temporary_tactic(
        self,
        *,
        session_id: str,
        tactic_type: str,
        tactic_payload: dict[str, Any],
        source_event_id: str,
    ) -> None:
        l0_store = getattr(self._unified_memory, "l0", None)
        if l0_store is None:
            return
        await l0_store.add_temporary_tactic(
            session_id=session_id,
            scope_type="session",
            scope_id=session_id,
            tactic_type=tactic_type,
            tactic_payload=tactic_payload,
            source_event_ids=[source_event_id] if source_event_id else [],
            expires_at=time.time() + TACTIC_TTL_SECONDS,
            tactic_id=f"session:{session_id}:{tactic_type}",
        )

    async def _record_memory_updates(
        self, *, user_id: str, user_message: str, response_text: str = "",
    ) -> bool:
        # Collect STP rules so the analyzer can detect behavioral triggers.
        stp_rules: list[dict[str, str]] | None = None
        milestone_conditions: dict[str, str] | None = None
        if self._memory is not None:
            try:
                config = await self._memory.get_core_personality()
                if hasattr(config, "state_transition_protocol") and config.state_transition_protocol:
                    stp_rules = []
                    for item in config.state_transition_protocol:
                        tt = getattr(item, "trigger_type", "")
                        cond = getattr(item, "trigger_condition", "")
                        if tt and cond:
                            stp_rules.append({"trigger_type": tt, "trigger_condition": cond})
                if hasattr(config, "milestone_conditions") and config.milestone_conditions:
                    milestone_conditions = config.milestone_conditions
            except Exception:
                pass

        analysis = await analyze_interaction(
            user_message, response_text,
            stp_rules=stp_rules,
            milestone_conditions=milestone_conditions,
        )

        updated = False
        if self._memory is not None:
            try:
                updated = await self._memory.process_turn_outcome(
                    user_id=user_id,
                    user_message=user_message,
                    analysis=analysis,
                    stp_rules=stp_rules,
                    milestone_conditions=milestone_conditions,
                )
            except Exception as exc:
                logger.warning("Failed to process turn outcome: %s", exc)

        return updated

    async def _maybe_run_bootstrap_extraction(
        self, *, user_id: str, user_message: str, response_text: str,
    ) -> None:
        """Run L2 user-info extraction if the persona is still bootstrapping."""
        if self._memory is None or self._unified_memory is None:
            return
        growth_engine = getattr(self._memory, "_growth_engine", None)
        if growth_engine is None:
            return
        l2_store = getattr(self._unified_memory, "l2", None)
        try:
            from ....personality.bootstrap_service import maybe_extract_bootstrap_info
            await maybe_extract_bootstrap_info(
                growth_engine=growth_engine,
                l2_store=l2_store,
                persona_name=self._memory.personality_name,
                persona_id=self._memory.persona_id,
                user_id=user_id,
                user_message=user_message,
                assistant_response=response_text,
            )
        except Exception as exc:
            logger.debug("Bootstrap extraction skipped: %s", exc)

    def _resolve_turn_id(self, context: ChatRuntimeContext, payload: dict[str, Any]) -> str | None:
        latest_payload = context.latest_payload
        typed_turn_id = str(getattr(latest_payload, "turn_id", "") or "").strip()
        if typed_turn_id:
            return typed_turn_id
        raw_turn_id = str(payload.get("turn_id") or "").strip()
        return raw_turn_id or None

    async def _persist_turn_ux_plan(
        self,
        *,
        turn_id: str,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        updated_at_ms: int,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
    ) -> None:
        await self._chat_outcome_writer.persist_turn_ux_plan(
            turn_id=turn_id,
            execution_mode=execution_mode,
            ux_plan=ux_plan,
            updated_at_ms=updated_at_ms,
            run_id=run_id,
            run_revision=run_revision,
            run_disposition=run_disposition,
        )

    async def _persist_final_chat_outcome(
        self,
        *,
        turn_id: str | None,
        response_text: str,
        started_at_ms: int,
        completed_at_ms: int,
        orchestration_id: str | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        reply_to_message_id: str | None = None,
    ) -> None:
        await self._chat_outcome_writer.persist_final_chat_outcome(
            turn_id=turn_id,
            orchestration_id=orchestration_id,
            execution_mode=execution_mode,
            ux_plan=ux_plan,
            response_text=response_text,
            started_at_ms=started_at_ms,
            completed_at_ms=completed_at_ms,
            run_id=run_id,
            run_revision=run_revision,
            run_disposition=run_disposition,
            reply_to_message_id=reply_to_message_id,
        )

    async def _resolve_result_reply_anchor_message_id(
        self,
        *,
        context: ChatRuntimeContext,
        turn_id: str | None,
    ) -> str | None:
        normalized_turn_id = str(turn_id or "").strip()
        if self._chat_store is None or not normalized_turn_id:
            return None
        if context.incoming_fact_kind not in {
            IncomingFactKind.WORKER_UPDATE,
            IncomingFactKind.EXPLORE_TASK_COMPLETED,
        }:
            return None
        turn = await self._chat_store.get_turn(normalized_turn_id)
        anchor_turn_id = str(
            (turn.response_anchor_turn_id if turn is not None else normalized_turn_id) or normalized_turn_id
        ).strip()
        if not anchor_turn_id:
            return None
        anchor_message = await self._chat_store.get_latest_message_for_turn(
            anchor_turn_id,
            message_kind="user_text",
        )
        if anchor_message is None:
            return None
        return anchor_message.message_id

    async def _get_chat_message(
        self,
        *,
        turn_id: str | None,
        message_kind: str,
    ) -> ChatMessageRecord | None:
        return await self._chat_outcome_writer.get_chat_message(
            turn_id=turn_id,
            message_kind=message_kind,
        )

    async def _get_final_chat_message(self, turn_id: str | None) -> ChatMessageRecord | None:
        return await self._get_chat_message(
            turn_id=turn_id,
            message_kind="assistant_final",
        )

    async def _get_notification_chat_message(
        self,
        *,
        turn_id: str | None,
        ux_plan: dict[str, Any] | None,
    ) -> ChatMessageRecord | None:
        return await self._chat_outcome_writer.get_notification_chat_message(
            turn_id=turn_id,
            ux_plan=ux_plan,
        )

    async def _get_turn_ux_chat_message(
        self,
        *,
        turn_id: str | None,
        ux_plan: dict[str, Any] | None,
    ) -> ChatMessageRecord | None:
        return await self._chat_outcome_writer.get_turn_ux_chat_message(
            turn_id=turn_id,
            ux_plan=ux_plan,
        )

    @staticmethod
    def _resolve_reaction_text(ux_plan: dict[str, Any] | None) -> str:
        return ChatOutcomeWriter.resolve_reaction_text(ux_plan)

    async def _project_final_chat_message(
        self,
        *,
        context: ChatRuntimeContext,
        final_message: ChatMessageRecord | None,
    ) -> None:
        await self._chat_outcome_writer.project_final_chat_message(
            user_id=context.user_id,
            session_id=context.session_id,
            final_message=final_message,
        )

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
        continued_from_turn_id, continued_from_trace_id = await self._resolve_trace_continuation(
            anchor_turn_id=turn_id
        )
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
                continued_from_turn_id=continued_from_turn_id,
                continued_from_trace_id=continued_from_trace_id,
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

    async def _resolve_trace_continuation(
        self,
        *,
        anchor_turn_id: str,
    ) -> tuple[str | None, str | None]:
        if self._chat_store is None:
            return (None, None)
        previous_turn = await self._chat_store.get_latest_superseded_turn(anchor_turn_id=anchor_turn_id)
        if previous_turn is None:
            return (None, None)
        trace_id = str(previous_turn.trace_id or self._build_trace_id(previous_turn.turn_id)).strip() or None
        return (previous_turn.turn_id, trace_id)

    async def _persist_trace_supersession(
        self,
        *,
        turn_id: str,
        anchor_turn_id: str,
        reason: str,
        updated_at_ms: int,
    ) -> None:
        if self._runtime_trace_store is None:
            return
        existing_turn = await self._runtime_trace_store.get_turn(turn_id)
        if existing_turn is None:
            return
        status = "merged" if reason == "augment" else "interrupted"
        started_at_ms = int(existing_turn.started_at_ms or updated_at_ms)
        ended_at_ms = max(updated_at_ms, started_at_ms)
        await self._runtime_trace_store.upsert_turn(
            TraceTurnRecord(
                trace_id=existing_turn.trace_id,
                turn_id=existing_turn.turn_id,
                session_id=existing_turn.session_id,
                user_id=existing_turn.user_id,
                status=status,
                mode=existing_turn.mode,
                orchestration_id=existing_turn.orchestration_id,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=max(0, ended_at_ms - started_at_ms),
                user_message_preview=existing_turn.user_message_preview,
                response_preview=existing_turn.response_preview,
                error_summary=existing_turn.error_summary,
                run_id=existing_turn.run_id,
                run_revision=existing_turn.run_revision,
                continued_from_turn_id=existing_turn.continued_from_turn_id,
                continued_from_trace_id=existing_turn.continued_from_trace_id,
                superseded_by_turn_id=anchor_turn_id,
                supersession_reason=status,
                created_at_ms=int(existing_turn.created_at_ms or started_at_ms),
                updated_at_ms=ended_at_ms,
            )
        )
        root_span = await self._runtime_trace_store.get_span(self._build_root_span_id(turn_id))
        if root_span is None:
            return
        await self._runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=root_span.span_id,
                trace_id=root_span.trace_id,
                turn_id=root_span.turn_id,
                parent_span_id=root_span.parent_span_id,
                node_type=root_span.node_type,
                name=root_span.name,
                status=status,
                attempt_index=root_span.attempt_index,
                retry_count=root_span.retry_count,
                iteration=root_span.iteration,
                execution_agent_id=root_span.execution_agent_id,
                result_preview=root_span.result_preview,
                error_text=root_span.error_text,
                run_id=root_span.run_id,
                run_revision=root_span.run_revision,
                started_at_ms=int(root_span.started_at_ms or started_at_ms),
                ended_at_ms=ended_at_ms,
                duration_ms=max(0, ended_at_ms - int(root_span.started_at_ms or started_at_ms)),
                created_at_ms=int(root_span.created_at_ms or started_at_ms),
                updated_at_ms=ended_at_ms,
            )
        )

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
        message_id: str | None,
        message_kind: str | None,
    ) -> None:
        await self._runtime_notifier.emit_agent_response(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            response_text=response_text,
            orchestration_id=orchestration_id,
            trace_summary=trace_summary,
            trace_available=trace_available,
            ux_plan=ux_plan,
            message_id=message_id,
            message_kind=message_kind,
        )

    async def _emit_turn_ux_plan_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        ux_plan: dict[str, Any] | None,
        message_id: str | None,
        message_kind: str | None,
        timestamp_ms: int | None,
    ) -> None:
        await self._runtime_notifier.emit_turn_ux_plan(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            ux_plan=ux_plan,
            message_id=message_id,
            message_kind=message_kind,
            timestamp_ms=timestamp_ms,
        )

    async def _emit_trace_update_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
    ) -> None:
        trace_summary: dict[str, Any] | None = None
        if self._trace_read_service and turn_id:
            try:
                trace_summary = await self._trace_read_service.aget_trace_summary(
                    user_id=user_id,
                    session_id=session_id,
                    turn_id=turn_id,
                )
            except Exception:
                pass
        await self._runtime_notifier.emit_trace_update(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            trace_summary=trace_summary,
        )

    async def _emit_context_usage_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        context_usage: dict[str, Any],
    ) -> None:
        await self._runtime_notifier.emit_context_usage(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            context_usage=context_usage,
        )

    async def emit_execution_control_notification(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        run_id: str | None,
        orchestration_id: str | None,
        state: str,
        can_cancel: bool,
        label: str | None = None,
    ) -> None:
        await self._runtime_notifier.emit_execution_control(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            run_id=run_id,
            orchestration_id=orchestration_id,
            state=state,
            can_cancel=can_cancel,
            label=label,
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
    def _resolve_reaction_notification_text(
        ux_plan: dict[str, Any] | None,
        *,
        fallback: str,
    ) -> str:
        reaction_text = ChatOutcomeWriter.resolve_reaction_text(ux_plan)
        return reaction_text or fallback

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
                request_preview=str(llm_trace.get("request_preview") or "")[:240] or None,
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
                request_preview=(user_message or "")[:240] or None,
            )
        )

    @staticmethod
    def _normalize_mode(mode: Any) -> str:
        return str(getattr(mode, "value", mode) or "unknown")
