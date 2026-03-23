"""Runtime task agent for chat facts."""
from __future__ import annotations

from typing import Optional

from ...agent.orchestration import get_orchestration_store
from ...agent.task_orchestrator import TaskOrchestrator
from ...chat import ChatProjector, ChatStore
from ...config import get_config
from ...core.logger import get_logger
from ...agent.runtime.contracts import FactRecord
from ...agent.runtime.task_agent import TaskAgent, TaskAgentRuntimeContext
from ...agent.runtime.types import TaskAgentType
from ...context import ContextAssemblyService, ContextRetrievalService, PromptContextAssembler, PromptContextRenderer
from ...tools.context_decider import ContextDecider
from ...tools.registry import tool_registry
from ...runtime_trace import RuntimeTraceStore
from ...utils.runtime import get_runtime_paths
from ..execution.function_calling import FunctionCallingOrchestrator
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


class ChatTaskAgent(TaskAgent[ChatRuntimeContext, IntentDecision, ToolSelection, ExecutionRequest, ExecutionResult]):
    """Consumes chat facts and delegates execution to typed handlers."""

    def __init__(
        self,
        agent_id: str,
        llm_adapter=None,
        llm_pool=None,
        memory=None,
        other_memory=None,
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
        self.other_memory = other_memory
        self.unified_memory = unified_memory
        self.memory_integration = memory_integration
        self.context_decider = ContextDecider(
            tool_registry=tool_registry,
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
        )
        self.prompt_context_assembler = PromptContextAssembler(
            tool_registry=tool_registry,
            scenario_prompts_store=scenario_prompts_store,
        )
        self.prompt_context_renderer = PromptContextRenderer()
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
            other_memory=other_memory,
        )

        runtime_paths = get_runtime_paths()
        self._history_service = ChatHistoryService(
            l1_db_path=runtime_paths.l1_memory_db_path,
            history_cache_max_sessions=history_cache_max_sessions,
            history_fetch_limit=history_fetch_limit,
        )
        self._fact_classifier = ChatFactClassifier()
        self._prompt_service = ChatPromptService(
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
        )
        self._session_run_coordinator = SessionRunCoordinator()
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
            get_action_emitter=lambda: self._action_emitter,
            get_task_agent_manager=lambda: self._task_agent_manager,
            get_sensor_hub=lambda: self._sensor_hub,
            memory=memory,
            other_memory=other_memory,
            unified_memory=unified_memory,
            max_fact_memory=self._max_fact_memory,
            trace_read_service=trace_read_service,
            runtime_trace_store=runtime_trace_store,
            chat_store=chat_store,
            chat_projector=chat_projector,
        )
        self.function_calling_orchestrator = FunctionCallingOrchestrator(
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
            tool_registry=tool_registry,
            skill_runner=skill_runner,
            tool_result_callback=self._postprocess_service.record_tool_interaction,
            loop_event_callback=self._postprocess_service.record_tool_loop_fact,
            runtime_trace_store=runtime_trace_store,
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
        )
        self._last_batch_facts: list[FactRecord] = []

        # Keep these aliases so existing read paths and tests see the same underlying stores.
        self._conversation_history = self._history_service._conversation_history
        self._tool_interactions = self._history_service._tool_interactions

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
        run_decision = self._session_run_coordinator.route(classified)
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
        _ = context
        return await self._coordinator.execute(llm_params)

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
