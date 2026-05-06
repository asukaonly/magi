"""Post-processing and side effects for chat execution results."""

from __future__ import annotations

import asyncio
import json
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
from .postprocess.background import ChatPostprocessBackgroundMixin
from .postprocess.components import ChatOutcomeWriter, ChatRuntimeNotifier
from .postprocess.intent import ChatPostprocessIntentMixin
from .postprocess.memory import ChatPostprocessMemoryMixin
from .postprocess.outcomes import ChatPostprocessOutcomeMixin
from .postprocess.session import ChatPostprocessSessionMixin
from .postprocess.tool_events import ChatPostprocessToolEventMixin
from .postprocess.trace import ChatPostprocessTraceMixin
from .session_run_coordinator import TurnSupersession

if TYPE_CHECKING:
    from ....api.services.chat_trace.read_service import ChatTraceReadService

logger = get_logger(__name__)


def _default_chat_read_service_factory() -> Any:
    from ....chat import get_chat_read_service

    return get_chat_read_service()


class ChatPostProcessService:
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
        response_rhythm_planner: Any | None = None,
        transcript_summarizer: Any | None = None,
        event_bus: Any | None = None,
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
        self._event_bus = event_bus
        self._operations = _ChatPostProcessOperations(self)
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
        self._response_rhythm_planner = response_rhythm_planner
        self._transcript_summarizer = transcript_summarizer
        # Track in-flight background memory-update tasks so they are not
        # garbage collected mid-flight. Entries remove themselves on done.
        self._background_tasks: set[asyncio.Task[Any]] = set()

    def __getattr__(self, name: str) -> Any:
        operations = self.__dict__.get("_operations")
        if operations is not None:
            try:
                return object.__getattribute__(operations, name)
            except AttributeError:
                pass
        raise AttributeError(f"{type(self).__name__!s} object has no attribute {name!r}")

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

        correlation_id = result.correlation_id or latest_fact.correlation_id
        turn_id = result.turn_id or self._resolve_turn_id(
            context, latest_fact.payload if isinstance(latest_fact.payload, dict) else {}
        )
        started_at_ms = self._resolve_started_at_ms(result, latest_fact)
        rhythm_started_at_ms = now_wall_ms()
        response_plan = await self._build_response_rhythm_plan(
            context=context,
            result=result,
            response_text=response_text,
            ux_plan=ux_plan,
        )
        rhythm_ended_at_ms = now_wall_ms()
        if response_plan is not None:
            result.response_plan = response_plan

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

        now_ms = now_wall_ms()

        await self._emit_result_llm_trace(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
            llm_trace=getattr(result, "llm_trace", {}),
            started_at_ms=started_at_ms,
            user_message=context.latest_user_message,
        )
        if response_plan is not None:
            await self._emit_response_rhythm_trace(
                user_id=context.user_id,
                session_id=context.session_id,
                turn_id=turn_id,
                response_text=response_text,
                response_plan=response_plan,
                started_at_ms=rhythm_started_at_ms,
                ended_at_ms=rhythm_ended_at_ms,
                mode=self._normalize_mode(result.mode),
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

        reply_anchor_message_id = await self._resolve_result_reply_anchor_message_id(
            context=context,
            turn_id=turn_id,
        )
        segmented_messages = []
        if response_plan is not None:
            segmented_messages = await self._persist_segmented_chat_outcome(
                turn_id=turn_id,
                response_plan=response_plan,
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
                reply_to_message_id=reply_anchor_message_id,
                persona_id=context.active_persona_id,
            )
            if not segmented_messages:
                response_plan = None
                result.response_plan = None

        if response_plan is None:
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
                reply_to_message_id=reply_anchor_message_id,
                persona_id=context.active_persona_id,
            )
        await self._finalize_session_run(context)
        self._schedule_transcript_summary_update(context)

        if response_plan is not None:
            await self._project_canonical_assistant_response(
                context=context,
                turn_id=turn_id,
                message_id=segmented_messages[0].message_id if segmented_messages else None,
                response_text=response_text,
                created_at_ms=now_ms,
            )
            await self._emit_segmented_agent_response_notifications(
                context=context,
                result=result,
                turn_id=turn_id,
                response_plan=response_plan,
                messages=segmented_messages,
                trace_summary=trace_summary,
                trace_available=trace_available,
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
        notification_persona_id = (
            notification_message.persona_id
            if notification_message is not None
            else context.active_persona_id
        )
        notification_response_text = response_text
        if str((ux_plan or {}).get("assistant_surface_mode") or "").strip() == "reaction_only":
            notification_response_text = self._resolve_reaction_notification_text(
                ux_plan, fallback=response_text
            )
            notification_message_id = None
            notification_message_kind = "assistant_reaction"
            notification_persona_id = context.active_persona_id
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
                message_payload=dict(getattr(result, "message_payload", {}) or {}),
                orchestration_id=result.orchestration_id,
                trace_summary=trace_summary,
                trace_available=trace_available,
                ux_plan=result.ux_plan,
                message_id=notification_message_id,
                message_kind=notification_message_kind,
                persona_id=notification_persona_id,
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

    def _schedule_transcript_summary_update(self, context: ChatRuntimeContext) -> None:
        if self._transcript_summarizer is None:
            return

        async def _runner() -> None:
            try:
                await self._transcript_summarizer.maybe_summarize_session(
                    user_id=context.user_id,
                    session_id=context.session_id,
                )
            except Exception:
                logger.exception(
                    "Background transcript summary failed user_id=%s session_id=%s",
                    context.user_id,
                    context.session_id,
                )

        task = asyncio.create_task(
            _runner(),
            name=f"chat-transcript-summary:{context.session_id}",
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _build_response_rhythm_plan(
        self,
        *,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        response_text: str,
        ux_plan: dict[str, Any],
    ):
        if self._response_rhythm_planner is None:
            return None
        try:
            return await self._response_rhythm_planner.plan(
                user_message=result.root_user_message or context.latest_user_message,
                response_text=response_text,
                execution_mode=self._normalize_mode(result.mode),
                ux_plan=ux_plan,
                streamed=bool(getattr(result, "streamed", False)),
            )
        except Exception as exc:
            logger.debug("Conversation rhythm planning failed", error=str(exc))
            return None

    async def _emit_segmented_agent_response_notifications(
        self,
        *,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        turn_id: str | None,
        response_plan,
        messages,
        trace_summary: dict[str, Any] | None,
        trace_available: bool,
    ) -> None:
        attachments = list(getattr(result, "attachments", []) or [])
        total = len(messages)
        for index, message in enumerate(messages):
            if index > 0:
                delay_ms = 0
                if index < len(response_plan.segments):
                    delay_ms = int(response_plan.segments[index].delay_ms or 0)
                if delay_ms > 0:
                    await asyncio.sleep(delay_ms / 1000.0)
            segment_payload = self._parse_message_payload(message.payload_json)
            await self._emit_agent_response_notification(
                user_id=context.user_id,
                session_id=context.session_id,
                turn_id=turn_id,
                response_text=str(message.content_text or ""),
                attachments=attachments if index == total - 1 else [],
                message_payload=segment_payload,
                orchestration_id=result.orchestration_id,
                trace_summary=trace_summary,
                trace_available=trace_available,
                ux_plan=result.ux_plan,
                message_id=message.message_id,
                message_kind=message.message_kind,
                persona_id=message.persona_id,
            )

    @staticmethod
    def _parse_message_payload(raw_payload_json: str | None) -> dict[str, Any]:
        if not raw_payload_json:
            return {}
        try:
            parsed = json.loads(raw_payload_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

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
            persona_id=context.active_persona_id,
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


class _ChatPostProcessOperations(
    ChatPostprocessTraceMixin,
    ChatPostprocessBackgroundMixin,
    ChatPostprocessSessionMixin,
    ChatPostprocessToolEventMixin,
    ChatPostprocessOutcomeMixin,
    ChatPostprocessMemoryMixin,
    ChatPostprocessIntentMixin,
):
    def __init__(self, host: ChatPostProcessService) -> None:
        self._host = host

    def __getattribute__(self, name: str) -> Any:
        if name not in {"_host", "__dict__", "__class__", "__getattribute__", "__getattr__"}:
            host = object.__getattribute__(self, "_host")
            override = host.__dict__.get(name)
            if override is not None:
                return override
        return object.__getattribute__(self, name)

    def __getattr__(self, name: str) -> Any:
        host = object.__getattribute__(self, "_host")
        return object.__getattribute__(host, name)
