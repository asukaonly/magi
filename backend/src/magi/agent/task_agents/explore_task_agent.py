"""Task agent dedicated to large Explore-style decompositions."""
from __future__ import annotations

from typing import Any, Callable

from ...agent.orchestration import get_orchestration_store
from ...agent.task_orchestrator import TaskOrchestrator
from ...agent.runtime.contracts import FactRecord
from ...agent.runtime.task_agent import TaskAgent, TaskAgentRuntimeContext
from ...agent.runtime.types import TaskAgentType
from ...tools.registry import tool_registry
from .common import (
    CommonHandlerDependencies,
    ExecutionRequest,
    ExecutionResult,
    ExecutionHandlerRegistry,
    ExploreTaskRequestPayload,
    FactOnlyHandler,
    OrchestrationLaunchHandler,
    OrchestrationUpdateHandler,
    ToolSelection,
)
from .explore import (
    EXPLORE_TASK_COMPLETED as EXPLORE_TASK_COMPLETED,
    EXPLORE_TASK_FAILED as EXPLORE_TASK_FAILED,
    EXPLORE_TASK_REQUEST as EXPLORE_TASK_REQUEST,
    ExploreAggregationService,
    ExploreExecutionCoordinator,
    ExploreFactClassifier,
    ExplorePlanningService,
    ExplorePostProcessService,
    ExploreRuntimeContext,
    ExploreSessionService,
)
from .explore.coordinator import ExploreIntentDecision
from .explore.prompt_service import ExplorePromptService


class ExploreTaskAgent(TaskAgent[ExploreRuntimeContext, ExploreIntentDecision, ToolSelection, ExecutionRequest, ExecutionResult]):
    """Parent task agent for large Explore tasks composed of leaf Explore workers."""

    def __init__(
        self,
        agent_id: str,
        llm_adapter=None,
        llm_pool=None,
        control_session_store_provider: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(agent_type=TaskAgentType.EXPLORE, agent_id=agent_id)
        self.llm = llm_adapter
        self._llm_pool = llm_pool
        self._last_batch_facts: list[FactRecord] = []
        self._session_service = ExploreSessionService()
        self._fact_classifier = ExploreFactClassifier()
        self._prompt_service = ExplorePromptService(llm_adapter=llm_adapter, llm_pool=llm_pool)
        self._planning_service = ExplorePlanningService(prompt_service=self._prompt_service)
        self._aggregation_service = ExploreAggregationService()
        self._orchestration_store = get_orchestration_store()
        self._task_orchestrator = TaskOrchestrator(
            runtime_key=self.runtime_key,
            tool_registry=tool_registry,
            plan_subtasks=self._planning_service.generate_subtask_plan,
            aggregate_orchestration=self._aggregation_service.aggregate_orchestration,
            register_user_message=self._session_service.append_request,
            parent_task_agent_type=TaskAgentType.EXPLORE.value,
            control_session_store_provider=control_session_store_provider,
        )
        self._postprocess_service = ExplorePostProcessService(
            get_task_agent_manager=lambda: self._task_agent_manager,
        )
        self._handler_registry = ExecutionHandlerRegistry()
        common_deps = CommonHandlerDependencies(task_orchestrator=self._task_orchestrator)
        for handler in (
            FactOnlyHandler(common_deps),
            OrchestrationLaunchHandler(common_deps),
            OrchestrationUpdateHandler(common_deps),
        ):
            self._handler_registry.register(handler)
        self._coordinator = ExploreExecutionCoordinator()

    async def handle_fact(self, fact: FactRecord) -> None:
        _ = fact

    async def merge_facts(self, new_facts: list[FactRecord]) -> list[FactRecord]:
        self._last_batch_facts = list(new_facts)
        return await super().merge_facts(new_facts)

    async def build_context(self, merged_facts: list[FactRecord]) -> ExploreRuntimeContext:
        base_context = await super().build_context(merged_facts)
        batch_facts = list(self._last_batch_facts)
        latest_fact = base_context.latest_fact if isinstance(base_context, TaskAgentRuntimeContext) else None
        classified = self._fact_classifier.classify(
            agent_id=self.agent_id,
            latest_fact=latest_fact if isinstance(latest_fact, FactRecord) else None,
            batch_facts=batch_facts,
        )
        history_key = self._session_service.history_key(classified.user_id, classified.session_id)
        history_snapshot = (
            classified.payload.history_snapshot
            if isinstance(classified.payload, ExploreTaskRequestPayload)
            else None
        )
        self._session_service.ingest_history_snapshot(history_key, history_snapshot)
        history = self._session_service.get_history(history_key)
        return ExploreRuntimeContext(
            latest_fact=latest_fact if isinstance(latest_fact, FactRecord) else None,
            recent_facts=list(base_context.recent_facts if isinstance(base_context, TaskAgentRuntimeContext) else []),
            batch_facts=batch_facts,
            agent_id=self.agent_id,
            agent_type=str(base_context.agent_type if isinstance(base_context, TaskAgentRuntimeContext) else TaskAgentType.EXPLORE.value),
            runtime_key=str(base_context.runtime_key if isinstance(base_context, TaskAgentRuntimeContext) else self.runtime_key),
            user_id=classified.user_id,
            session_id=classified.session_id,
            history_key=history_key,
            history=history,
            latest_user_message=classified.user_message,
            incoming_fact_kind=classified.kind,
            upstream_task_agent_type=(
                classified.payload.upstream_task_agent_type
                if isinstance(classified.payload, ExploreTaskRequestPayload)
                else TaskAgentType.CHAT.value
            ),
            upstream_task_agent_id=(
                classified.payload.upstream_task_agent_id
                if isinstance(classified.payload, ExploreTaskRequestPayload)
                else classified.user_id
            ),
            latest_payload=classified.payload,
            user_message_generation=(
                int(latest_fact.user_message_generation)
                if isinstance(latest_fact, FactRecord)
                and latest_fact.user_message_generation is not None
                else None
            ),
        )

    async def match_intent(self, context: ExploreRuntimeContext) -> ExploreIntentDecision:
        return await self._coordinator.match_intent(context)

    async def match_tools(self, context: ExploreRuntimeContext, intent_result: ExploreIntentDecision):
        return await self._coordinator.match_tools(context, intent_result)

    async def assemble_llm_params(self, context: ExploreRuntimeContext, intent_result: ExploreIntentDecision, tool_result):
        return await self._coordinator.assemble_request(context, intent_result, tool_result)

    async def call_llm(self, context: ExploreRuntimeContext, llm_params):
        _ = context
        handler = self._handler_registry.get(llm_params.mode)
        prepared = await handler.build_request(llm_params)
        return await handler.execute(prepared)

    async def parse_result(self, context: ExploreRuntimeContext, raw_result: ExecutionResult) -> None:
        await self._postprocess_service.handle(context, raw_result)
