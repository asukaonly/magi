"""Runtime task agent for chat facts."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Callable, cast

from magi.agent.cancel import SessionRunCancelToken
from magi.agent.execution.task_budget import (
    TaskExecutionBudgetStore,
    fresh_task_execution_budget_context,
    task_execution_budget_scope,
)
from magi.control.run_control import null_run_control
from magi.agent.trace import now_wall_ms
from magi.chat import ChatReadService, ChatStore
from magi.chat.contracts import (
    CHAT_DELIVERY_STATE_ADMITTED,
    CHAT_DELIVERY_STATE_TERMINAL,
)
from magi.chat.rhythm_completion import complete_visible_rhythm_segments
from magi.chat.user_turn_delivery import parse_user_turn_runtime_envelope
from magi.delivery.contracts import DeliveryFanoutResult
from magi.config import get_config, get_user_preference
from magi.core.logger import get_logger
from magi.events.events import EventTypes
from magi.agent.runtime.contracts import FactRecord
from magi.agent.runtime.task_agent import (
    FactAdmissionResult,
    TaskAgent,
    TaskAgentBatchDiscarded,
    TaskAgentRuntimeContext,
)
from magi.agent.runtime.types import TaskAgentType
from magi.tools.registry import tool_registry
from magi.runtime_trace import RuntimeTraceStore
from magi.utils.runtime import get_runtime_paths
from magi.llm.streaming_events import stream_scope
from magi.agent.task_agents.handlers import (
    TurnAdmissionDecision,
    ChatRuntimeContext,
    CapabilitySelection,
    ExecutionRequest,
    ExecutionResult,
)
from magi.chat.task_agent.postprocess_service import ChatPostProcessService
from magi.chat.task_agent.reply_context import ChatReplyContextMixin
from magi.chat.task_agent.recall_feedback_context import ChatRecallFeedbackContextMixin
from magi.agent.response_rhythm import (
    is_conversation_rhythm_enabled,
)
from magi.chat.task_agent.session_control import ChatSessionControlMixin
from .streaming import (
    ChatStreamingMixin,
    format_llm_error as _format_llm_error,
)
from .runtime_dependencies import (
    ChatTaskAgentRuntimeCallbacks,
    ChatTaskAgentRuntimeConfig,
    build_chat_task_agent_runtime_parts,
)

logger = get_logger(__name__)

_PIPELINE_FAILURE_RETRY_INITIAL_SECONDS = 0.25
_PIPELINE_FAILURE_RETRY_MAX_SECONDS = 30.0

_RUNTIME_CONFIG_INIT_FIELDS = (
    "llm_adapter",
    "llm_pool",
    "memory",
    "unified_memory",
    "post_turn_understanding_service",
    "hybrid_retrieval_service",
    "history_cache_max_sessions",
    "skill_runner",
    "runtime_trace_store",
    "chat_store",
    "chat_read_service_factory",
    "background_launch_service",
    "permission_gateway_provider",
    "delivery_dispatcher_resolver",
    "conversation_log_resolver",
    "message_bus",
    "run_plan_store",
)


@dataclass(slots=True)
class _ChatRuntimePreferences:
    streaming_chat_enabled: bool
    allow_media_grounding_for_conversation: bool
    core_model_supports_vision: bool
    core_model_supports_tool_calls: bool


@dataclass(slots=True)
class _ChatContextInputs:
    session_id: str
    active_persona_id: str | None
    history_context: Any
    history: list[dict[str, Any]]
    history_key: str
    recent_tool_errors: list[dict[str, Any]]
    recent_tool_state: list[dict[str, Any]]
    reply_context: Any
    recall_feedback: Any
    preferences: _ChatRuntimePreferences


class ChatTaskAgent(
    ChatSessionControlMixin,
    ChatStreamingMixin,
    ChatReplyContextMixin,
    ChatRecallFeedbackContextMixin,
    TaskAgent[
        ChatRuntimeContext,
        TurnAdmissionDecision,
        CapabilitySelection,
        ExecutionRequest,
        ExecutionResult,
    ],
):
    """Consumes chat facts and delegates execution to typed handlers."""

    def __init__(
        self,
        agent_id: str,
        llm_adapter=None,
        llm_pool=None,
        memory=None,
        unified_memory=None,
        post_turn_understanding_service=None,
        hybrid_retrieval_service=None,
        memory_integration=None,
        history_cache_max_sessions: int = 500,
        skill_runner=None,
        runtime_trace_store: RuntimeTraceStore | None = None,
        chat_store: ChatStore | None = None,
        chat_read_service_factory: Callable[[], ChatReadService] | None = None,
        background_launch_service: Any | None = None,
        permission_gateway_provider: Callable[[], Any] | None = None,
        delivery_dispatcher_resolver: Callable[[], Any] | None = None,
        conversation_log_resolver: Callable[[], Any] | None = None,
        message_bus: Any | None = None,
        run_plan_store: Any | None = None,
    ) -> None:
        if run_plan_store is None:
            from magi.control.session_store import ControlSessionStore

            run_plan_store = ControlSessionStore()
        super().__init__(agent_type=TaskAgentType.CHAT, agent_id=agent_id)
        init_values = locals()
        self._store_runtime_roots(init_values)
        runtime_parts = build_chat_task_agent_runtime_parts(
            self._build_runtime_config(init_values),
            self._build_runtime_callbacks(),
        )
        self._install_runtime_parts(runtime_parts)
        self._bind_runtime_views()

    def _store_runtime_roots(self, init_values: dict[str, Any]) -> None:
        self.llm = init_values["llm_adapter"]
        self._llm_pool = init_values["llm_pool"]
        self.memory = init_values["memory"]
        self.unified_memory = init_values["unified_memory"]
        self.memory_integration = init_values["memory_integration"]
        self._chat_store = init_values["chat_store"]
        self._runtime_trace_store = init_values["runtime_trace_store"]

    def _build_runtime_config(self, init_values: dict[str, Any]) -> ChatTaskAgentRuntimeConfig:
        return ChatTaskAgentRuntimeConfig(
            agent_id=self.agent_id,
            runtime_key=self.runtime_key,
            **{field: init_values[field] for field in _RUNTIME_CONFIG_INIT_FIELDS},
        )

    def _build_runtime_callbacks(self) -> ChatTaskAgentRuntimeCallbacks:
        return ChatTaskAgentRuntimeCallbacks(
            get_event_emitter=lambda: self._event_emitter,
            get_task_agent_manager=lambda: self._task_agent_manager,
            get_sensor_hub=lambda: self._sensor_hub,
            max_fact_memory=self._max_fact_memory,
            release_pending_inputs=self._release_pending_inputs,
            deliver_final_response=self._deliver_final_response_from_postprocess,
            tool_advisory_provider=self._get_tool_advisory,
            session_workspace_provider=self._resolve_session_workspace_path,
        )

    def _bind_runtime_views(self) -> None:
        self._last_batch_facts: list[FactRecord] = []
        self._execution_admission_lock = asyncio.Lock()

        # Keep this alias so existing read paths and tests see the same underlying store.
        self._conversation_history = self._context_assembler._conversation_history
        # Per-session recent-tool-call view; the chat agent (prompt assembly)
        # and postprocess (tool-event sink) both depend on this view
        # directly rather than going through ChatContextAssembler.
        self._tool_state_view = self._context_assembler.tool_state_view

    def _install_runtime_parts(self, runtime_parts: Any) -> None:
        self._chat_read_service_factory = runtime_parts.chat_read_service_factory
        self.prompt_context_assembler = runtime_parts.prompt_context_assembler
        self.prompt_context_renderer = runtime_parts.prompt_context_renderer
        self._chat_read_service = runtime_parts.chat_read_service
        self._attachment_resolver = runtime_parts.attachment_resolver
        self._context_retrieval_service = runtime_parts.context_retrieval_service
        self._context_service = runtime_parts.context_service
        self._context_assembler = runtime_parts.context_assembler
        self._fact_classifier = runtime_parts.fact_classifier
        self._prompt_service = runtime_parts.prompt_service
        self._session_run_coordinator = runtime_parts.session_run_coordinator
        self._transcript_summarizer = runtime_parts.transcript_summarizer
        self._postprocess_service = runtime_parts.postprocess_service
        self.function_calling_orchestrator = runtime_parts.function_calling_orchestrator
        self._handler_registry = runtime_parts.handler_registry
        self._coordinator = runtime_parts.coordinator

    @property
    def postprocess_service(self) -> ChatPostProcessService:
        """Expose the chat post-process service for external wiring."""
        return self._postprocess_service

    async def stop(self) -> None:
        """Stop the active run and every detached post-process task."""
        await super().stop()
        await self._postprocess_service.shutdown_background_tasks()

    async def cancel_postprocess_for_destructive_change(self) -> None:
        """Discard detached memory work before chat or memory deletion."""

        await self._postprocess_service.cancel_background_tasks()

    def has_inflight_work(self) -> bool:
        """Keep the session alive while durable post-processing is unfinished."""

        return (
            super().has_inflight_work() or self._postprocess_service.has_pending_background_work()
        )

    async def _deliver_final_response_from_postprocess(
        self,
        context,
        *,
        content,
        exclude_chat_sse: bool = False,
        exclude_channel_types: Iterable[str] = (),
    ) -> DeliveryFanoutResult:
        coordinator = getattr(self, "_coordinator", None)
        deliver = getattr(coordinator, "deliver_final_chat_response", None)
        if deliver is None:
            return DeliveryFanoutResult()
        delivery_kwargs: dict[str, Any] = {"content": content}
        if exclude_chat_sse:
            delivery_kwargs["exclude_chat_sse"] = True
        excluded_channel_types = tuple(exclude_channel_types)
        if excluded_channel_types:
            delivery_kwargs["exclude_channel_types"] = excluded_channel_types
        return await deliver(context, **delivery_kwargs)

    async def _resolve_session_workspace_path(self, *, user_id: str, session_id: str) -> str | None:
        summary = await self._chat_read_service.aget_session_summary(user_id, session_id)
        return summary.workspace_path if summary is not None else None

    async def _get_tool_advisory(
        self,
        task_context: str | None = None,
        tool_names: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Fetch notable L4 advisories for the coordinator."""
        available_tool_names = list(tool_names or tool_registry.list_tools())
        targeted_mode = bool(tool_names)
        advisories_by_tool = await self._collect_tool_advisories(
            available_tool_names=available_tool_names,
            task_context=task_context,
            targeted_mode=targeted_mode,
            tool_names=tool_names,
            limit=limit,
        )

        if targeted_mode:
            return _ordered_target_tool_advisories(advisories_by_tool, tool_names, limit)

        return _notable_tool_advisories(advisories_by_tool, limit)

    async def _collect_tool_advisories(
        self,
        *,
        available_tool_names: list[str],
        task_context: str | None,
        targeted_mode: bool,
        tool_names: list[str] | None,
        limit: int,
    ) -> dict[str, dict]:
        advisories_by_tool = _advisories_by_tool(
            await self._fetch_l4_tool_advisories(
                task_context=task_context,
                targeted_mode=targeted_mode,
                tool_names=tool_names,
                limit=limit,
            )
        )
        _merge_trace_tool_stats(
            advisories_by_tool,
            await self._fetch_tool_trace_stats(available_tool_names),
        )
        return advisories_by_tool

    async def _fetch_tool_trace_stats(
        self,
        available_tool_names: list[str],
    ) -> dict[str, dict[str, float | int]]:
        if self._runtime_trace_store is None:
            return {}
        try:
            return await self._runtime_trace_store.get_tool_execution_stats(available_tool_names)
        except Exception as exc:
            logger.debug("Failed to fetch runtime trace tool stats: %s", exc)
            return {}

    async def _fetch_l4_tool_advisories(
        self,
        *,
        task_context: str | None,
        targeted_mode: bool,
        tool_names: list[str] | None,
        limit: int,
    ) -> list[dict]:
        if self.unified_memory is None or self.unified_memory.l4 is None:
            return []
        try:
            if targeted_mode:
                return await self.unified_memory.l4.get_tool_advisory(
                    tool_names=list(tool_names or []),
                    task_context=task_context,
                )
            return await self.unified_memory.l4.get_notable_advisories(
                task_context=task_context,
                limit=limit,
            )
        except Exception as exc:
            logger.debug("Failed to fetch L4 tool advisories: %s", exc)
            return []

    async def add_fact(self, fact: FactRecord) -> bool:
        """Admit controls and active-run inputs without starting a second loop."""

        async with self._chat_execution_admission_boundary():
            if await self._request_ingress_replace_at_admission_boundary(fact):
                return True
            if await self._request_ingress_cancel_at_admission_boundary(fact):
                return True
            if self._queue_active_run_input_at_admission_boundary(fact):
                return True
            return await super().add_fact(fact)

    async def add_fact_with_admission(
        self,
        fact: FactRecord,
        *,
        admit: Callable[[], Awaitable[bool]],
    ) -> FactAdmissionResult:
        """Atomically admit a managed root, control, or active-run input."""

        async with self._chat_execution_admission_boundary():
            if self._fact_targets_active_run(fact):
                if not await admit():
                    return FactAdmissionResult(queued=False, superseded=True)
                if await self._request_ingress_replace_at_admission_boundary(fact):
                    return FactAdmissionResult(queued=True)
                if await self._request_ingress_cancel_at_admission_boundary(fact):
                    return FactAdmissionResult(queued=True)
                if self._queue_active_run_input_at_admission_boundary(fact):
                    return FactAdmissionResult(queued=True)
                return FactAdmissionResult(queued=await super().add_fact(fact))
            return await super().add_fact_with_admission(fact, admit=admit)

    async def handle_fact(self, fact: FactRecord) -> None:
        _ = fact

    def _should_end_batch_before(
        self,
        batch: list[FactRecord],
        next_fact: FactRecord,
    ) -> bool:
        """Keep admitted user turns as non-mergeable command boundaries."""

        if next_fact.event_type == EventTypes.USER_MESSAGE and any(
            fact.event_type == EventTypes.USER_MESSAGE for fact in batch
        ):
            return True
        return False

    async def merge_facts(self, new_facts: list[FactRecord]) -> list[FactRecord]:
        executable_facts = [
            fact for fact in new_facts if await self._fact_delivery_is_executable(fact)
        ]
        self._last_batch_facts = list(executable_facts)
        self._active_batch_facts = list(executable_facts)
        if not executable_facts:
            return []
        return await super().merge_facts(executable_facts)

    async def _fact_delivery_is_executable(self, fact: FactRecord) -> bool:
        """Reject a cancelled or superseded admitted fact before execution."""

        if (
            fact.event_type != EventTypes.USER_MESSAGE
            or fact.delivery_attempt_no is None
            or fact.runtime_command_id is None
            or self._chat_store is None
        ):
            return True
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        turn_id = str(payload.get("turn_id") or "").strip()
        if not turn_id:
            logger.warning(
                "Discarding managed chat fact without a turn identity",
                runtime_command_id=fact.runtime_command_id,
            )
            return False
        delivery = await self._chat_store.get_user_turn_delivery(turn_id=turn_id)
        if delivery is None:
            logger.warning(
                "Discarding managed chat fact without a delivery record",
                session_id=str(payload.get("session_id") or ""),
                turn_id=turn_id,
                runtime_command_id=fact.runtime_command_id,
            )
            return False
        executable = (
            delivery.delivery_state == CHAT_DELIVERY_STATE_ADMITTED
            and delivery.delivery_attempt_no == int(fact.delivery_attempt_no)
            and delivery.current_command_id == int(fact.runtime_command_id)
        )
        if not executable:
            logger.info(
                "Discarding non-executable admitted chat fact",
                session_id=str(payload.get("session_id") or ""),
                turn_id=turn_id,
                delivery_state=delivery.delivery_state,
                terminal=(delivery.delivery_state == CHAT_DELIVERY_STATE_TERMINAL),
            )
        return executable

    async def build_context(self, merged_facts: list[FactRecord]) -> ChatRuntimeContext:
        async with self._execution_admission_lock:
            (
                merged_facts,
                batch_facts,
            ) = await self._revalidate_execution_batch(merged_facts)
            if not batch_facts:
                raise TaskAgentBatchDiscarded
            base_context = await super().build_context(merged_facts)
            latest_fact = _latest_runtime_fact(base_context)
            classified = self._fact_classifier.classify(
                agent_id=self.agent_id,
                latest_fact=latest_fact,
                batch_facts=batch_facts,
            )
            self._context_assembler.require_session_id(
                classified.user_id,
                classified.session_id,
            )
            await self._reconcile_finished_active_run(classified.session_id)
            await self._before_execution_run_admission(classified=classified)
            with fresh_task_execution_budget_context():
                run_decision = await self._session_run_coordinator.aroute(classified)
            turn_control = null_run_control()
            if run_decision.active_run is not None:
                turn_control.cancel_token = SessionRunCancelToken(
                    coordinator=self._session_run_coordinator,
                    session_id=classified.session_id,
                    run_id=run_decision.active_run.run_id,
                    revision=int(run_decision.active_run.revision or 0),
                )
                turn_control.input_queue = self._session_run_coordinator.create_run_input_queue(
                    session_id=classified.session_id,
                    run_id=run_decision.active_run.run_id,
                    revision=int(run_decision.active_run.revision or 0),
                    root_turn_id=run_decision.active_run.root_turn_id,
                    on_consumed=self._persist_run_input_supersessions,
                )
            self._register_turn_control(
                classified.session_id,
                run_decision,
                turn_control,
            )
            await self._after_execution_run_admitted(
                classified=classified,
                run_decision=run_decision,
            )

        context_inputs = await self._load_context_inputs(classified, run_decision)

        return self._build_chat_runtime_context(
            base_context=base_context,
            latest_fact=latest_fact,
            batch_facts=batch_facts,
            classified=classified,
            run_decision=run_decision,
            context_inputs=context_inputs,
            turn_control=turn_control,
        )

    async def _before_execution_run_admission(
        self,
        *,
        classified: Any,
    ) -> None:
        """Test seam after final delivery validation and before run creation."""

        _ = classified

    async def _revalidate_execution_batch(
        self,
        merged_facts: list[FactRecord],
    ) -> tuple[list[FactRecord], list[FactRecord]]:
        """Revalidate the transferred batch inside the stop/run boundary."""

        original_batch = list(self._last_batch_facts)
        executable_batch = [
            fact for fact in original_batch if await self._fact_delivery_is_executable(fact)
        ]
        if len(executable_batch) == len(original_batch):
            return merged_facts, executable_batch

        executable_ids = {id(fact) for fact in executable_batch}
        removed_ids = {id(fact) for fact in original_batch if id(fact) not in executable_ids}
        self._last_batch_facts = list(executable_batch)
        self._active_batch_facts = list(executable_batch)
        self._fact_memory = [fact for fact in self._fact_memory if id(fact) not in removed_ids]
        filtered_merged_facts = [fact for fact in merged_facts if id(fact) not in removed_ids]
        return filtered_merged_facts, executable_batch

    async def _after_execution_run_admitted(
        self,
        *,
        classified: Any,
        run_decision: Any,
    ) -> None:
        """Test seam after an active run wins the execution boundary."""

        _ = (classified, run_decision)

    async def _raise_if_execution_cancelled(
        self,
        context: ChatRuntimeContext,
    ) -> None:
        async with self._execution_admission_lock:
            latest_fact = context.latest_fact
            if isinstance(latest_fact, FactRecord) and not await self._fact_delivery_is_executable(
                latest_fact
            ):
                raise TaskAgentBatchDiscarded
            if await context.control.cancel_token.is_cancelled():
                raise TaskAgentBatchDiscarded

    async def _reconcile_finished_active_run(self, session_id: str) -> None:
        """Discard an L0 run whose durable chat surface already finished.

        Durable chat projection and process-local run state commit separately.
        A process can finish the visible result before clearing the live run;
        this check prevents a recovered delivery from joining that stale run.
        """

        active_run = self._session_run_coordinator.get_active_run(session_id)
        if active_run is None or self._chat_store is None:
            return
        root_turn_id = str(active_run.root_turn_id or "").strip()
        if not root_turn_id:
            return
        turn = await self._chat_store.get_turn(root_turn_id)
        if turn is None:
            return
        status = str(turn.status or "").strip().lower()
        terminal = status in {"cancelled", "interrupted", "merged"}
        if status == "completed":
            response_mode = str(turn.response_mode or "").strip().lower()
            terminal = response_mode in {"none", "reaction_only"}
            if not terminal:
                messages = await self._chat_store.list_messages(
                    session_id=turn.session_id,
                )
                terminal = any(
                    message.turn_id == root_turn_id
                    and message.role == "assistant"
                    and message.message_kind == "assistant_final"
                    and message.is_visible
                    and message.is_final
                    for message in messages
                ) or (
                    complete_visible_rhythm_segments(
                        messages,
                        turn_id=root_turn_id,
                    )
                    is not None
                )
        if not terminal:
            return
        completed = self._session_run_coordinator.complete_run(
            session_id=session_id,
            run_id=active_run.run_id,
            revision=active_run.revision,
        )
        if not completed:
            return

    async def _load_context_inputs(self, classified: Any, run_decision: Any) -> _ChatContextInputs:
        session_id = self._context_assembler.require_session_id(
            classified.user_id, classified.session_id
        )
        active_persona_id = await self._resolve_context_persona_id(run_decision.latest_payload)
        history_context = await self._context_assembler.get_or_load_history_context(
            classified.user_id,
            session_id,
            active_persona_id=active_persona_id,
        )
        history_key = self._context_assembler.history_key(classified.user_id, session_id)
        reply_context = await self._resolve_reply_context(run_decision.latest_payload)
        recall_feedback = await self._resolve_recall_feedback_context(run_decision.latest_payload)
        return _ChatContextInputs(
            session_id=session_id,
            active_persona_id=active_persona_id,
            history_context=history_context,
            history=history_context.messages,
            history_key=history_key,
            recent_tool_errors=self._tool_state_view.recent_errors(history_key),
            recent_tool_state=self._tool_state_view.recent_state(history_key),
            reply_context=reply_context,
            recall_feedback=recall_feedback,
            preferences=_resolve_chat_runtime_preferences(),
        )

    def _build_chat_runtime_context(
        self,
        *,
        base_context: TaskAgentRuntimeContext,
        latest_fact: FactRecord | None,
        batch_facts: list[FactRecord],
        classified: Any,
        run_decision: Any,
        context_inputs: _ChatContextInputs,
        turn_control: Any,
    ) -> ChatRuntimeContext:
        return ChatRuntimeContext(
            latest_fact=latest_fact if isinstance(latest_fact, FactRecord) else None,
            recent_facts=_recent_runtime_facts(base_context),
            batch_facts=batch_facts,
            agent_id=self.agent_id,
            agent_type=_runtime_agent_type(base_context),
            runtime_key=_runtime_key(base_context, self.runtime_key),
            user_id=classified.user_id,
            session_id=context_inputs.session_id,
            history_key=context_inputs.history_key,
            history=context_inputs.history,
            conversation_history=context_inputs.history,
            recent_tool_errors=context_inputs.recent_tool_errors,
            recent_tool_state=context_inputs.recent_tool_state,
            latest_user_message=run_decision.planner_user_message,
            incoming_fact_kind=run_decision.planner_fact_kind,
            latest_payload=run_decision.latest_payload,
            user_message_generation=_fact_user_message_generation(
                run_decision.planner_fact,
                latest_fact,
            ),
            active_run=run_decision.active_run,
            session_run_id=(
                run_decision.active_run.run_id if run_decision.active_run is not None else None
            ),
            session_run_revision=(
                run_decision.active_run.revision if run_decision.active_run is not None else 0
            ),
            session_run_disposition=run_decision.run_disposition,
            planner_fact=run_decision.planner_fact,
            planner_fact_kind=run_decision.planner_fact_kind,
            planner_payload=run_decision.latest_payload,
            reply_context=context_inputs.reply_context,
            recall_feedback=context_inputs.recall_feedback,
            session_summary=context_inputs.history_context.session_summary,
            session_origin=context_inputs.history_context.session_origin,
            active_persona_id=context_inputs.active_persona_id,
            streaming_chat_enabled=context_inputs.preferences.streaming_chat_enabled,
            allow_media_grounding_for_conversation=(
                context_inputs.preferences.allow_media_grounding_for_conversation
            ),
            core_model_supports_vision=context_inputs.preferences.core_model_supports_vision,
            core_model_supports_tool_calls=(
                context_inputs.preferences.core_model_supports_tool_calls
            ),
            control=turn_control,
        )

    async def _persist_run_input_supersessions(
        self,
        superseded_turns: list[Any],
    ) -> None:
        """Commit safe-boundary input consumption to chat and trace views."""

        await self._postprocess_service.persist_turn_supersessions(
            superseded_turns=superseded_turns,
            updated_at_ms=now_wall_ms(),
        )

    def _register_turn_control(
        self,
        session_id: str,
        run_decision: Any,
        turn_control: Any,
    ) -> None:
        if run_decision.active_run is None:
            return
        self._session_run_coordinator.register_active_run_control(
            session_id,
            run_decision.active_run.run_id,
            turn_control,
        )

    async def _resolve_context_persona_id(self, latest_payload: object) -> str | None:
        turn_id = str(getattr(latest_payload, "turn_id", "") or "").strip()
        if self._chat_store is not None and turn_id:
            try:
                user_message = await self._chat_store.get_latest_message_for_turn(
                    turn_id,
                    message_kind="user_text",
                )
                if user_message is not None and user_message.persona_id:
                    return str(user_message.persona_id).strip() or None
            except Exception:
                logger.debug("Failed to resolve persona id from user turn", turn_id=turn_id)
        try:
            from magi.personality.persona_repository import PersonaRepository

            repo = PersonaRepository(str(get_runtime_paths().persona_registry_db_path))
            await repo.init()
            active_id = await repo.get_active_id()
        except Exception:
            return None
        return str(active_id or "").strip() or None

    async def admit_context(self, context: ChatRuntimeContext):
        await self._raise_if_execution_cancelled(context)
        result = await self._coordinator.admit_context(context)
        await self._raise_if_execution_cancelled(context)
        return result

    @asynccontextmanager
    async def execution_scope(
        self,
        context: ChatRuntimeContext,
    ) -> AsyncIterator[None]:
        """Rehydrate the root turn's model and worker budget for this admission."""
        root_turn_id = await self._resolve_context_root_turn_id(context)
        async with self._task_budget_scope(root_turn_id):
            yield

    async def _resolve_context_root_turn_id(self, context: object) -> str:
        """Recover the durable budget identity even after the chat actor restarts."""
        latest_payload = getattr(context, "latest_payload", None)
        payload_root = str(getattr(latest_payload, "root_turn_id", "") or "").strip()
        if payload_root:
            return payload_root

        active_run = getattr(context, "active_run", None)
        active_root = str(getattr(active_run, "root_turn_id", "") or "").strip()
        if active_root:
            return active_root

        session_id = str(getattr(context, "session_id", "") or "").strip()
        run_coordinator = getattr(self, "_session_run_coordinator", None)
        get_active_run = getattr(run_coordinator, "get_active_run", None)
        if session_id and callable(get_active_run):
            restored_run = get_active_run(session_id)
            return str(getattr(restored_run, "root_turn_id", "") or "").strip()
        return ""

    @asynccontextmanager
    async def _task_budget_scope(
        self,
        root_turn_id: str,
    ) -> AsyncIterator[None]:
        store = self._durable_task_budget_store()
        if root_turn_id and store is not None:
            async with task_execution_budget_scope(
                root_turn_id=root_turn_id,
                store=store,
            ):
                yield
            return
        if self._chat_store is not None:
            # Product runtime has durable chat storage. Missing identity or a
            # partially wired store must deny model/worker reservations instead
            # of silently resetting a fresh per-admission allowance.
            raise RuntimeError("Durable chat task budget root identity is unavailable")
        async with task_execution_budget_scope():
            yield

    def _durable_task_budget_store(self) -> TaskExecutionBudgetStore | None:
        store = self._chat_store
        required_methods = (
            "ensure_task_execution_budget",
            "reserve_task_execution_budget",
            "release_task_execution_llm_calls",
        )
        if store is None or not all(
            callable(getattr(store, method, None)) for method in required_methods
        ):
            return None
        return cast(TaskExecutionBudgetStore, store)

    async def resolve_capabilities(self, context: ChatRuntimeContext, admission):
        await self._raise_if_execution_cancelled(context)
        result = await self._coordinator.resolve_capabilities(context, admission)
        await self._raise_if_execution_cancelled(context)
        return result

    async def build_execution_request(
        self,
        context: ChatRuntimeContext,
        admission,
        capabilities,
    ) -> ExecutionRequest:
        await self._raise_if_execution_cancelled(context)
        result = await self._coordinator.build_execution_request(
            context,
            admission,
            capabilities,
        )
        await self._raise_if_execution_cancelled(context)
        return result

    async def execute_request(
        self, context: ChatRuntimeContext, request: ExecutionRequest
    ) -> ExecutionResult:
        await self._raise_if_execution_cancelled(context)
        sink = None
        turn_id = str(getattr(context.latest_payload, "turn_id", "") or "").strip() or None
        if (
            context.user_id
            and context.session_id
            and turn_id
            and self._streaming_enabled(context.user_id)
        ):
            sink = self._build_stream_sink(
                user_id=context.user_id,
                session_id=context.session_id,
                turn_id=turn_id,
                persona_id=context.active_persona_id,
            )
        try:
            async with stream_scope(sink, source="chat"):
                return await self._coordinator.execute_request(request)
        except Exception as exc:
            logger.error(
                "ChatTaskAgent LLM execution failed",
                session_id=context.session_id,
                turn_id=turn_id,
                error=str(exc),
                exc_info=True,
            )
            if sink is not None:
                await self._emit_llm_error(context, exc)
            correlation_id = (
                str(context.latest_fact.correlation_id or "").strip()
                if isinstance(context.latest_fact, FactRecord)
                else None
            )
            return ExecutionResult(
                mode=request.mode,
                response_text=_format_llm_error(exc),
                root_user_message=context.latest_user_message,
                correlation_id=correlation_id,
                message_started_at=getattr(request, "message_started_at", None),
                turn_id=turn_id,
                streamed=sink is not None,
            )

    def _streaming_enabled(self, _user_id: str) -> bool:
        try:
            return (
                bool(get_user_preference("streaming_chat_enabled", False))
                and not is_conversation_rhythm_enabled()
            )
        except Exception:
            return False

    async def finalize_result(self, context: ChatRuntimeContext, result: ExecutionResult) -> None:
        try:
            await self._postprocess_service.handle(context, result)
        finally:
            # Unregister the turn's RunControl now that the turn is done.
            # The bundle's signals (asyncio.Event etc.) are not persistable
            # so keeping a dead reference accomplishes nothing.
            if context.session_id and context.session_run_id:
                self._session_run_coordinator.unregister_active_run_control(
                    context.session_id, context.session_run_id
                )

    async def handle_batch_failure(
        self,
        batch: list[FactRecord],
        *,
        error: BaseException,
        stage: str,
        context: ChatRuntimeContext | None,
    ) -> None:
        """Close one failed admitted chat turn without replaying its work."""

        _ = context
        delay_seconds = _PIPELINE_FAILURE_RETRY_INITIAL_SECONDS
        while True:
            try:
                source_fact = await self._resolve_pipeline_failure_source_fact(
                    batch=batch,
                    context=context,
                )
                if source_fact is None:
                    return
                await self._finalize_failed_batch_once(
                    source_fact=source_fact,
                    error=error,
                    stage=stage,
                )
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Chat pipeline failure finalization retry failed",
                    stage=stage,
                    exc_info=True,
                )
                await asyncio.sleep(max(0.0, delay_seconds))
                delay_seconds = min(
                    max(
                        _PIPELINE_FAILURE_RETRY_INITIAL_SECONDS,
                        delay_seconds * 2,
                    ),
                    _PIPELINE_FAILURE_RETRY_MAX_SECONDS,
                )

    async def _resolve_pipeline_failure_source_fact(
        self,
        *,
        batch: list[FactRecord],
        context: ChatRuntimeContext | None,
    ) -> FactRecord | None:
        """Resolve the admitted root turn owned by a failed continuation fact."""

        def _managed_user_fact(fact: FactRecord) -> bool:
            return (
                fact.event_type == EventTypes.USER_MESSAGE
                and fact.delivery_attempt_no is not None
                and fact.runtime_command_id is not None
            )

        source_fact = next(
            (fact for fact in reversed(batch) if _managed_user_fact(fact)),
            None,
        )
        if source_fact is not None:
            return source_fact

        session_id = str(context.session_id if context is not None else "").strip()
        if not session_id:
            for fact in reversed(batch):
                payload = fact.payload if isinstance(fact.payload, dict) else {}
                session_id = str(payload.get("session_id") or "").strip()
                if session_id:
                    break
        if not session_id:
            return None
        active_run = self._session_run_coordinator.get_active_run(session_id)
        if active_run is None:
            return None
        root_turn_id = str(active_run.root_turn_id or "").strip()
        if not root_turn_id:
            return None

        for fact in reversed(self._fact_memory):
            if not _managed_user_fact(fact):
                continue
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            if (
                str(payload.get("session_id") or "").strip() == session_id
                and str(payload.get("turn_id") or "").strip() == root_turn_id
            ):
                return fact

        if self._chat_store is None:
            return None
        delivery = await self._chat_store.get_user_turn_delivery(
            turn_id=root_turn_id,
        )
        if (
            delivery is None
            or delivery.current_command_id is None
            or delivery.delivery_attempt_no < 0
        ):
            return None
        try:
            envelope = parse_user_turn_runtime_envelope(delivery)
        except ValueError:
            logger.warning(
                "Cannot reconstruct failed chat root from its delivery envelope",
                session_id=session_id,
                turn_id=root_turn_id,
                exc_info=True,
            )
            return None
        return FactRecord(
            agent_id=self.runtime_key,
            agent_type=TaskAgentType.CHAT.value,
            agent_instance_id=session_id,
            event_type=EventTypes.USER_MESSAGE,
            payload={
                "content": envelope.message,
                "attachments": list(envelope.attachments),
                "author_type": "user",
                "content_type": "text",
                "user_id": envelope.user_id,
                "runtime_namespace": envelope.runtime_namespace,
                "session_id": envelope.session_id,
                "turn_id": envelope.turn_id,
                "workspace_path": envelope.workspace_path,
                "timestamp": float(delivery.created_at_ms) / 1000.0,
                "metadata": dict(envelope.metadata),
                "source": envelope.source,
                "interaction_kind": envelope.interaction_kind,
            },
            timestamp=float(delivery.created_at_ms) / 1000.0,
            correlation_id=f"user_message:{delivery.message_id}",
            delivery_attempt_no=delivery.delivery_attempt_no,
            runtime_command_id=delivery.current_command_id,
        )

    async def _finalize_failed_batch_once(
        self,
        *,
        source_fact: FactRecord,
        error: BaseException,
        stage: str,
    ) -> None:
        """Finalize one failed delivery without rerunning the original pipeline."""

        finalized = await self._postprocess_service.handle_pipeline_failure(
            source_fact=source_fact,
            error=error,
            stage=stage,
        )
        if not finalized:
            return

        payload = source_fact.payload if isinstance(source_fact.payload, dict) else {}
        session_id = str(payload.get("session_id") or "").strip()
        turn_id = str(payload.get("turn_id") or "").strip()
        if not session_id or not turn_id:
            return
        active_run = self._session_run_coordinator.get_active_run(session_id)
        if active_run is None or active_run.root_turn_id != turn_id:
            return
        completed, pending_inputs = self._session_run_coordinator.complete_run_with_pending_inputs(
            session_id=session_id,
            run_id=active_run.run_id,
            revision=active_run.revision,
        )
        if not completed:
            return
        await self._postprocess_service.release_pending_inputs_after_run_completion(
            session_id=session_id,
            run_id=active_run.run_id,
            revision=active_run.revision,
            pending_inputs=pending_inputs,
        )

    def get_conversation_history(self, user_id: str, session_id: str) -> list[dict]:
        return self._context_assembler.get_conversation_history(user_id, session_id)

    def clear_conversation_history(self, user_id: str, session_id: str) -> None:
        self._context_assembler.clear_conversation_history(user_id, session_id)

    def get_llm_max_tokens(self) -> int:
        try:
            return int(get_config().llm.max_tokens)
        except Exception:
            return 4096


def _latest_runtime_fact(base_context: Any) -> FactRecord | None:
    if not isinstance(base_context, TaskAgentRuntimeContext):
        return None
    latest_fact = base_context.latest_fact
    return latest_fact if isinstance(latest_fact, FactRecord) else None


def _fact_user_message_generation(*facts: Any) -> int | None:
    for fact in facts:
        if isinstance(fact, FactRecord) and fact.user_message_generation is not None:
            return int(fact.user_message_generation)
    return None


def _recent_runtime_facts(base_context: Any) -> list[FactRecord]:
    if not isinstance(base_context, TaskAgentRuntimeContext):
        return []
    return list(base_context.recent_facts)


def _runtime_agent_type(base_context: Any) -> str:
    if not isinstance(base_context, TaskAgentRuntimeContext):
        return TaskAgentType.CHAT.value
    return str(base_context.agent_type)


def _runtime_key(base_context: Any, fallback: str) -> str:
    if not isinstance(base_context, TaskAgentRuntimeContext):
        return fallback
    return str(base_context.runtime_key)


def _advisories_by_tool(base_advisories: list[dict]) -> dict[str, dict]:
    advisories_by_tool: dict[str, dict] = {}
    for advisory in base_advisories:
        tool_name = str(advisory.get("tool_name") or "").strip()
        if tool_name:
            advisories_by_tool[tool_name] = dict(advisory)
    return advisories_by_tool


def _merge_trace_tool_stats(
    advisories_by_tool: dict[str, dict],
    trace_stats: dict[str, dict[str, float | int]],
) -> None:
    for tool_name, stats in trace_stats.items():
        total_calls = int(stats.get("total_calls") or 0)
        if total_calls <= 0:
            continue
        _merge_one_trace_tool_stat(advisories_by_tool, tool_name, stats, total_calls)


def _merge_one_trace_tool_stat(
    advisories_by_tool: dict[str, dict],
    tool_name: str,
    stats: dict[str, float | int],
    total_calls: int,
) -> None:
    success_rate = float(stats.get("success_rate") or 0.0)
    advisory = advisories_by_tool.setdefault(
        tool_name,
        {
            "tool_name": tool_name,
            "available": True,
            "breaker_state": "closed",
            "strategy_hint": None,
            "context_fit": 0.0,
        },
    )
    advisory["success_rate"] = success_rate
    advisory["total_attempts"] = total_calls
    advisory["failure_count"] = int(stats.get("failed_calls") or 0)
    advisory["stats_source"] = "runtime_trace.trace_tools"
    if success_rate < 0.7 and total_calls >= 3:
        advisory["risk_note"] = f"Low success rate ({success_rate:.0%} over {total_calls} attempts)"


def _ordered_target_tool_advisories(
    advisories_by_tool: dict[str, dict],
    tool_names: list[str] | None,
    limit: int,
) -> list[dict]:
    ordered: list[dict] = []
    for tool_name in list(tool_names or []):
        advisory = advisories_by_tool.get(tool_name)
        if advisory is not None:
            ordered.append(advisory)
    return ordered[:limit]


def _notable_tool_advisories(advisories_by_tool: dict[str, dict], limit: int) -> list[dict]:
    return [
        advisory
        for advisory in advisories_by_tool.values()
        if advisory.get("strategy_hint") is not None
        or advisory.get("breaker_state") != "closed"
        or (
            float(advisory.get("success_rate") or 0.0) < 0.7
            and int(advisory.get("total_attempts") or 0) >= 3
        )
    ][:limit]


def _resolve_chat_runtime_preferences() -> _ChatRuntimePreferences:
    streaming_chat_enabled = bool(get_user_preference("streaming_chat_enabled", False))
    if is_conversation_rhythm_enabled():
        streaming_chat_enabled = False
    core_selection = get_config().llm.selections.get("core")
    core_model_supports_vision = bool(
        getattr(getattr(core_selection, "capabilities", None), "vision", False)
    )
    core_model_supports_tool_calls = bool(
        getattr(getattr(core_selection, "capabilities", None), "tool_calling", True)
    )
    return _ChatRuntimePreferences(
        streaming_chat_enabled=streaming_chat_enabled,
        allow_media_grounding_for_conversation=bool(
            get_user_preference("allow_media_grounding_for_conversation", False)
        ),
        core_model_supports_vision=core_model_supports_vision,
        core_model_supports_tool_calls=core_model_supports_tool_calls,
    )
