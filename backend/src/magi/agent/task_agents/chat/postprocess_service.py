"""Post-processing and side effects for chat execution results."""
from __future__ import annotations

import asyncio
import inspect
import json
import time
import uuid
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from ....core.logger import get_logger
from ....agent.runtime.contracts import FactRecord
from ....agent.trace import (
    now_wall_ms,
)
from ....chat import ChatMessageRecord, ChatProjector, ChatStore
from ....events.events import EventTypes
from ....personality.feature_flags import get_personality_feature_flags
from ....personality.interaction_analyzer import analyze_interaction, DEFAULT_ANALYSIS
from ....memory.l3.models import TaskOutcomePacket
from ....runtime_trace import (
    RuntimeTraceStore,
    TraceIntentResolutionRecord,
    TraceLlmCallRecord,
    TraceSpanRecord,
)
from ..common import ExecutionMode, ExecutionResult, FunctionCallingExecutionResult, IncomingFactKind
from ..explore.constants import EXPLORE_TASK_COMPLETED
from .contracts import ChatParseOutcome, ChatRuntimeContext
from .fact_classifier import WORKER_AGENT_EVENT_TYPES
from .history_service import ChatHistoryService
from .postprocess_constants import (
    CHAT_TOOL_LOOP_STEP_EVENT_TYPE,
    MEMORY_QUERY_ACTIVE_TACTIC,
    REPLAN_AFTER_TOOL_FAILURE_TACTIC,
    TACTIC_TTL_SECONDS,
    TOOL_INTERACTION_EVENT_TYPE,
)
from .postprocess_components import ChatOutcomeWriter, ChatRuntimeNotifier
from .postprocess_trace import ChatPostprocessTraceMixin
from .session_run_coordinator import TurnSupersession
from ...background.contracts import BackgroundTask, BackgroundTaskStatus

if TYPE_CHECKING:
    from ....api.services.chat_trace_read_service import ChatTraceReadService

logger = get_logger(__name__)


def _default_chat_read_service_factory() -> Any:
    from ....chat import get_chat_read_service

    return get_chat_read_service()


class ChatPostProcessService(ChatPostprocessTraceMixin):
    """Applies side effects for chat execution results."""

    def __init__(
        self,
        *,
        agent_id: str,
        history_service: ChatHistoryService,
        get_event_emitter: Callable[[], Any],
        get_task_agent_manager: Callable[[], Any | None],
        get_sensor_hub: Callable[[], Any | None],
        memory=None,
        unified_memory=None,
        max_fact_memory: int = 200,
        trace_read_service: "ChatTraceReadService | None" = None,
        runtime_trace_store: RuntimeTraceStore | None = None,
        chat_store: ChatStore | None = None,
        chat_projector: ChatProjector | None = None,
        chat_read_service_factory: Callable[[], Any] | None = None,
        complete_session_run: Callable[[str, str, int], Any] | None = None,
        resolve_session_run_status: Callable[[str, str, int], Any] | None = None,
        drain_deferred_turns: Callable[[str], Any] | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._history_service = history_service
        self._get_event_emitter = get_event_emitter
        self._get_task_agent_manager = get_task_agent_manager
        self._get_sensor_hub = get_sensor_hub
        self._memory = memory
        self._unified_memory = unified_memory
        self._chat_store = chat_store
        self._local_fact_memory: list[FactRecord] = []
        self._max_fact_memory = max_fact_memory
        self._trace_read_service = trace_read_service
        self._chat_read_service_factory = chat_read_service_factory or _default_chat_read_service_factory
        self._runtime_trace_store = runtime_trace_store
        self._chat_outcome_writer = ChatOutcomeWriter(
            chat_store=chat_store,
            chat_projector=chat_projector,
            trace_id_factory=self._build_trace_id,
        )
        self._runtime_notifier = ChatRuntimeNotifier(
            runtime_trace_store=runtime_trace_store,
            chat_read_service_factory=self._chat_read_service_factory,
        )
        self._started_turn_traces: set[str] = set()
        self._complete_session_run = complete_session_run
        self._resolve_session_run_status = resolve_session_run_status
        self._drain_deferred_turns = drain_deferred_turns
        # Track in-flight background memory-update tasks so they are not
        # garbage collected mid-flight. Entries remove themselves on done.
        self._background_tasks: set[asyncio.Task[Any]] = set()

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

    async def deliver_background_task_completion(
        self,
        task: BackgroundTask,
        *,
        summary_max_chars: int = 1000,
    ) -> ChatMessageRecord | None:
        """Persist a system message announcing a background task's outcome.

        The message lands in ``task.spec.session_id`` so the chat UI surfaces
        the completion inline with the conversation. Returns the persisted
        record, or ``None`` when there is no chat store wired or the task
        spec lacks a routable session.

        ``task.summary`` is used verbatim for ``SUCCEEDED`` outcomes (capped
        at ``summary_max_chars``); ``FAILED`` and ``CANCELLED`` use
        ``task.error`` and ``task.cancel_reason`` respectively. The full
        result payload stays on the background task record itself.
        """
        if self._chat_store is None:
            return None
        spec = task.spec
        session_id = str(spec.session_id or "").strip()
        user_id = str(spec.user_id or "").strip()
        if not session_id or not user_id:
            return None

        title = (spec.title or "").strip() or "Background task"
        if task.status is BackgroundTaskStatus.FAILED:
            reason = (task.error or "").strip() or "unknown error"
            body = f"Background task failed: {reason}"
        elif task.status is BackgroundTaskStatus.CANCELLED:
            reason = (task.cancel_reason or "").strip() or "cancelled"
            body = f"Background task cancelled: {reason}"
        else:
            body = (task.summary or "").strip() or "(no summary)"
        if len(body) > summary_max_chars:
            body = body[:summary_max_chars].rstrip() + "..."
        content_text = f"[Background task] {title}\n{body}"

        payload = {
            "background_task_id": task.task_id,
            "background_task_status": task.status.value,
            "background_task_title": title,
            "background_task_attempt": int(task.attempt_index),
        }
        finished_at = task.finished_at if task.finished_at is not None else task.updated_at
        completed_at_ms = int(finished_at * 1000) if finished_at else now_wall_ms()

        record = ChatMessageRecord(
            message_id=f"msg_{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            turn_id=None,
            user_id=user_id,
            role="system",
            message_kind="background_task_completion",
            content_text=content_text,
            payload_json=json.dumps(payload, ensure_ascii=False),
            is_final=True,
            is_visible=True,
            created_at_ms=completed_at_ms,
            sequence_no=await self._chat_store.next_sequence_no(session_id=session_id),
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
        await self._chat_store.append_message(record)
        await self._chat_store.bump_history_version(session_id)
        return record

    async def handle(self, context: ChatRuntimeContext, result: ExecutionResult) -> ChatParseOutcome:
        event_emitter = self._get_event_emitter()
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
        if event_emitter is None:
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
            elif isinstance(execution_outcome, dict) and execution_outcome.get("status") == "detached":
                # A detached outcome reaches postprocess only when the
                # background hand-off declined or failed. Surface that so
                # the user does not silently lose the turn.
                response_text = "Failed to move this task to the background."
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

        # Schedule memory/reflection updates as a background task so they do not
        # delay AI_RESPONSE emission. These updates only affect future turns
        # (persona emotion, relationship profile, milestones, task reflection)
        # and the currently emitted response does not depend on them.
        memory_updated = False
        if user_message:
            self._schedule_background_memory_updates(
                user_id=context.user_id,
                user_message=user_message,
                response_text=response_text,
                context=context,
                result=result,
            )
            memory_updated = True

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
            attachments=list(getattr(result, "attachments", []) or []),
            message_payload=dict(getattr(result, "message_payload", {}) or {}),
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
        if getattr(result, "streamed", False) and final_message is not None:
            await self._runtime_notifier.emit_chat_message_upsert(
                user_id=context.user_id,
                session_id=context.session_id,
                message_id=final_message.message_id,
            )

        if not getattr(result, "streamed", False):
            await self._emit_agent_response_notification(
                user_id=context.user_id,
                session_id=context.session_id,
                turn_id=turn_id,
                response_text=notification_response_text,
                attachments=list(getattr(result, "attachments", []) or []),
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

        await event_emitter.emit_chat_response_event(
            user_id=context.user_id,
            session_id=context.session_id,
            response=response_text,
            correlation_id=correlation_id,
            turn_id=turn_id,
            orchestration_id=result.orchestration_id,
            trace_summary=trace_summary,
            trace_available=trace_available,
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
        await self._drain_deferred_user_turns(context)
        await self._notify_memory_session_end(context.session_id)

    async def _drain_deferred_user_turns(self, context: ChatRuntimeContext) -> None:
        """Re-inject DEFER pending turns as new user messages after turn completion.

        AUGMENT turns are merged mid-run at the tool-loop checkpoint. DEFER
        turns must wait until the active run is finalized and then start a
        fresh run, so we dispatch them back through the runtime command queue
        as brand-new user messages.
        """
        if self._drain_deferred_turns is None:
            return
        session_id = str(context.session_id or "").strip()
        if not session_id:
            return
        try:
            result = self._drain_deferred_turns(session_id)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning(
                "Failed to drain deferred user turns",
                session_id=session_id,
                error=str(exc),
            )

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
                selected_tools_json=self._serialize_selected_tools_payload(
                    router_tools=list(getattr(decision, "tools", []) or []),
                    selected_tools=list(getattr(decision, "tools", []) or []),
                    task_hint=getattr(decision, "task_hint", None),
                    recommended_tools=list(getattr(decision, "recommended_tools", []) or []),
                ),
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

    async def record_tool_selection(self, context: ChatRuntimeContext, decision: Any, tool_selection: Any) -> None:
        latest_fact = context.latest_fact
        if self._runtime_trace_store is None or not isinstance(latest_fact, FactRecord):
            return
        turn_id = self._resolve_turn_id(context, latest_fact.payload if isinstance(latest_fact.payload, dict) else {})
        if not turn_id:
            return
        span_id = self._build_span_id(turn_id, "intent_resolution")
        trace_id = self._build_trace_id(turn_id)
        await self._runtime_trace_store.upsert_intent_resolution(
            TraceIntentResolutionRecord(
                span_id=span_id,
                trace_id=trace_id,
                turn_id=turn_id,
                intent=str(getattr(decision, "intent", "") or ""),
                execution_mode=self._normalize_mode(getattr(decision, "execution_mode", None)),
                route_reason=str(getattr(decision, "reasoning", "") or "") or None,
                selected_tools_json=self._serialize_selected_tools_payload(
                    router_tools=list(getattr(decision, "tools", []) or []),
                    selected_tools=list(getattr(tool_selection, "tools", []) or []),
                    task_hint=getattr(tool_selection, "task_hint", None) or getattr(decision, "task_hint", None),
                    recommended_tools=list(getattr(tool_selection, "recommended_tools", []) or []),
                ),
                selected_worker_type=(
                    str(getattr(getattr(decision, "orchestration_plan", None), "default_leaf_type", "") or "")
                    or None
                ),
            )
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
        result_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        self._history_service.store_tool_interaction(
            history_key,
            {
                "timestamp": time.time(),
                "intent": payload.get("intent") or "unknown",
                "tool_name": str(payload.get("tool_name") or "unknown"),
                "status": "success" if bool(payload.get("success")) else "error",
                "error_code": str(payload.get("error_code") or ""),
                "error_message": str(payload.get("error") or ""),
                "result_summary": self._summarize_tool_result(result_data),
                "result_data": result_data,
                "turn_id": turn_id,
            },
        )

        event_emitter = self._get_event_emitter()
        if event_emitter is None:
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
        await event_emitter.emit_runtime_event(
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

    @staticmethod
    def _summarize_tool_result(result_data: dict[str, Any]) -> str:
        if not isinstance(result_data, dict) or not result_data:
            return ""

        summary = str(result_data.get("summary") or "").strip()
        if summary:
            return summary

        historical_recall = result_data.get("historical_recall")
        if isinstance(historical_recall, dict):
            recall_summary = str(historical_recall.get("summary") or "").strip()
            if recall_summary:
                return recall_summary
            status = str(historical_recall.get("status") or "").strip()
            if status:
                return f"historical_recall status={status}"

        resolved_count = result_data.get("resolved_count")
        if isinstance(resolved_count, int):
            return f"Resolved {resolved_count} asset(s)."

        chat_attachments = result_data.get("chat_attachments")
        if isinstance(chat_attachments, list):
            return f"Prepared {len(chat_attachments)} chat attachment(s)."

        asset_refs = result_data.get("asset_refs")
        if isinstance(asset_refs, list):
            return f"Returned {len(asset_refs)} asset ref(s)."

        return ""

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
        event_emitter = self._get_event_emitter()
        if event_emitter is not None:
            await event_emitter.emit_runtime_event(
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

    def _schedule_background_memory_updates(
        self,
        *,
        user_id: str,
        user_message: str,
        response_text: str,
        context: ChatRuntimeContext,
        result: ExecutionResult,
    ) -> None:
        """Run memory/reflection updates off the AI_RESPONSE critical path.

        These updates persist relationship profile, emotional state, persona
        milestones, direct-chat STP triggers, and (for worker/explore turns)
        task reflection summaries. None of them influence the response that
        is about to be emitted; they only shape future turns, so they are safe
        to run after AI_RESPONSE is published.
        """

        async def _runner() -> None:
            t0 = time.monotonic()
            try:
                if user_message:
                    await self._record_memory_updates(
                        user_id=user_id,
                        user_message=user_message,
                        response_text=response_text,
                        allow_state_transition=self._allows_state_transition(context=context, result=result),
                        incoming_fact_kind=self._enum_value(context.incoming_fact_kind),
                        execution_mode=self._enum_value(result.mode),
                        session_id=context.session_id,
                        turn_id=result.turn_id,
                    )
                await self._record_task_reflection(
                    context=context,
                    result=result,
                    user_message=user_message,
                    response_text=response_text,
                )
            except Exception:
                logger.exception(
                    "Background memory update failed user_id=%s session_id=%s",
                    user_id,
                    context.session_id,
                )
            finally:
                logger.info(
                    "[chat.handle] background memory updates finished elapsed_ms=%.1f",
                    (time.monotonic() - t0) * 1000,
                )

        task = asyncio.create_task(
            _runner(),
            name=f"chat-memory-updates:{context.session_id}",
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _record_memory_updates(
        self,
        *,
        user_id: str,
        user_message: str,
        response_text: str = "",
        allow_state_transition: bool = True,
        incoming_fact_kind: str | None = None,
        execution_mode: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> bool:
        features = get_personality_feature_flags()
        if not (
            features.state_memory_enabled
            or features.state_transition_enabled
            or features.deep_persona_enabled
        ):
            return False

        effective_state_transition = bool(allow_state_transition and features.state_transition_enabled)
        logger.info(
            "[chat.memory] interaction analysis scope user_id=%s session_id=%s turn_id=%s "
            "incoming_fact_kind=%s execution_mode=%s state_transition_enabled=%s",
            user_id,
            session_id,
            turn_id,
            incoming_fact_kind,
            execution_mode,
            effective_state_transition,
        )

        # Collect STP rules so the analyzer can detect behavioral triggers.
        stp_rules: list[dict[str, str]] | None = None
        milestone_conditions: dict[str, str] | None = None
        if self._memory is not None:
            try:
                config = await self._memory.get_core_personality()
                if (
                    effective_state_transition
                    and hasattr(config, "state_transition_protocol")
                    and config.state_transition_protocol
                ):
                    stp_rules = []
                    for item in config.state_transition_protocol:
                        tt = getattr(item, "trigger_type", "")
                        cond = getattr(item, "trigger_condition", "")
                        if tt and cond:
                            stp_rules.append({"trigger_type": tt, "trigger_condition": cond})
                if (
                    features.deep_persona_enabled
                    and hasattr(config, "milestone_conditions")
                    and config.milestone_conditions
                ):
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
                    allow_state_transition=effective_state_transition,
                )
            except Exception as exc:
                logger.warning("Failed to process turn outcome: %s", exc)

        return updated

    @staticmethod
    def _allows_state_transition(
        *,
        context: ChatRuntimeContext,
        result: ExecutionResult,
    ) -> bool:
        return (
            context.incoming_fact_kind == IncomingFactKind.USER_MESSAGE
            and result.mode == ExecutionMode.DIRECT_LLM
        )

    @staticmethod
    def _enum_value(value: Any) -> str:
        return str(getattr(value, "value", value) or "")

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
        attachments: list[dict[str, Any]] | None = None,
        message_payload: dict[str, Any] | None = None,
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
            attachments=attachments,
            message_payload=message_payload,
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

    @staticmethod
    def _serialize_selected_tools_payload(
        *,
        router_tools: list[str],
        selected_tools: list[str],
        task_hint: Any,
        recommended_tools: list[dict[str, Any]],
    ) -> str:
        return json.dumps(
            {
                "router_tools": list(router_tools or []),
                "selected_tools": list(selected_tools or []),
                "task_hint": dict(task_hint or {}),
                "recommended_tools": list(recommended_tools or []),
            },
            ensure_ascii=False,
        )

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
