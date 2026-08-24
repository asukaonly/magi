"""Post-processing and side effects for chat execution results."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from magi.core.logger import get_logger
from magi.agent.execution.task_budget import TaskBudgetExceeded
from magi.agent.runtime.contracts import FactRecord
from magi.agent.trace import (
    now_wall_ms,
)
from magi.chat import ChatStore
from magi.delivery.contracts import DeliveryFanoutResult
from magi.chat.rhythm_completion import complete_visible_rhythm_segments
from magi.events.events import EventTypes
from magi.events.first_context import FIRST_CONTEXT_STORY_INTERACTION_KIND
from magi.i18n import t
from magi.runtime_trace import (
    RuntimeTraceStore,
)
from magi.agent.task_agents.common import (
    ExecutionMode,
    ExecutionResult,
    AgentRunExecutionResult,
    IncomingFactKind,
)
from magi.agent.task_agents.handlers.contracts import ChatParseOutcome, ChatRuntimeContext
from .context_assembler import ChatContextAssembler
from .postprocess.components import ChatOutcomeWriter, ChatRuntimeNotifier
from .postprocess.delivery import ChatPostprocessDeliveryMixin
from .postprocess.capability_projection import ChatPostprocessCapabilityMixin
from .postprocess.memory import ChatPostprocessMemoryMixin
from .postprocess.outcomes import ChatPostprocessOutcomeMixin
from .postprocess.session import ChatPostprocessSessionMixin
from .postprocess.tool_events import ChatPostprocessToolEventMixin
from .postprocess.trace import ChatPostprocessTraceMixin
from magi.agent.response_rhythm import strip_segmentation_sentinel
from .session_run_decisions import TurnSupersession

if TYPE_CHECKING:
    from magi.runtime_trace.chat_trace.read_service import ChatTraceReadService

logger = get_logger(__name__)

_PENDING_INTERJECTION_DISPOSITIONS = frozenset({"augment", "defer", "steer"})
_TERMINAL_TURN_STATUSES = frozenset({"cancelled", "interrupted", "merged"})


class _MissingVisibleChatResponseError(RuntimeError):
    """Signal that an expected visible response produced no usable content."""


def _default_chat_read_service_factory() -> Any:
    from magi.chat import get_chat_read_service

    return get_chat_read_service()


@dataclass(slots=True)
class _PreparedChatPostprocess:
    event_emitter: Any
    latest_fact: FactRecord
    ux_plan: dict[str, Any]
    raw_response_text: str
    response_text: str
    user_message: str | None
    correlation_id: str | None
    turn_id: str | None
    started_at_ms: int
    response_plan: Any | None
    rhythm_started_at_ms: int
    rhythm_ended_at_ms: int
    now_ms: int = 0
    history_stored: bool = False
    memory_updated: bool = False
    trace_summary: dict[str, Any] | None = None
    trace_available: bool = False
    reply_anchor_message_id: str | None = None
    segmented_messages: list[Any] = field(default_factory=list)


class ChatPostProcessService:
    """Applies side effects for chat execution results."""

    def __init__(
        self,
        *,
        agent_id: str,
        context_assembler: ChatContextAssembler,
        get_event_emitter: Callable[[], Any],
        get_task_agent_manager: Callable[[], Any | None],
        get_sensor_hub: Callable[[], Any | None],
        memory=None,
        unified_memory=None,
        post_turn_understanding_service=None,
        max_fact_memory: int = 200,
        trace_read_service: "ChatTraceReadService | None" = None,
        runtime_trace_store: RuntimeTraceStore | None = None,
        chat_store: ChatStore | None = None,
        chat_read_service_factory: Callable[[], Any] | None = None,
        complete_session_run: Callable[[str, str, int], Any] | None = None,
        resolve_session_run_status: Callable[[str, str, int], Any] | None = None,
        release_deferred_turns: Callable[[str, list[Any]], Any] | None = None,
        response_rhythm_planner: Any | None = None,
        transcript_summarizer: Any | None = None,
        event_bus: Any | None = None,
        deliver_final_response: Callable[..., Awaitable[DeliveryFanoutResult]] | None = None,
    ) -> None:
        self._wire_core_dependencies(
            agent_id=agent_id,
            context_assembler=context_assembler,
            get_event_emitter=get_event_emitter,
            get_task_agent_manager=get_task_agent_manager,
            get_sensor_hub=get_sensor_hub,
            memory=memory,
            unified_memory=unified_memory,
            post_turn_understanding_service=post_turn_understanding_service,
            max_fact_memory=max_fact_memory,
        )
        self._wire_output_components(
            trace_read_service=trace_read_service,
            runtime_trace_store=runtime_trace_store,
            chat_store=chat_store,
            chat_read_service_factory=chat_read_service_factory,
            event_bus=event_bus,
        )
        self._wire_session_runtime(
            complete_session_run=complete_session_run,
            resolve_session_run_status=resolve_session_run_status,
            release_deferred_turns=release_deferred_turns,
            response_rhythm_planner=response_rhythm_planner,
            transcript_summarizer=transcript_summarizer,
        )
        self._wire_delivery(deliver_final_response)
    async def cancel_background_tasks(self) -> None:
        """Cancel detached post-processing created before a destructive clear."""

        await self._cancel_detached_background_tasks()
        self._deferred_release_retry_keys.clear()

    async def shutdown_background_tasks(self) -> None:
        """Finish runtime handoff before a normal session-agent shutdown."""

        handoff_tasks = [
            task
            for task in self._background_tasks
            if not task.done() and task.get_name().startswith("chat-outcome-enqueue:")
        ]
        if handoff_tasks:
            await asyncio.gather(*handoff_tasks, return_exceptions=True)
        await self._cancel_detached_background_tasks()
        self._deferred_release_retry_keys.clear()

    async def _cancel_detached_background_tasks(self) -> None:
        """Cancel and drain currently detached post-processing tasks."""

        tasks = [task for task in self._background_tasks if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._background_tasks.clear()

    def has_pending_background_work(self) -> bool:
        """Return whether post-processing still owns the session."""

        return bool(self._deferred_release_retry_keys)

    async def handle_pipeline_failure(
        self,
        *,
        source_fact: FactRecord,
        error: BaseException,
        stage: str,
    ) -> bool:
        """Persist a retryable failure for one exact admitted user turn."""

        if self._chat_store is None or source_fact.event_type != EventTypes.USER_MESSAGE:
            return False
        payload = source_fact.payload if isinstance(source_fact.payload, dict) else {}
        user_id = str(payload.get("user_id") or "").strip()
        session_id = str(payload.get("session_id") or "").strip()
        turn_id = str(payload.get("turn_id") or "").strip()
        if (
            not user_id
            or not session_id
            or not turn_id
            or source_fact.delivery_attempt_no is None
            or source_fact.runtime_command_id is None
        ):
            return False

        if isinstance(error, TaskBudgetExceeded):
            failure_message = t(
                "chat.delivery.execution_limit_reached",
                fallback=(
                    "This task reached its execution limit and was stopped to "
                    "avoid an unbounded loop. Narrow the request or start a new task."
                ),
            )
        else:
            failure_message = t(
                "chat.delivery.execution_failed",
                fallback="I couldn't finish this message. Send it again to retry.",
            )
        result = await self._chat_store.finalize_user_turn_delivery_failure(
            turn_id=turn_id,
            delivery_attempt_no=int(source_fact.delivery_attempt_no),
            command_id=int(source_fact.runtime_command_id),
            user_message=failure_message,
            failure_stage=stage,
            error_type=type(error).__name__,
            updated_at_ms=now_wall_ms(),
        )
        if not result.applied:
            logger.info(
                "Chat pipeline failure finalization was superseded",
                turn_id=turn_id,
                delivery_attempt_no=int(source_fact.delivery_attempt_no),
                runtime_command_id=int(source_fact.runtime_command_id),
            )
            return False
        if not result.wrote_failure or not result.message_id:
            return True

        try:
            await self._runtime_notifier.emit_chat_message_upsert(
                user_id=user_id,
                session_id=session_id,
                message_id=result.message_id,
            )
        except Exception:
            logger.warning(
                "Failed to publish chat failure message upsert",
                turn_id=turn_id,
                exc_info=True,
            )
        event_emitter = self._get_event_emitter()
        if event_emitter is not None:
            try:
                await event_emitter.emit_chat_response_event(
                    user_id=user_id,
                    session_id=session_id,
                    response=failure_message,
                    correlation_id=source_fact.correlation_id,
                    turn_id=turn_id,
                    orchestration_id=None,
                    trace_summary=None,
                    trace_available=False,
                )
            except Exception:
                logger.warning(
                    "Failed to publish chat pipeline failure response",
                    turn_id=turn_id,
                    exc_info=True,
                )
        return True

    def _wire_core_dependencies(
        self,
        *,
        agent_id: str,
        context_assembler: ChatContextAssembler,
        get_event_emitter: Callable[[], Any],
        get_task_agent_manager: Callable[[], Any | None],
        get_sensor_hub: Callable[[], Any | None],
        memory: Any,
        unified_memory: Any,
        post_turn_understanding_service: Any,
        max_fact_memory: int,
    ) -> None:
        self._agent_id = agent_id
        self._context_assembler = context_assembler
        self._tool_state_view = context_assembler.tool_state_view
        self._get_event_emitter = get_event_emitter
        self._get_task_agent_manager = get_task_agent_manager
        self._get_sensor_hub = get_sensor_hub
        self._memory = memory
        self._unified_memory = unified_memory
        self._post_turn_understanding_service = post_turn_understanding_service
        self._local_fact_memory: list[FactRecord] = []
        self._max_fact_memory = max_fact_memory

    def _wire_output_components(
        self,
        *,
        trace_read_service: "ChatTraceReadService | None",
        runtime_trace_store: RuntimeTraceStore | None,
        chat_store: ChatStore | None,
        chat_read_service_factory: Callable[[], Any] | None,
        event_bus: Any | None,
    ) -> None:
        self._chat_store = chat_store
        self._trace_read_service = trace_read_service
        self._chat_read_service_factory = (
            chat_read_service_factory or _default_chat_read_service_factory
        )
        self._runtime_trace_store = runtime_trace_store
        self._event_bus = event_bus
        self._operations = _ChatPostProcessOperations(self)
        self._chat_outcome_writer = ChatOutcomeWriter(
            chat_store=chat_store,
            trace_id_factory=self._build_trace_id,
        )
        self._runtime_notifier = ChatRuntimeNotifier(
            runtime_trace_store=runtime_trace_store,
            chat_read_service_factory=self._chat_read_service_factory,
        )
        self._started_turn_traces: set[str] = set()

    def _wire_session_runtime(
        self,
        *,
        complete_session_run: Callable[[str, str, int], Any] | None,
        resolve_session_run_status: Callable[[str, str, int], Any] | None,
        release_deferred_turns: Callable[[str, list[Any]], Any] | None,
        response_rhythm_planner: Any | None,
        transcript_summarizer: Any | None,
    ) -> None:
        self._complete_session_run = complete_session_run
        self._resolve_session_run_status = resolve_session_run_status
        self._release_deferred_turns = release_deferred_turns
        self._response_rhythm_planner = response_rhythm_planner
        self._transcript_summarizer = transcript_summarizer

    def _wire_delivery(
        self,
        deliver_final_response: Callable[..., Awaitable[DeliveryFanoutResult]] | None,
    ) -> None:
        self._deliver_final_response = deliver_final_response
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._deferred_release_retry_keys: set[tuple[str, str, int]] = set()

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
            await self.mark_user_turn_delivery_terminal_if_persisted(
                turn_id=superseded_turn.turn_id,
                source_fact=None,
            )

    async def handle(
        self, context: ChatRuntimeContext, result: ExecutionResult
    ) -> ChatParseOutcome:
        prepared = await self._prepare_chat_postprocess(context, result)
        if isinstance(prepared, ChatParseOutcome):
            return prepared

        prepared.now_ms = now_wall_ms()
        await self._emit_chat_response_observability(context, result, prepared)
        await self._prepare_chat_delivery_state(context, prepared)
        if not await self._persist_chat_response_outcome(
            context,
            result,
            prepared,
        ):
            return ChatParseOutcome(False, False, False, False)
        try:
            await self._emit_committed_chat_response_observability(
                context,
                result,
                prepared,
            )
        except Exception:
            logger.warning(
                "Failed to publish committed chat response trace",
                turn_id=prepared.turn_id,
                exc_info=True,
            )
        response_mode = str(
            prepared.ux_plan.get("assistant_surface_mode") or ""
        ).strip()
        has_message_surface = response_mode not in {"none", "reaction_only"}
        await self._mark_required_user_turn_delivery_terminal(
            turn_id=prepared.turn_id,
            source_fact=prepared.latest_fact,
            required_message_kind=(
                (
                    "assistant_rhythm_segment"
                    if prepared.response_plan is not None
                    else "assistant_final"
                )
                if has_message_surface
                else None
            ),
            expected_message_count=(
                len(prepared.response_plan.segments)
                if prepared.response_plan is not None
                else (1 if has_message_surface else 0)
            ),
        )
        await self._record_chat_history_and_memory(context, result, prepared)
        await self._finalize_session_run(context)
        self._schedule_transcript_summary_update(context)
        return await self._deliver_chat_response_outcome(context, result, prepared)

    async def _prepare_chat_postprocess(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
    ) -> _PreparedChatPostprocess | ChatParseOutcome:
        preflight = await self._preflight_chat_postprocess(context, result)
        if isinstance(preflight, ChatParseOutcome):
            return preflight
        event_emitter, latest_fact, ux_plan = preflight

        raw_response_text, response_text = self._resolve_visible_response_text(result)
        if not response_text:
            if await self._complete_turn_without_visible_response(
                context=context,
                result=result,
                latest_fact=latest_fact,
                ux_plan=ux_plan,
            ):
                return ChatParseOutcome(False, False, False, False)
            raise _MissingVisibleChatResponseError(
                "A visible chat response was expected but no content was produced"
            )

        return await self._build_prepared_chat_postprocess(
            context=context,
            result=result,
            event_emitter=event_emitter,
            latest_fact=latest_fact,
            ux_plan=ux_plan,
            raw_response_text=raw_response_text,
            response_text=response_text,
        )

    async def _preflight_chat_postprocess(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
    ) -> tuple[Any, FactRecord, dict[str, Any]] | ChatParseOutcome:
        event_emitter = self._get_event_emitter()
        latest_fact = context.latest_fact
        if not isinstance(latest_fact, FactRecord):
            return ChatParseOutcome(False, False, False, False)
        if context.incoming_fact_kind not in {
            IncomingFactKind.USER_MESSAGE,
            IncomingFactKind.WORKER_UPDATE,
            IncomingFactKind.EXPLORE_TASK_COMPLETED,
            IncomingFactKind.EXPLORE_TASK_FAILED,
        }:
            return ChatParseOutcome(False, False, False, False)
        ux_plan = result.ux_plan if isinstance(result.ux_plan, dict) else {}
        if await self._session_run_status(context) in {
            "cancelling",
            "cancelled",
        }:
            await self._finalize_session_run(context)
            return ChatParseOutcome(False, False, False, False)
        if result.skip_emit:
            await self._complete_turn_without_visible_response(
                context=context,
                result=result,
                latest_fact=latest_fact,
                ux_plan=ux_plan,
            )
            return ChatParseOutcome(False, False, False, False)
        if event_emitter is None:
            return ChatParseOutcome(False, False, False, False)
        return event_emitter, latest_fact, ux_plan

    async def _build_prepared_chat_postprocess(
        self,
        *,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        event_emitter: Any,
        latest_fact: FactRecord,
        ux_plan: dict[str, Any],
        raw_response_text: str,
        response_text: str,
    ) -> _PreparedChatPostprocess:
        correlation_id = result.correlation_id or latest_fact.correlation_id
        turn_id = result.turn_id or self._resolve_turn_id(
            context, latest_fact.payload if isinstance(latest_fact.payload, dict) else {}
        )
        started_at_ms = self._resolve_started_at_ms(result, latest_fact)
        rhythm_started_at_ms = now_wall_ms()
        response_plan = await self._build_response_rhythm_plan(
            context=context,
            result=result,
            response_text=raw_response_text,
            ux_plan=ux_plan,
        )
        rhythm_ended_at_ms = now_wall_ms()
        if response_plan is not None:
            response_text = str(response_plan.aggregate_text or response_text).strip() or response_text
            result.response_plan = response_plan

        return _PreparedChatPostprocess(
            event_emitter=event_emitter,
            latest_fact=latest_fact,
            ux_plan=ux_plan,
            raw_response_text=raw_response_text,
            response_text=response_text,
            user_message=result.root_user_message or context.latest_user_message,
            correlation_id=correlation_id,
            turn_id=turn_id,
            started_at_ms=started_at_ms,
            response_plan=response_plan,
            rhythm_started_at_ms=rhythm_started_at_ms,
            rhythm_ended_at_ms=rhythm_ended_at_ms,
        )

    def _resolve_visible_response_text(self, result: ExecutionResult) -> tuple[str, str]:
        raw_response_text = str(result.response_text or "").strip()
        response_text = strip_segmentation_sentinel(raw_response_text)
        if response_text:
            return raw_response_text, response_text

        execution_outcome = (
            result.execution_outcome if isinstance(result, AgentRunExecutionResult) else {}
        )
        if isinstance(execution_outcome, dict) and execution_outcome.get("status") == "failed":
            failure_reason = str(execution_outcome.get("failure_reason") or "EXECUTION_ERROR")
            response_text = f"Execution failed: {failure_reason}"
            return response_text, response_text
        if isinstance(execution_outcome, dict) and execution_outcome.get("status") == "detached":
            response_text = "Failed to move this task to the background."
            return response_text, response_text
        return raw_response_text, response_text

    async def _record_chat_history_and_memory(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedChatPostprocess,
    ) -> None:
        user_message = result.root_user_message or context.latest_user_message
        if prepared.latest_fact.event_type == EventTypes.USER_MESSAGE and user_message:
            self._context_assembler.append_user_message(context.history_key, user_message)
            prepared.history_stored = True
        self._context_assembler.append_assistant_message(
            context.history_key,
            prepared.response_text,
        )
        prepared.history_stored = True
        prepared.user_message = user_message
        is_first_context_story = (
            str(getattr(context.latest_payload, "interaction_kind", "") or "")
            .strip()
            .lower()
            == FIRST_CONTEXT_STORY_INTERACTION_KIND
        )
        if user_message and not is_first_context_story:
            assistant_message_ids = [
                str(message.message_id)
                for message in prepared.segmented_messages
                if str(getattr(message, "message_id", "") or "").strip()
            ]
            if not assistant_message_ids:
                assistant_message = await self._get_turn_ux_chat_message(
                    turn_id=prepared.turn_id,
                    ux_plan=prepared.ux_plan,
                )
                if assistant_message is not None:
                    assistant_message_ids.append(
                        str(assistant_message.message_id)
                    )
            prepared.memory_updated = self._schedule_background_memory_updates(
                user_id=context.user_id,
                user_message=user_message,
                response_text=prepared.response_text,
                context=context,
                result=result,
                turn_id=prepared.turn_id,
                assistant_message_ids=assistant_message_ids,
                accepted_at=float(prepared.now_ms) / 1000.0,
            )

    async def _emit_chat_response_observability(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedChatPostprocess,
    ) -> None:
        await self._emit_result_llm_trace(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=prepared.turn_id,
            llm_trace=getattr(result, "llm_trace", {}),
            started_at_ms=prepared.started_at_ms,
            user_message=context.latest_user_message,
        )

    async def _emit_committed_chat_response_observability(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedChatPostprocess,
    ) -> None:
        """Publish response traces only after the durable outcome wins."""

        if isinstance(result.context_usage, dict) and prepared.turn_id:
            await self._emit_context_usage_notification(
                user_id=context.user_id,
                session_id=context.session_id,
                turn_id=prepared.turn_id,
                context_usage={
                    **result.context_usage,
                    "updated_at_ms": prepared.now_ms,
                },
            )
        if prepared.response_plan is not None:
            await self._emit_response_rhythm_trace(
                user_id=context.user_id,
                session_id=context.session_id,
                turn_id=prepared.turn_id,
                response_text=prepared.response_text,
                response_plan=prepared.response_plan,
                started_at_ms=prepared.rhythm_started_at_ms,
                ended_at_ms=prepared.rhythm_ended_at_ms,
                mode=self._normalize_mode(result.mode),
                user_message=context.latest_user_message,
            )
        await self._emit_response_trace(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=prepared.turn_id,
            response_text=prepared.response_text,
            started_at_ms=prepared.started_at_ms,
            ended_at_ms=prepared.now_ms,
            orchestration_id=result.orchestration_id,
            mode=self._normalize_mode(result.mode),
            user_message=context.latest_user_message,
        )

    async def _prepare_chat_delivery_state(
        self,
        context: ChatRuntimeContext,
        prepared: _PreparedChatPostprocess,
    ) -> None:
        prepared.trace_summary, prepared.trace_available = self._resolve_trace_summary(
            context=context,
            turn_id=prepared.turn_id,
        )
        prepared.reply_anchor_message_id = await self._resolve_result_reply_anchor_message_id(
            context=context,
            turn_id=prepared.turn_id,
        )

    def _resolve_trace_summary(
        self,
        *,
        context: ChatRuntimeContext,
        turn_id: str | None,
    ) -> tuple[dict[str, Any] | None, bool]:
        if self._trace_read_service and turn_id:
            try:
                snapshot = self._trace_read_service.get_trace_snapshot(
                    user_id=context.user_id,
                    session_id=context.session_id,
                    turn_id=turn_id,
                )
                if isinstance(snapshot, dict):
                    summary = snapshot.get("summary")
                    return summary, bool(snapshot.get("summary", {}).get("trace_available"))
            except Exception as exc:
                logger.debug("Failed to fetch trace snapshot for AI_RESPONSE event: %s", exc)
        return None, False

    async def _persist_chat_response_outcome(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedChatPostprocess,
    ) -> bool:
        (
            delivery_identity,
            delivery_is_terminal,
        ) = await self._resolve_outcome_delivery_identity(
            turn_id=prepared.turn_id,
            source_fact=prepared.latest_fact,
        )
        if delivery_is_terminal:
            return False
        if prepared.response_plan is not None:
            accepted = await self._try_persist_segmented_response(
                context,
                result,
                prepared,
                delivery_identity=delivery_identity,
            )
            if not accepted:
                return False

        if prepared.response_plan is None:
            return await self._persist_final_response_outcome(
                context,
                result,
                prepared,
                delivery_identity=delivery_identity,
            )
        return True

    async def _try_persist_segmented_response(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedChatPostprocess,
        *,
        delivery_identity: tuple[int, int] | None,
    ) -> bool:
        try:
            if delivery_identity is None:
                prepared.segmented_messages = (
                    await self._persist_segmented_chat_outcome(
                        turn_id=prepared.turn_id,
                        response_plan=prepared.response_plan,
                        attachments=list(getattr(result, "attachments", []) or []),
                        message_payload=dict(
                            getattr(result, "message_payload", {}) or {}
                        ),
                        started_at_ms=prepared.started_at_ms,
                        completed_at_ms=prepared.now_ms,
                        context_usage=result.context_usage,
                        orchestration_id=result.orchestration_id,
                        execution_mode=self._normalize_mode(result.mode),
                        ux_plan=prepared.ux_plan,
                        run_id=context.session_run_id,
                        run_revision=context.session_run_revision,
                        run_disposition=context.session_run_disposition,
                        reply_to_message_id=prepared.reply_anchor_message_id,
                        persona_id=context.active_persona_id,
                    )
                )
                accepted = True
            else:
                accepted, prepared.segmented_messages = (
                    await self._commit_segmented_chat_outcome(
                        turn_id=prepared.turn_id,
                        delivery_attempt_no=delivery_identity[0],
                        command_id=delivery_identity[1],
                        response_plan=prepared.response_plan,
                        attachments=list(getattr(result, "attachments", []) or []),
                        message_payload=dict(
                            getattr(result, "message_payload", {}) or {}
                        ),
                        started_at_ms=prepared.started_at_ms,
                        completed_at_ms=prepared.now_ms,
                        context_usage=result.context_usage,
                        orchestration_id=result.orchestration_id,
                        execution_mode=self._normalize_mode(result.mode),
                        ux_plan=prepared.ux_plan,
                        run_id=context.session_run_id,
                        run_revision=context.session_run_revision,
                        run_disposition=context.session_run_disposition,
                        reply_to_message_id=prepared.reply_anchor_message_id,
                        persona_id=context.active_persona_id,
                    )
                )
            if not accepted:
                return False
        except Exception as exc:
            logger.warning(
                "Segmented chat outcome persistence failed; falling back to final message: %s",
                exc,
            )
            hidden = await self._hide_persisted_rhythm_segments(
                session_id=context.session_id,
                turn_id=prepared.turn_id,
            )
            if not hidden:
                raise RuntimeError(
                    "Failed to clean up a partial segmented response"
                ) from exc
            prepared.segmented_messages = []
            prepared.response_plan = None
            result.response_plan = None
        if not prepared.segmented_messages:
            prepared.response_plan = None
            result.response_plan = None
        return True

    async def _persist_final_response_outcome(
        self,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        prepared: _PreparedChatPostprocess,
        *,
        delivery_identity: tuple[int, int] | None,
    ) -> bool:
        outcome_kwargs = {
            "turn_id": prepared.turn_id,
            "response_text": prepared.response_text,
            "attachments": list(getattr(result, "attachments", []) or []),
            "message_payload": dict(getattr(result, "message_payload", {}) or {}),
            "started_at_ms": prepared.started_at_ms,
            "completed_at_ms": prepared.now_ms,
            "context_usage": result.context_usage,
            "orchestration_id": result.orchestration_id,
            "execution_mode": self._normalize_mode(result.mode),
            "ux_plan": prepared.ux_plan,
            "run_id": context.session_run_id,
            "run_revision": context.session_run_revision,
            "run_disposition": context.session_run_disposition,
            "reply_to_message_id": prepared.reply_anchor_message_id,
            "persona_id": context.active_persona_id,
        }
        if delivery_identity is None:
            return await self._persist_final_chat_outcome(**outcome_kwargs)
        return await self._commit_final_chat_outcome(
            delivery_attempt_no=delivery_identity[0],
            command_id=delivery_identity[1],
            **outcome_kwargs,
        )

    async def _resolve_outcome_delivery_identity(
        self,
        *,
        turn_id: str | None,
        source_fact: FactRecord | None,
    ) -> tuple[tuple[int, int] | None, bool]:
        """Resolve an exact admitted attempt or a terminal rejection."""

        normalized_turn_id = str(turn_id or "").strip()
        if self._chat_store is None or not normalized_turn_id:
            return None, False
        fact_turn_id = ""
        if isinstance(source_fact, FactRecord) and isinstance(
            source_fact.payload,
            dict,
        ):
            fact_turn_id = str(source_fact.payload.get("turn_id") or "").strip()
        if (
            isinstance(source_fact, FactRecord)
            and fact_turn_id == normalized_turn_id
            and source_fact.delivery_attempt_no is not None
            and source_fact.runtime_command_id is not None
        ):
            return (
                (
                    int(source_fact.delivery_attempt_no),
                    int(source_fact.runtime_command_id),
                ),
                False,
            )
        delivery = await self._chat_store.get_user_turn_delivery(
            turn_id=normalized_turn_id,
        )
        if delivery is None:
            return None, False
        if delivery.delivery_state == "terminal":
            return None, True
        if (
            delivery.delivery_state != "admitted"
            or delivery.current_command_id is None
        ):
            return None, False
        return (
            (
                int(delivery.delivery_attempt_no),
                int(delivery.current_command_id),
            ),
            False,
        )

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
                response_text=response_text,
                streamed=bool(getattr(result, "streamed", False)),
                persona=getattr(result, "persona_rhythm", None),
                ux_plan=ux_plan,
            )
        except Exception as exc:
            logger.debug("Conversation rhythm planning failed", error=str(exc))
            return None

    async def _complete_turn_without_visible_response(
        self,
        *,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        latest_fact: FactRecord,
        ux_plan: dict[str, Any],
    ) -> bool:
        if (
            result.mode == ExecutionMode.FACT_ONLY
            and str(context.session_run_disposition or "").strip().lower()
            in _PENDING_INTERJECTION_DISPOSITIONS
        ):
            # AUGMENT / STEER / DEFER facts have only been durably accepted by
            # the active run.  They have not produced a terminal chat outcome.
            return True
        response_mode = str(ux_plan.get("assistant_surface_mode") or "").strip()
        if response_mode not in {"none", "reaction_only"}:
            return False
        turn_id = result.turn_id or self._resolve_turn_id(
            context,
            latest_fact.payload if isinstance(latest_fact.payload, dict) else {},
        )
        now_ms = now_wall_ms()
        started_at_ms = self._resolve_started_at_ms(result, latest_fact)
        outcome_kwargs = {
            "turn_id": turn_id,
            "response_text": "",
            "started_at_ms": started_at_ms,
            "completed_at_ms": now_ms,
            "context_usage": result.context_usage,
            "orchestration_id": result.orchestration_id,
            "execution_mode": self._normalize_mode(result.mode),
            "ux_plan": ux_plan,
            "run_id": context.session_run_id,
            "run_revision": context.session_run_revision,
            "run_disposition": context.session_run_disposition,
            "reply_to_message_id": (
                await self._resolve_result_reply_anchor_message_id(
                    context=context,
                    turn_id=turn_id,
                )
            ),
            "persona_id": context.active_persona_id,
        }
        (
            delivery_identity,
            delivery_is_terminal,
        ) = await self._resolve_outcome_delivery_identity(
            turn_id=turn_id,
            source_fact=latest_fact,
        )
        if delivery_is_terminal:
            return True
        if delivery_identity is None:
            accepted = await self._persist_final_chat_outcome(**outcome_kwargs)
        else:
            accepted = await self._commit_final_chat_outcome(
                delivery_attempt_no=delivery_identity[0],
                command_id=delivery_identity[1],
                **outcome_kwargs,
            )
        if not accepted:
            return True
        await self._mark_required_user_turn_delivery_terminal(
            turn_id=turn_id,
            source_fact=latest_fact,
        )
        await self._finalize_session_run(context)
        await self.emit_execution_control_notification(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
            run_id=context.session_run_id,
            orchestration_id=result.orchestration_id,
            state="completed",
            can_cancel=False,
        )
        return True

    async def _mark_required_user_turn_delivery_terminal(
        self,
        *,
        turn_id: str | None,
        source_fact: FactRecord | None,
        required_message_kind: str | None = None,
        expected_message_count: int = 0,
    ) -> None:
        """Require an existing delivery owner to accept the durable outcome."""

        terminal = await self.mark_user_turn_delivery_terminal_if_persisted(
            turn_id=turn_id,
            source_fact=source_fact,
            required_message_kind=required_message_kind,
            expected_message_count=expected_message_count,
        )
        if terminal or self._chat_store is None:
            return
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            return
        delivery = await self._chat_store.get_user_turn_delivery(
            turn_id=normalized_turn_id,
        )
        if delivery is None:
            return
        raise RuntimeError(
            "Durable chat outcome did not close its user-turn delivery attempt"
        )

    async def mark_user_turn_delivery_terminal_if_persisted(
        self,
        *,
        turn_id: str | None,
        source_fact: FactRecord | None,
        required_message_kind: str | None = None,
        expected_message_count: int = 0,
    ) -> bool:
        """Close delivery only after the matching chat outcome is durable."""

        normalized_turn_id = str(turn_id or "").strip()
        if self._chat_store is None or not normalized_turn_id:
            return False
        turn = await self._chat_store.get_turn(normalized_turn_id)
        if turn is None:
            return False
        status = str(turn.status or "").strip().lower()
        if status in _TERMINAL_TURN_STATUSES:
            pass
        elif status == "completed":
            response_mode = str(turn.response_mode or "").strip().lower()
            if required_message_kind is None:
                if response_mode not in {"none", "reaction_only"}:
                    return False
            elif not await self._has_complete_visible_message_set(
                session_id=turn.session_id,
                turn_id=normalized_turn_id,
                message_kind=required_message_kind,
                expected_count=max(1, int(expected_message_count or 0)),
            ):
                return False
        else:
            return False

        now_ms = now_wall_ms()
        fact_turn_id = ""
        if isinstance(source_fact, FactRecord) and isinstance(source_fact.payload, dict):
            fact_turn_id = str(source_fact.payload.get("turn_id") or "").strip()
        if (
            isinstance(source_fact, FactRecord)
            and fact_turn_id == normalized_turn_id
            and source_fact.delivery_attempt_no is not None
            and source_fact.runtime_command_id is not None
        ):
            changed = await self._chat_store.mark_user_turn_delivery_terminal(
                turn_id=normalized_turn_id,
                delivery_attempt_no=int(source_fact.delivery_attempt_no),
                command_id=int(source_fact.runtime_command_id),
                updated_at_ms=now_ms,
            )
            if not changed:
                current = await self._chat_store.get_user_turn_delivery(
                    turn_id=normalized_turn_id,
                )
                if (
                    current is not None
                    and current.delivery_state == "terminal"
                    and current.delivery_attempt_no
                    == int(source_fact.delivery_attempt_no)
                    and current.current_command_id
                    == int(source_fact.runtime_command_id)
                ):
                    return True
                logger.info(
                    "Exact user-turn delivery terminal transition was superseded",
                    turn_id=normalized_turn_id,
                    delivery_attempt_no=int(source_fact.delivery_attempt_no),
                    runtime_command_id=int(source_fact.runtime_command_id),
                )
            return bool(changed)

        delivery = await self._chat_store.get_user_turn_delivery(
            turn_id=normalized_turn_id,
        )
        if delivery is None or delivery.delivery_state == "terminal":
            return delivery is not None
        changed = await self._chat_store.reconcile_user_turn_terminal_surface(
            turn_id=normalized_turn_id,
            expected_attempt_no=delivery.delivery_attempt_no,
            updated_at_ms=now_ms,
        )
        if not changed:
            logger.info(
                "Recovered user-turn delivery terminal transition was superseded",
                turn_id=normalized_turn_id,
                delivery_attempt_no=delivery.delivery_attempt_no,
            )
        return bool(changed)

    async def _has_complete_visible_message_set(
        self,
        *,
        session_id: str,
        turn_id: str,
        message_kind: str,
        expected_count: int,
    ) -> bool:
        messages = await self._chat_store.list_messages(session_id=session_id)
        if message_kind == "assistant_rhythm_segment":
            return (
                complete_visible_rhythm_segments(
                    messages,
                    turn_id=turn_id,
                    expected_count=expected_count,
                )
                is not None
            )
        matching = [
            message
            for message in messages
            if message.turn_id == turn_id
            and message.message_kind == message_kind
            and message.is_visible
            and message.is_final
        ]
        return len(matching) >= expected_count

    def _resolve_turn_id(self, context: ChatRuntimeContext, payload: dict[str, Any]) -> str | None:
        latest_payload = context.latest_payload
        typed_turn_id = str(getattr(latest_payload, "turn_id", "") or "").strip()
        if typed_turn_id:
            return typed_turn_id
        raw_turn_id = str(payload.get("turn_id") or "").strip()
        return raw_turn_id or None


class _ChatPostProcessOperations(
    ChatPostprocessDeliveryMixin,
    ChatPostprocessTraceMixin,
    ChatPostprocessSessionMixin,
    ChatPostprocessToolEventMixin,
    ChatPostprocessOutcomeMixin,
    ChatPostprocessMemoryMixin,
    ChatPostprocessCapabilityMixin,
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
