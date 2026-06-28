"""Runtime task agent for chat facts."""

from __future__ import annotations

from typing import Any, Callable

from magi.agent.cancel import SessionRunCancelToken
from magi.control.run_control import null_run_control
from magi.agent.trace import now_wall_ms
from magi.chat import ChatProjector, ChatReadService, ChatStore
from magi.config import get_config, get_user_preference
from magi.core.logger import get_logger
from magi.agent.runtime.contracts import FactRecord
from magi.agent.runtime.task_agent import TaskAgent, TaskAgentRuntimeContext
from magi.agent.runtime.types import TaskAgentType
from magi.tools.registry import tool_registry
from magi.runtime_trace import RuntimeTraceStore
from magi.utils.runtime import get_runtime_paths
from magi.llm.streaming_events import stream_scope
from magi.agent.task_agents.handlers import (
    IntentDecision,
    ChatRuntimeContext,
    ExecutionRequest,
    ExecutionResult,
    ToolSelection,
)
from magi.chat.task_agent.postprocess_service import ChatPostProcessService
from magi.chat.task_agent.reply_context import ChatReplyContextMixin
from .rhythm import (
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


class ChatTaskAgent(
    ChatSessionControlMixin,
    ChatStreamingMixin,
    ChatReplyContextMixin,
    TaskAgent[
        ChatRuntimeContext,
        IntentDecision,
        ToolSelection,
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
        hybrid_retrieval_service=None,
        memory_integration=None,
        history_cache_max_sessions: int = 500,
        history_fetch_limit: int = 1000,
        skill_runner=None,
        runtime_trace_store: RuntimeTraceStore | None = None,
        chat_store: ChatStore | None = None,
        chat_projector: ChatProjector | None = None,
        chat_read_service_factory: Callable[[], ChatReadService] | None = None,
        background_dispatcher: Any | None = None,
        background_launch_service: Any | None = None,
        permission_gateway_provider: Callable[[], Any] | None = None,
        control_session_store_provider: Callable[[], Any] | None = None,
        delivery_dispatcher_resolver: Callable[[], Any] | None = None,
        conversation_log_resolver: Callable[[], Any] | None = None,
        message_bus: Any | None = None,
    ) -> None:
        super().__init__(agent_type=TaskAgentType.CHAT, agent_id=agent_id)
        self.llm = llm_adapter
        self._llm_pool = llm_pool
        self.memory = memory
        self.unified_memory = unified_memory
        self.memory_integration = memory_integration
        self._chat_store = chat_store
        self._runtime_trace_store = runtime_trace_store
        runtime_parts = build_chat_task_agent_runtime_parts(
            ChatTaskAgentRuntimeConfig(
                agent_id=self.agent_id,
                runtime_key=self.runtime_key,
                llm_adapter=llm_adapter,
                llm_pool=llm_pool,
                memory=memory,
                unified_memory=unified_memory,
                hybrid_retrieval_service=hybrid_retrieval_service,
                history_cache_max_sessions=history_cache_max_sessions,
                history_fetch_limit=history_fetch_limit,
                skill_runner=skill_runner,
                runtime_trace_store=runtime_trace_store,
                chat_store=chat_store,
                chat_projector=chat_projector,
                chat_read_service_factory=chat_read_service_factory,
                background_dispatcher=background_dispatcher,
                background_launch_service=background_launch_service,
                permission_gateway_provider=permission_gateway_provider,
                control_session_store_provider=control_session_store_provider,
                delivery_dispatcher_resolver=delivery_dispatcher_resolver,
                conversation_log_resolver=conversation_log_resolver,
                message_bus=message_bus,
            ),
            ChatTaskAgentRuntimeCallbacks(
                get_event_emitter=lambda: self._event_emitter,
                get_task_agent_manager=lambda: self._task_agent_manager,
                get_sensor_hub=lambda: self._sensor_hub,
                max_fact_memory=self._max_fact_memory,
                drain_deferred_turns=self._drain_deferred_turns,
                deliver_final_response=self._deliver_final_response_from_postprocess,
                tool_advisory_provider=self._get_tool_advisory,
                session_workspace_provider=self._resolve_session_workspace_path,
                persist_turn_supersessions=self._persist_turn_supersessions_from_handler,
            ),
        )
        self._chat_read_service_factory = runtime_parts.chat_read_service_factory
        self.context_decider = runtime_parts.context_decider
        self.prompt_context_assembler = runtime_parts.prompt_context_assembler
        self.prompt_context_renderer = runtime_parts.prompt_context_renderer
        self._chat_read_service = runtime_parts.chat_read_service
        self._attachment_resolver = runtime_parts.attachment_resolver
        self._context_retrieval_service = runtime_parts.context_retrieval_service
        self._context_service = runtime_parts.context_service
        self._context_assembler = runtime_parts.context_assembler
        self._fact_classifier = runtime_parts.fact_classifier
        self._prompt_service = runtime_parts.prompt_service
        self._interruption_classifier = runtime_parts.interruption_classifier
        self._session_run_coordinator = runtime_parts.session_run_coordinator
        self._planning_service = runtime_parts.planning_service
        self._orchestration_store = runtime_parts.orchestration_store
        self._task_orchestrator = runtime_parts.task_orchestrator
        self._transcript_summarizer = runtime_parts.transcript_summarizer
        self._postprocess_service = runtime_parts.postprocess_service
        self.function_calling_orchestrator = (
            runtime_parts.function_calling_orchestrator
        )
        self._handler_registry = runtime_parts.handler_registry
        self._coordinator = runtime_parts.coordinator
        self._last_batch_facts: list[FactRecord] = []

        # Keep this alias so existing read paths and tests see the same underlying store.
        self._conversation_history = self._context_assembler._conversation_history
        # Per-session recent-tool-call view; the chat agent (prompt assembly)
        # and postprocess (tool-event sink) both depend on this view
        # directly rather than going through ChatContextAssembler.
        self._tool_state_view = self._context_assembler.tool_state_view

    @property
    def postprocess_service(self) -> ChatPostProcessService:
        """Expose the chat post-process service for external wiring."""
        return self._postprocess_service

    async def _deliver_final_response_from_postprocess(self, context, *, content):
        coordinator = getattr(self, "_coordinator", None)
        deliver = getattr(coordinator, "deliver_final_chat_response", None)
        if deliver is None:
            return []
        return await deliver(context, content=content)

    async def _persist_turn_supersessions_from_handler(
        self,
        superseded_turns: list[Any],
        updated_at_ms: int,
    ) -> None:
        """Bridge STEER supersessions from handler -> post-process service.

        Exposed as a callable on :class:`ChatHandlerDependencies` so the
        function-calling handler can emit STEER supersession bookkeeping
        whenever it drains persisted STEER pending turns into the inbox.
        """
        await self._postprocess_service.persist_turn_supersessions(
            superseded_turns=superseded_turns,
            updated_at_ms=updated_at_ms,
        )

    async def _resolve_session_workspace_path(
        self, *, user_id: str, session_id: str
    ) -> str | None:
        summary = await self._chat_read_service.aget_session_summary(
            user_id, session_id
        )
        return summary.workspace_path if summary is not None else None

    async def _get_tool_advisory(
        self,
        task_context: str | None = None,
        tool_names: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Fetch notable L4 advisories for the coordinator."""
        available_tool_names = list(tool_names or tool_registry.list_tools())
        trace_stats: dict[str, dict[str, float | int]] = {}
        if self._runtime_trace_store is not None:
            try:
                trace_stats = await self._runtime_trace_store.get_tool_execution_stats(
                    available_tool_names
                )
            except Exception as exc:
                logger.debug("Failed to fetch runtime trace tool stats: %s", exc)

        advisories_by_tool: dict[str, dict] = {}
        targeted_mode = bool(tool_names)
        if self.unified_memory is None or self.unified_memory.l4 is None:
            base_advisories = []
        else:
            try:
                if targeted_mode:
                    base_advisories = await self.unified_memory.l4.get_tool_advisory(
                        tool_names=list(tool_names or []),
                        task_context=task_context,
                    )
                else:
                    base_advisories = await self.unified_memory.l4.get_notable_advisories(
                        task_context=task_context,
                        limit=limit,
                    )
            except Exception as exc:
                logger.debug("Failed to fetch L4 tool advisories: %s", exc)
                base_advisories = []
        for advisory in base_advisories:
            tool_name = str(advisory.get("tool_name") or "").strip()
            if tool_name:
                advisories_by_tool[tool_name] = dict(advisory)

        for tool_name, stats in trace_stats.items():
            total_calls = int(stats.get("total_calls") or 0)
            if total_calls <= 0:
                continue
            success_rate = float(stats.get("success_rate") or 0.0)
            failed_calls = int(stats.get("failed_calls") or 0)
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
            advisory["failure_count"] = failed_calls
            advisory["stats_source"] = "runtime_trace.trace_tools"
            if success_rate < 0.7 and total_calls >= 3:
                advisory["risk_note"] = (
                    f"Low success rate ({success_rate:.0%} over {total_calls} attempts)"
                )

        if targeted_mode:
            ordered: list[dict] = []
            for tool_name in list(tool_names or []):
                advisory = advisories_by_tool.get(tool_name)
                if advisory is not None:
                    ordered.append(advisory)
            return ordered[:limit]

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

    async def add_fact(self, fact: FactRecord) -> bool:
        """Enqueue the fact, fast-pathing obvious INTERRUPT user turns.

        When a USER_MESSAGE arrives while an earlier run is still executing
        and the text matches the INTERRUPT rule patterns, we proactively
        call ``request_cancel`` on the coordinator so the in-flight
        execution can bail out at the next ``cancel_token`` probe — even
        before the run loop gets a chance to pull the fact off the queue
        and classify it.
        """
        await self._request_ingress_interrupt(fact)
        return await super().add_fact(fact)

    async def handle_fact(self, fact: FactRecord) -> None:
        _ = fact

    async def merge_facts(self, new_facts: list[FactRecord]) -> list[FactRecord]:
        self._last_batch_facts = list(new_facts)
        return await super().merge_facts(new_facts)

    async def build_context(self, merged_facts: list[FactRecord]) -> ChatRuntimeContext:
        base_context = await super().build_context(merged_facts)
        batch_facts = list(self._last_batch_facts)
        latest_fact = (
            base_context.latest_fact
            if isinstance(base_context, TaskAgentRuntimeContext)
            else None
        )
        classified = self._fact_classifier.classify(
            agent_id=self.agent_id,
            latest_fact=latest_fact,
            batch_facts=batch_facts,
        )
        run_decision = await self._session_run_coordinator.aroute(classified)
        if run_decision.superseded_turns:
            updated_at_ms = (
                int(latest_fact.timestamp * 1000)
                if isinstance(latest_fact, FactRecord)
                else now_wall_ms()
            )
            await self._postprocess_service.persist_turn_supersessions(
                superseded_turns=run_decision.superseded_turns,
                updated_at_ms=updated_at_ms,
            )
        session_id = self._context_assembler.require_session_id(
            classified.user_id, classified.session_id
        )
        active_persona_id = await self._resolve_context_persona_id(
            run_decision.latest_payload
        )
        history_context = await self._context_assembler.get_or_load_history_context(
            classified.user_id,
            session_id,
            active_persona_id=active_persona_id,
        )
        history = history_context.messages
        recent_tool_errors = self._tool_state_view.recent_errors(
            self._context_assembler.history_key(classified.user_id, session_id)
        )
        recent_tool_state = self._tool_state_view.recent_state(
            self._context_assembler.history_key(classified.user_id, session_id)
        )
        active_orchestrations = await self._orchestration_store.list_orchestrations(
            user_id=classified.user_id,
            session_id=session_id,
            statuses=["running", "aggregating"],
        )
        reply_context = await self._resolve_reply_context(run_decision.latest_payload)
        streaming_chat_enabled = bool(
            get_user_preference("streaming_chat_enabled", False)
        )
        if is_conversation_rhythm_enabled():
            streaming_chat_enabled = False
        allow_media_grounding_for_conversation = bool(
            get_user_preference("allow_media_grounding_for_conversation", False)
        )
        core_selection = get_config().llm.selections.get("core")
        core_model_supports_vision = bool(
            getattr(getattr(core_selection, "capabilities", None), "vision", False)
        )
        # Build a fresh RunControl bundle for this turn. The signals
        # (retract, suspend, detach, steer) are functional — fired via
        # the SessionRunCoordinator's request_* methods or future
        # detach/steer entry points.
        turn_control = null_run_control()
        # Wire the real SessionRunCancelToken into the bundle so external
        # cancel calls (SessionRunCoordinator.request_cancel / UI cancel
        # button) flow through context.control.cancel_token to all three
        # execution paths (Direct / FC / Orchestration). Without this,
        # the bundle's cancel_token is a null_cancel_token() no-op.
        if run_decision.active_run is not None:
            turn_control.cancel_token = SessionRunCancelToken(
                coordinator=self._session_run_coordinator,
                session_id=session_id,
                run_id=run_decision.active_run.run_id,
                revision=int(run_decision.active_run.revision or 0),
            )
        # Register the bundle with the session store so external callers
        # (SessionRunCoordinator.request_retract, future cancel/detach
        # entry points) can fire its signals at the live in-flight run.
        if run_decision.active_run is not None:
            self._session_run_coordinator.register_active_run_control(
                session_id, run_decision.active_run.run_id, turn_control
            )
        return ChatRuntimeContext(
            latest_fact=latest_fact if isinstance(latest_fact, FactRecord) else None,
            recent_facts=list(
                base_context.recent_facts
                if isinstance(base_context, TaskAgentRuntimeContext)
                else []
            ),
            batch_facts=batch_facts,
            agent_id=self.agent_id,
            agent_type=str(
                base_context.agent_type
                if isinstance(base_context, TaskAgentRuntimeContext)
                else TaskAgentType.CHAT.value
            ),
            runtime_key=str(
                base_context.runtime_key
                if isinstance(base_context, TaskAgentRuntimeContext)
                else self.runtime_key
            ),
            user_id=classified.user_id,
            session_id=session_id,
            history_key=self._context_assembler.history_key(
                classified.user_id, session_id
            ),
            history=history,
            conversation_history=history,
            active_orchestrations=[item.to_dict() for item in active_orchestrations],
            recent_tool_errors=recent_tool_errors,
            recent_tool_state=recent_tool_state,
            latest_user_message=run_decision.planner_user_message,
            incoming_fact_kind=run_decision.planner_fact_kind,
            latest_payload=run_decision.latest_payload,
            active_run=run_decision.active_run,
            session_run_id=(
                run_decision.active_run.run_id
                if run_decision.active_run is not None
                else None
            ),
            session_run_revision=(
                run_decision.active_run.revision
                if run_decision.active_run is not None
                else 0
            ),
            session_run_disposition=run_decision.run_disposition,
            planner_fact=run_decision.planner_fact,
            planner_fact_kind=run_decision.planner_fact_kind,
            planner_payload=run_decision.latest_payload,
            pending_turns=list(run_decision.checkpoint_pending_turns),
            reply_context=reply_context,
            session_summary=history_context.session_summary,
            session_origin=history_context.session_origin,
            active_persona_id=active_persona_id,
            streaming_chat_enabled=streaming_chat_enabled,
            allow_media_grounding_for_conversation=allow_media_grounding_for_conversation,
            core_model_supports_vision=core_model_supports_vision,
            control=turn_control,
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
                logger.debug(
                    "Failed to resolve persona id from user turn", turn_id=turn_id
                )
        try:
            from magi.personality.persona_repository import PersonaRepository

            repo = PersonaRepository(str(get_runtime_paths().persona_registry_db_path))
            await repo.init()
            active_id = await repo.get_active_id()
        except Exception:
            return None
        return str(active_id or "").strip() or None

    async def match_intent(self, context: ChatRuntimeContext):
        return await self._coordinator.match_intent(context)

    async def match_tools(self, context: ChatRuntimeContext, intent_result):
        return await self._coordinator.match_tools(context, intent_result)

    async def assemble_llm_params(
        self,
        context: ChatRuntimeContext,
        intent_result,
        tool_result,
    ) -> ExecutionRequest:
        return await self._coordinator.assemble_request(
            context, intent_result, tool_result
        )

    async def call_llm(
        self, context: ChatRuntimeContext, llm_params: ExecutionRequest
    ) -> ExecutionResult:
        sink = None
        turn_id = (
            str(getattr(context.latest_payload, "turn_id", "") or "").strip() or None
        )
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
                return await self._coordinator.execute(llm_params)
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
                mode=llm_params.mode,
                response_text=_format_llm_error(exc),
                root_user_message=context.latest_user_message,
                correlation_id=correlation_id,
                message_started_at=getattr(llm_params, "message_started_at", None),
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

    async def parse_result(
        self, context: ChatRuntimeContext, raw_result: ExecutionResult
    ) -> None:
        try:
            await self._postprocess_service.handle(context, raw_result)
        finally:
            # Unregister the turn's RunControl now that the turn is done.
            # The bundle's signals (asyncio.Event etc.) are not persistable
            # so keeping a dead reference accomplishes nothing.
            if context.session_id and context.session_run_id:
                self._session_run_coordinator.unregister_active_run_control(
                    context.session_id, context.session_run_id
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
