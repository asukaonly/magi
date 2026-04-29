"""Post-processing and side effects for chat execution results."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, TYPE_CHECKING

from ....core.logger import get_logger
from ....agent.runtime.contracts import FactRecord
from ....agent.trace import (
    now_wall_ms,
)
from ....chat import ChatProjector, ChatStore
from ....events.events import EventTypes
from ....runtime_trace import (
    RuntimeTraceStore,
)
from ..common import (
    ExecutionResult,
    FunctionCallingExecutionResult,
    IncomingFactKind,
)
from .contracts import ChatParseOutcome, ChatRuntimeContext
from .history_service import ChatHistoryService
from .postprocess_background import ChatPostprocessBackgroundMixin
from .postprocess_components import ChatOutcomeWriter, ChatRuntimeNotifier
from .postprocess_intent import ChatPostprocessIntentMixin
from .postprocess_memory import ChatPostprocessMemoryMixin
from .postprocess_outcomes import ChatPostprocessOutcomeMixin
from .postprocess_session import ChatPostprocessSessionMixin
from .postprocess_tool_events import ChatPostprocessToolEventMixin
from .postprocess_trace import ChatPostprocessTraceMixin
from .session_run_coordinator import TurnSupersession

if TYPE_CHECKING:
    from ....api.services.chat_trace_read_service import ChatTraceReadService

logger = get_logger(__name__)


def _default_chat_read_service_factory() -> Any:
    from ....chat import get_chat_read_service

    return get_chat_read_service()


class ChatPostProcessService(
    ChatPostprocessTraceMixin,
    ChatPostprocessBackgroundMixin,
    ChatPostprocessSessionMixin,
    ChatPostprocessToolEventMixin,
    ChatPostprocessOutcomeMixin,
    ChatPostprocessMemoryMixin,
    ChatPostprocessIntentMixin,
):
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
        self._chat_read_service_factory = (
            chat_read_service_factory or _default_chat_read_service_factory
        )
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

    async def handle(
        self, context: ChatRuntimeContext, result: ExecutionResult
    ) -> ChatParseOutcome:
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
            elif (
                isinstance(execution_outcome, dict)
                and execution_outcome.get("status") == "detached"
            ):
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
        turn_id = result.turn_id or self._resolve_turn_id(
            context, latest_fact.payload if isinstance(latest_fact.payload, dict) else {}
        )
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
        notification_message_id = (
            notification_message.message_id if notification_message is not None else None
        )
        notification_message_kind = (
            notification_message.message_kind if notification_message is not None else None
        )
        notification_response_text = response_text
        if str((ux_plan or {}).get("assistant_surface_mode") or "").strip() == "reaction_only":
            notification_response_text = self._resolve_reaction_notification_text(
                ux_plan, fallback=response_text
            )
            notification_message_id = None
            notification_message_kind = "assistant_reaction"
        final_message = (
            notification_message
            if notification_message and notification_message.message_kind == "assistant_final"
            else None
        )
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

    def _resolve_turn_id(self, context: ChatRuntimeContext, payload: dict[str, Any]) -> str | None:
        latest_payload = context.latest_payload
        typed_turn_id = str(getattr(latest_payload, "turn_id", "") or "").strip()
        if typed_turn_id:
            return typed_turn_id
        raw_turn_id = str(payload.get("turn_id") or "").strip()
        return raw_turn_id or None
