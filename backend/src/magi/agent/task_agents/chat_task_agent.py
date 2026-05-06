"""Runtime task agent for chat facts."""

from __future__ import annotations

from typing import Any, Callable

from ...agent.orchestration import get_orchestration_store
from ...agent.task_orchestrator import TaskOrchestrator
from ...agent.trace import now_wall_ms
from ...chat import ChatProjector, ChatReadService, ChatStore
from ...config import get_config, get_user_preference
from ...core.logger import get_logger
from ...agent.runtime.contracts import FactRecord
from ...agent.runtime.task_agent import TaskAgent, TaskAgentRuntimeContext
from ...agent.runtime.types import TaskAgentType
from ...context import (
    ContextAssemblyService,
    ContextRetrievalService,
    PromptContextAssembler,
    PromptContextRenderer,
)
from ...context.user_profile_service import UserProfileService
from ...tools.context_decider import ContextDecider
from ...tools.registry import tool_registry
from ...runtime_trace import RuntimeTraceStore
from ...utils.runtime import get_runtime_paths
from ..execution.function_calling import FunctionCallingOrchestrator
from ...llm.streaming_events import stream_scope
from .chat.interruption_classifier import InterruptionClassifier
from .chat import (
    ChatExecutionCoordinator,
    ChatFactClassifier,
    ChatHistoryService,
    IntentDecision,
    ChatPlanningService,
    ChatPostProcessService,
    ChatPromptService,
    ChatRuntimeContext,
    ExecutionHandlerRegistry,
    ExecutionRequest,
    ExecutionResult,
    SessionRunCoordinator,
    SessionRunStore,
    ToolSelection,
)
from .chat.direct_handler import DirectLLMHandler
from .chat.explore_render import ExploreRenderHandler
from .chat.handlers import (
    ChatHandlerDependencies,
    FunctionCallingHandler,
    build_common_handler_dependencies,
)
from .chat.reply_context import ChatReplyContextMixin
from .chat.rhythm import ResponseRhythmPlanner, is_conversation_rhythm_enabled
from .chat.session_control import ChatSessionControlMixin
from .chat.streaming import ChatStreamingMixin, format_llm_error as _format_llm_error
from .chat.transcript_summarizer import ChatTranscriptSummarizer
from .common import (
    FactOnlyHandler,
    OrchestrationLaunchHandler,
    OrchestrationUpdateHandler,
)

logger = get_logger(__name__)


def _default_chat_read_service_factory() -> ChatReadService:
    from ...chat import get_chat_read_service

    return get_chat_read_service()


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
    ) -> None:
        super().__init__(agent_type=TaskAgentType.CHAT, agent_id=agent_id)
        self.llm = llm_adapter
        self._llm_pool = llm_pool
        self.memory = memory
        self.unified_memory = unified_memory
        self.memory_integration = memory_integration
        self._chat_store = chat_store
        self._runtime_trace_store = runtime_trace_store
        self._chat_read_service_factory = (
            chat_read_service_factory or _default_chat_read_service_factory
        )
        self.context_decider = ContextDecider(
            tool_registry=tool_registry,
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
        )
        self.prompt_context_assembler = PromptContextAssembler(
            tool_registry=tool_registry,
            user_profile_service=UserProfileService(unified_memory=unified_memory),
        )
        self.prompt_context_renderer = PromptContextRenderer()
        self._chat_read_service = self._chat_read_service_factory()
        self._context_retrieval_service = ContextRetrievalService(
            unified_memory=unified_memory,
            retrieval_service=hybrid_retrieval_service,
        )
        self._context_service = ContextAssemblyService(
            agent_id=self.agent_id,
            agent_type=str(
                self.agent_type.value
                if hasattr(self.agent_type, "value")
                else self.agent_type
            ),
            prompt_context_assembler=self.prompt_context_assembler,
            prompt_context_renderer=self.prompt_context_renderer,
            retrieval_memory_provider=self._context_retrieval_service.build_retrieved_memory_payload,
            memory=memory,
            session_workspace_provider=self._resolve_session_workspace_path,
        )

        runtime_paths = get_runtime_paths()
        self._history_service = ChatHistoryService(
            l1_db_path=runtime_paths.l1_memory_db_path,
            history_cache_max_sessions=history_cache_max_sessions,
            history_fetch_limit=history_fetch_limit,
            chat_store=chat_store,
            chat_read_service_factory=self._chat_read_service_factory,
            scenario_llm_pool=llm_pool,
            llm_adapter=llm_adapter,
        )
        self._fact_classifier = ChatFactClassifier()
        self._prompt_service = ChatPromptService(
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
        )
        self._interruption_classifier = InterruptionClassifier(
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
        )
        self._session_run_coordinator = SessionRunCoordinator(
            run_store=SessionRunStore(
                l0_store=(unified_memory.l0 if unified_memory is not None else None),
            ),
            interruption_classifier=self._interruption_classifier,
        )
        self._planning_service = ChatPlanningService(
            agent_id=self.agent_id,
            runtime_key=self.runtime_key,
            context_service=self._context_service,
            prompt_service=self._prompt_service,
            history_service=self._history_service,
            tool_registry=tool_registry,
            parent_task_agent_type=TaskAgentType.CHAT.value,
        )
        self._orchestration_store = get_orchestration_store()
        self._task_orchestrator = TaskOrchestrator(
            runtime_key=self.runtime_key,
            tool_registry=tool_registry,
            plan_subtasks=self._planning_service.generate_subtask_plan,
            aggregate_orchestration=self._planning_service.aggregate_orchestration,
            register_user_message=self._history_service.append_user_message,
            parent_task_agent_type=TaskAgentType.CHAT.value,
            session_workspace_provider=self._resolve_session_workspace_path,
            control_session_store_provider=control_session_store_provider,
        )
        # Initialize trace read service for enriching AI_RESPONSE events
        from ...api.services.chat_trace.read_service import ChatTraceReadService

        try:
            trace_read_service = ChatTraceReadService()
        except Exception:
            trace_read_service = None
        self._transcript_summarizer = ChatTranscriptSummarizer(
            chat_store=chat_store,
            scenario_llm_pool=llm_pool,
            llm_adapter=llm_adapter,
        )

        self._postprocess_service = ChatPostProcessService(
            agent_id=self.agent_id,
            history_service=self._history_service,
            get_event_emitter=lambda: self._event_emitter,
            get_task_agent_manager=lambda: self._task_agent_manager,
            get_sensor_hub=lambda: self._sensor_hub,
            memory=memory,
            unified_memory=unified_memory,
            max_fact_memory=self._max_fact_memory,
            trace_read_service=trace_read_service,
            runtime_trace_store=runtime_trace_store,
            chat_store=chat_store,
            chat_projector=chat_projector,
            chat_read_service_factory=self._chat_read_service_factory,
            complete_session_run=lambda session_id, run_id, revision: self._session_run_coordinator.complete_run(
                session_id=session_id,
                run_id=run_id,
                revision=revision,
            ),
            resolve_session_run_status=lambda session_id, run_id, revision: self._session_run_coordinator.get_run_status(
                session_id=session_id,
                run_id=run_id,
                revision=revision,
            ),
            drain_deferred_turns=self._drain_deferred_turns,
            response_rhythm_planner=ResponseRhythmPlanner(
                prompt_service=self._prompt_service
            ),
            transcript_summarizer=self._transcript_summarizer,
            event_bus=self._resolve_message_bus(),
        )
        self.function_calling_orchestrator = FunctionCallingOrchestrator(
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
            tool_registry=tool_registry,
            skill_runner=skill_runner,
            tool_result_callback=self._postprocess_service.record_tool_interaction,
            loop_event_callback=self._postprocess_service.record_tool_loop_fact,
            runtime_trace_store=runtime_trace_store,
            scenario_llm_pool=llm_pool,
            permission_gateway_provider=permission_gateway_provider,
        )
        handler_deps = ChatHandlerDependencies(
            context_service=self._context_service,
            prompt_service=self._prompt_service,
            planning_service=self._planning_service,
            function_calling_orchestrator=self.function_calling_orchestrator,
            task_orchestrator=self._task_orchestrator,
            history_service=self._history_service,
            agent_id=self.agent_id,
            get_task_agent_manager=lambda: self._task_agent_manager,
            session_run_coordinator=self._session_run_coordinator,
            background_dispatcher=background_dispatcher,
            background_launch_service=background_launch_service,
            persist_turn_supersessions=self._persist_turn_supersessions_from_handler,
        )
        self._handler_registry = ExecutionHandlerRegistry()
        common_handler_deps = build_common_handler_dependencies(handler_deps)
        for handler in (
            FactOnlyHandler(common_handler_deps),
            DirectLLMHandler(handler_deps),
            FunctionCallingHandler(handler_deps),
            OrchestrationLaunchHandler(common_handler_deps),
            OrchestrationUpdateHandler(common_handler_deps),
            ExploreRenderHandler(handler_deps),
        ):
            self._handler_registry.register(handler)
        self._coordinator = ChatExecutionCoordinator(
            context_decider=self.context_decider,
            fact_classifier=self._fact_classifier,
            handler_registry=self._handler_registry,
            intent_trace_callback=self._postprocess_service.record_intent_resolution,
            tool_advisory_provider=self._get_tool_advisory,
            tool_selection_trace_callback=self._postprocess_service.record_tool_selection,
        )
        self._last_batch_facts: list[FactRecord] = []

        # Keep these aliases so existing read paths and tests see the same underlying stores.
        self._conversation_history = self._history_service._conversation_history
        self._tool_interactions = self._history_service._tool_interactions

    @property
    def postprocess_service(self) -> ChatPostProcessService:
        """Expose the chat post-process service for external wiring.

        Used by the background-task completion handshake so the bootstrap
        listener can route terminal-state tasks back into the chat session
        via :meth:`ChatPostProcessService.deliver_background_task_completion`.
        """
        return self._postprocess_service

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

    @staticmethod
    def _resolve_message_bus() -> Any | None:
        try:
            from ...core.container import Container

            bus = Container.message_bus()
        except Exception:
            return None
        if bus is None or type(bus).__name__ == "object":
            return None
        return bus if hasattr(bus, "publish") else None

    async def _get_tool_advisory(self, task_context: str | None = None) -> list[dict]:
        """Fetch notable L4 advisories for the coordinator."""
        available_tool_names = tool_registry.list_tools()
        trace_stats: dict[str, dict[str, float | int]] = {}
        if self._runtime_trace_store is not None:
            try:
                trace_stats = await self._runtime_trace_store.get_tool_execution_stats(
                    available_tool_names
                )
            except Exception as exc:
                logger.debug("Failed to fetch runtime trace tool stats: %s", exc)

        advisories_by_tool: dict[str, dict] = {}
        if self.unified_memory is None or self.unified_memory.l4 is None:
            base_advisories = []
        else:
            try:
                base_advisories = await self.unified_memory.l4.get_notable_advisories(
                    task_context=task_context
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

        return [
            advisory
            for advisory in advisories_by_tool.values()
            if advisory.get("strategy_hint") is not None
            or advisory.get("breaker_state") != "closed"
            or (
                float(advisory.get("success_rate") or 0.0) < 0.7
                and int(advisory.get("total_attempts") or 0) >= 3
            )
        ][:10]

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
        session_id = self._history_service.require_session_id(
            classified.user_id, classified.session_id
        )
        active_persona_id = await self._resolve_context_persona_id(
            run_decision.latest_payload
        )
        history_context = await self._history_service.get_or_load_history_context(
            classified.user_id,
            session_id,
            active_persona_id=active_persona_id,
        )
        history = history_context.messages
        recent_tool_errors = self._history_service.get_recent_tool_errors(
            self._history_service.history_key(classified.user_id, session_id)
        )
        recent_tool_state = self._history_service.get_recent_tool_state(
            self._history_service.history_key(classified.user_id, session_id)
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
            history_key=self._history_service.history_key(
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
            from ...personality.persona_repository import PersonaRepository

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
        await self._postprocess_service.handle(context, raw_result)

    def get_conversation_history(self, user_id: str, session_id: str) -> list[dict]:
        return self._history_service.get_conversation_history(user_id, session_id)

    def clear_conversation_history(self, user_id: str, session_id: str) -> None:
        self._history_service.clear_conversation_history(user_id, session_id)

    def get_llm_max_tokens(self) -> int:
        try:
            return int(get_config().llm.max_tokens)
        except Exception:
            return 4096
