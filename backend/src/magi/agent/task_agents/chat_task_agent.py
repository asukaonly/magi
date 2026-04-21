"""Runtime task agent for chat facts."""
from __future__ import annotations

from typing import Optional

from ...agent.orchestration import get_orchestration_store
from ...agent.task_orchestrator import TaskOrchestrator
from ...agent.trace import now_wall_ms
from ...chat import ChatMessageRecord, ChatProjector, ChatStore, get_chat_read_service
from ...config import get_config, get_user_preference
from ...core.logger import get_logger
from ...agent.runtime.contracts import FactRecord
from ...agent.runtime.task_agent import TaskAgent, TaskAgentRuntimeContext
from ...agent.runtime.types import TaskAgentType
from ...context import ContextAssemblyService, ContextRetrievalService, PromptContextAssembler, PromptContextRenderer
from ...context.user_profile_service import UserProfileService
from ...tools.context_decider import ContextDecider
from ...tools.registry import tool_registry
from ...runtime_trace import RuntimeTraceStore
from ...utils.runtime import get_runtime_paths
from ..execution.function_calling import FunctionCallingOrchestrator
from .chat.interruption_classifier import InterruptionClassifier
from .chat import (
    ChatExecutionCoordinator,
    ChatFactClassifier,
    ChatHistoryService,
    IntentDecision,
    ChatPlanningService,
    ChatPostProcessService,
    ChatPromptService,
    ChatReplyContext,
    ChatRuntimeContext,
    ExecutionHandlerRegistry,
    ExecutionRequest,
    ExecutionResult,
    SessionRunCoordinator,
    SessionRunStore,
    ToolSelection,
)
from .chat.handlers import (
    ChatHandlerDependencies,
    DirectLLMHandler,
    ExploreRenderHandler,
    FunctionCallingHandler,
    build_common_handler_dependencies,
)
from .common import FactOnlyHandler, OrchestrationLaunchHandler, OrchestrationUpdateHandler

logger = get_logger(__name__)

_RATE_LIMIT_CODES = {"429", "1302", "rate_limit_exceeded"}


def _format_llm_error(exc: Exception) -> str:
    """Return a concise user-facing error string for an LLM call failure."""
    exc_str = str(exc)
    status_code = str(getattr(exc, "status_code", "") or "")
    if status_code == "429" or any(code in exc_str for code in _RATE_LIMIT_CODES):
        return "⚠️ The AI service is rate-limited. Please wait a moment and try again."
    if status_code in ("401", "403"):
        return "⚠️ Authentication failed. Please check your API key configuration."
    if status_code in ("500", "502", "503"):
        return "⚠️ The AI service is temporarily unavailable. Please try again later."
    return f"⚠️ The AI service returned an error. Please try again. ({exc.__class__.__name__})"


class ChatTaskAgent(TaskAgent[ChatRuntimeContext, IntentDecision, ToolSelection, ExecutionRequest, ExecutionResult]):
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
        history_fetch_limit: int = 200,
        scenario_prompts_store=None,
        skill_runner=None,
        runtime_trace_store: RuntimeTraceStore | None = None,
        chat_store: ChatStore | None = None,
        chat_projector: ChatProjector | None = None,
    ) -> None:
        super().__init__(agent_type=TaskAgentType.CHAT, agent_id=agent_id)
        self.llm = llm_adapter
        self._llm_pool = llm_pool
        self.memory = memory
        self.unified_memory = unified_memory
        self.memory_integration = memory_integration
        self._chat_store = chat_store
        self.context_decider = ContextDecider(
            tool_registry=tool_registry,
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
        )
        self.prompt_context_assembler = PromptContextAssembler(
            tool_registry=tool_registry,
            scenario_prompts_store=scenario_prompts_store,
            user_profile_service=UserProfileService(unified_memory=unified_memory),
        )
        self.prompt_context_renderer = PromptContextRenderer()
        self._chat_read_service = get_chat_read_service()
        self._context_retrieval_service = ContextRetrievalService(
            unified_memory=unified_memory,
            retrieval_service=hybrid_retrieval_service,
        )
        self._context_service = ContextAssemblyService(
            agent_id=self.agent_id,
            agent_type=str(self.agent_type.value if hasattr(self.agent_type, "value") else self.agent_type),
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
        )
        self._fact_classifier = ChatFactClassifier()
        self._prompt_service = ChatPromptService(
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
        )
        self._session_run_coordinator = SessionRunCoordinator(
            run_store=SessionRunStore(
                l0_store=(unified_memory.l0 if unified_memory is not None else None),
            ),
            interruption_classifier=InterruptionClassifier(
                llm_adapter=llm_adapter,
                llm_pool=llm_pool,
            ),
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
        )
        # Initialize trace read service for enriching AI_RESPONSE events
        from ...api.services.chat_trace_read_service import ChatTraceReadService
        try:
            trace_read_service = ChatTraceReadService()
        except Exception:
            trace_read_service = None

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
            stream_chunk_callback=self._emit_stream_chunk,
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
        )
        self._last_batch_facts: list[FactRecord] = []

        # Keep these aliases so existing read paths and tests see the same underlying stores.
        self._conversation_history = self._history_service._conversation_history
        self._tool_interactions = self._history_service._tool_interactions

    async def _emit_stream_chunk(
        self,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        content_delta: str,
        is_final: bool,
        retract: bool = False,
    ) -> None:
        await self._postprocess_service._runtime_notifier.emit_stream_chunk(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            content_delta=content_delta,
            is_final=is_final,
            retract=retract,
        )

    async def _resolve_session_workspace_path(self, *, user_id: str, session_id: str) -> str | None:
        summary = await self._chat_read_service.aget_session_summary(user_id, session_id)
        return summary.workspace_path if summary is not None else None

    async def _get_tool_advisory(self, task_context: str | None = None) -> list[dict]:
        """Fetch notable L4 advisories for the coordinator."""
        if self.unified_memory is None or self.unified_memory.l4 is None:
            return []
        return await self.unified_memory.l4.get_notable_advisories(task_context=task_context)

    async def handle_fact(self, fact: FactRecord) -> None:
        _ = fact

    async def merge_facts(self, new_facts: list[FactRecord]) -> list[FactRecord]:
        self._last_batch_facts = list(new_facts)
        return await super().merge_facts(new_facts)

    async def build_context(self, merged_facts: list[FactRecord]) -> ChatRuntimeContext:
        base_context = await super().build_context(merged_facts)
        batch_facts = list(self._last_batch_facts)
        latest_fact = base_context.latest_fact if isinstance(base_context, TaskAgentRuntimeContext) else None
        classified = self._fact_classifier.classify(
            agent_id=self.agent_id,
            latest_fact=latest_fact,
            batch_facts=batch_facts,
        )
        run_decision = await self._session_run_coordinator.aroute(classified)
        if run_decision.superseded_turns:
            updated_at_ms = int(latest_fact.timestamp * 1000) if isinstance(latest_fact, FactRecord) else now_wall_ms()
            await self._postprocess_service.persist_turn_supersessions(
                superseded_turns=run_decision.superseded_turns,
                updated_at_ms=updated_at_ms,
            )
        session_id = self._history_service.require_session_id(classified.user_id, classified.session_id)
        history = await self._history_service.get_or_load_history(classified.user_id, session_id)
        recent_tool_errors = self._history_service.get_recent_tool_errors(
            self._history_service.history_key(classified.user_id, session_id)
        )
        active_orchestrations = await self._orchestration_store.list_orchestrations(
            user_id=classified.user_id,
            session_id=session_id,
            statuses=["running", "aggregating"],
        )
        reply_context = await self._resolve_reply_context(run_decision.latest_payload)
        streaming_chat_enabled = bool(get_user_preference("streaming_chat_enabled", False))
        return ChatRuntimeContext(
            latest_fact=latest_fact if isinstance(latest_fact, FactRecord) else None,
            recent_facts=list(base_context.recent_facts if isinstance(base_context, TaskAgentRuntimeContext) else []),
            batch_facts=batch_facts,
            agent_id=self.agent_id,
            agent_type=str(base_context.agent_type if isinstance(base_context, TaskAgentRuntimeContext) else TaskAgentType.CHAT.value),
            runtime_key=str(base_context.runtime_key if isinstance(base_context, TaskAgentRuntimeContext) else self.runtime_key),
            user_id=classified.user_id,
            session_id=session_id,
            history_key=self._history_service.history_key(classified.user_id, session_id),
            history=history,
            conversation_history=history,
            active_orchestrations=[item.to_dict() for item in active_orchestrations],
            recent_tool_errors=recent_tool_errors,
            latest_user_message=run_decision.planner_user_message,
            incoming_fact_kind=run_decision.planner_fact_kind,
            latest_payload=run_decision.latest_payload,
            active_run=run_decision.active_run,
            session_run_id=run_decision.active_run.run_id if run_decision.active_run is not None else None,
            session_run_revision=run_decision.active_run.revision if run_decision.active_run is not None else 0,
            session_run_disposition=run_decision.run_disposition,
            planner_fact=run_decision.planner_fact,
            planner_fact_kind=run_decision.planner_fact_kind,
            planner_payload=run_decision.latest_payload,
            pending_turns=list(run_decision.checkpoint_pending_turns),
            reply_context=reply_context,
            streaming_chat_enabled=streaming_chat_enabled,
        )

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
        return await self._coordinator.assemble_request(context, intent_result, tool_result)

    async def call_llm(self, context: ChatRuntimeContext, llm_params: ExecutionRequest) -> ExecutionResult:
        try:
            return await self._coordinator.execute(llm_params)
        except Exception as exc:
            await self._emit_llm_error(context, exc)
            raise

    async def _emit_llm_error(self, context: ChatRuntimeContext, exc: Exception) -> None:
        """Emit a user-visible error message when LLM call fails."""
        turn_id = str(getattr(context.latest_payload, "turn_id", "") or "").strip()
        if not (context.user_id and context.session_id and turn_id):
            return
        error_text = _format_llm_error(exc)
        await self._emit_stream_chunk(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
            content_delta=error_text,
            is_final=False,
        )
        await self._emit_stream_chunk(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
            content_delta="",
            is_final=True,
        )

    async def parse_result(self, context: ChatRuntimeContext, raw_result: ExecutionResult) -> None:
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

    async def _resolve_reply_context(self, latest_payload: object) -> ChatReplyContext | None:
        if self._chat_store is None:
            return None
        current_turn_id = str(getattr(latest_payload, "turn_id", "") or "").strip()
        reply_to_message_id = str(getattr(latest_payload, "reply_to_message_id", "") or "").strip()
        if current_turn_id:
            current_user_message = await self._chat_store.get_latest_message_for_turn(
                current_turn_id,
                message_kind="user_text",
            )
            if current_user_message is not None:
                reply_to_message_id = str(current_user_message.reply_to_message_id or reply_to_message_id or "").strip()
        if not reply_to_message_id:
            return None
        reply_target = await self._chat_store.get_message(reply_to_message_id)
        if reply_target is None:
            return None
        return self._build_reply_context(
            current_turn_id=current_turn_id,
            reply_target=reply_target,
        )

    @staticmethod
    def _build_reply_context(
        *,
        current_turn_id: str,
        reply_target: ChatMessageRecord,
    ) -> ChatReplyContext:
        content_excerpt = str(reply_target.content_text or "").strip()
        if len(content_excerpt) > 280:
            content_excerpt = f"{content_excerpt[:277]}..."
        return ChatReplyContext(
            message_id=reply_target.message_id,
            role=reply_target.role,
            content_excerpt=content_excerpt,
            references_prior_turn=bool(
                current_turn_id
                and reply_target.turn_id
                and str(reply_target.turn_id).strip() != current_turn_id
            ),
        )

    async def request_session_cancel(
        self,
        *,
        session_id: str,
        requested_by: str,
        reason: str = "user_cancel",
        anchor_turn_id: str | None = None,
    ) -> dict[str, object] | None:
        """Request strong cancellation for the active session run."""
        active_run = self._session_run_coordinator.request_cancel(
            session_id=session_id,
            requested_by=requested_by,
            reason=reason,
            anchor_turn_id=anchor_turn_id,
        )
        if active_run is None:
            return None
        cancelled_orchestration_ids = await self._task_orchestrator.cancel_run(
            session_id=session_id,
            run_id=active_run.run_id,
            run_revision=active_run.revision,
        )
        await self._postprocess_service.emit_execution_control_notification(
            user_id=self.agent_id,
            session_id=session_id,
            turn_id=active_run.cancel_anchor_turn_id or active_run.root_turn_id,
            run_id=active_run.run_id,
            orchestration_id=(cancelled_orchestration_ids[0] if cancelled_orchestration_ids else None),
            state="cancelling",
            can_cancel=False,
            label="Cancelling run",
        )
        return {
            "session_id": session_id,
            "run_id": active_run.run_id,
            "revision": active_run.revision,
            "status": active_run.status,
            "cancel_reason": active_run.cancel_reason,
            "cancel_requested_by": active_run.cancel_requested_by,
            "cancel_anchor_turn_id": active_run.cancel_anchor_turn_id,
            "cancelled_orchestration_ids": cancelled_orchestration_ids,
        }
