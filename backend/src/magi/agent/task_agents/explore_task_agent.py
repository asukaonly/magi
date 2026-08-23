"""Task agent dedicated to large Explore-style decompositions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Callable, cast

from ...agent.execution.task_budget import (
    TaskExecutionBudgetStore,
    task_execution_budget_scope,
)
from ...agent.orchestration import get_orchestration_store
from ...agent.task_orchestrator import TaskOrchestrator
from ...agent.runtime.contracts import FactRecord
from ...agent.runtime.task_agent import TaskAgent, TaskAgentRuntimeContext
from ...agent.runtime.types import TaskAgentType
from ...core.logger import get_logger
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

logger = get_logger(__name__)


class ExploreTaskAgent(
    TaskAgent[
        ExploreRuntimeContext,
        ExploreIntentDecision,
        ToolSelection,
        ExecutionRequest,
        ExecutionResult,
    ]
):
    """Parent task agent for large Explore tasks composed of leaf Explore workers."""

    def __init__(
        self,
        agent_id: str,
        llm_adapter=None,
        llm_pool=None,
        control_session_store_provider: Callable[[], Any] | None = None,
        chat_store: Any | None = None,
    ) -> None:
        super().__init__(agent_type=TaskAgentType.EXPLORE, agent_id=agent_id)
        self.llm = llm_adapter
        self._llm_pool = llm_pool
        self._chat_store = chat_store
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

    def _should_end_batch_before(
        self,
        batch: list[FactRecord],
        next_fact: FactRecord,
    ) -> bool:
        """Keep facts from different root executions out of one admission."""
        if next_fact.event_type == EXPLORE_TASK_REQUEST or any(
            fact.event_type == EXPLORE_TASK_REQUEST for fact in batch
        ):
            return True
        current_key = self._fact_batch_key(batch[-1])
        next_key = self._fact_batch_key(next_fact)
        return current_key is None or next_key is None or current_key != next_key

    @staticmethod
    def _fact_batch_key(fact: FactRecord) -> tuple[str, str] | None:
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        session_id = str(payload.get("session_id") or "").strip()
        execution_id = str(
            payload.get("orchestration_id")
            or payload.get("root_turn_id")
            or payload.get("turn_id")
            or ""
        ).strip()
        if not session_id or not execution_id:
            return None
        return session_id, execution_id

    async def merge_facts(self, new_facts: list[FactRecord]) -> list[FactRecord]:
        self._last_batch_facts = list(new_facts)
        return await super().merge_facts(new_facts)

    async def build_context(self, merged_facts: list[FactRecord]) -> ExploreRuntimeContext:
        base_context = await super().build_context(merged_facts)
        batch_facts = list(self._last_batch_facts)
        latest_fact = (
            base_context.latest_fact if isinstance(base_context, TaskAgentRuntimeContext) else None
        )
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
        orchestration_metadata = await self._resolve_orchestration_metadata(
            classified.payload
        )
        root_turn_id = self._resolve_root_turn_id(
            classified.payload,
            orchestration_metadata,
        )
        upstream_task_agent_type, upstream_task_agent_id = (
            self._resolve_upstream_target(
                classified.payload,
                orchestration_metadata,
                fallback_session_id=classified.session_id,
                fallback_user_id=classified.user_id,
            )
        )
        return ExploreRuntimeContext(
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
                else TaskAgentType.EXPLORE.value
            ),
            runtime_key=str(
                base_context.runtime_key
                if isinstance(base_context, TaskAgentRuntimeContext)
                else self.runtime_key
            ),
            user_id=classified.user_id,
            session_id=classified.session_id,
            history_key=history_key,
            history=history,
            latest_user_message=classified.user_message,
            incoming_fact_kind=classified.kind,
            upstream_task_agent_type=upstream_task_agent_type,
            upstream_task_agent_id=upstream_task_agent_id,
            root_turn_id=root_turn_id,
            latest_payload=classified.payload,
            user_message_generation=(
                int(latest_fact.user_message_generation)
                if isinstance(latest_fact, FactRecord)
                and latest_fact.user_message_generation is not None
                else None
            ),
        )

    async def _resolve_orchestration_metadata(
        self,
        payload: Any,
    ) -> dict[str, Any]:
        orchestration_id = str(
            getattr(payload, "orchestration_id", "") or ""
        ).strip()
        if not orchestration_id:
            return {}
        try:
            state = await self._orchestration_store.get_orchestration(orchestration_id)
            return dict(state.metadata) if state is not None else {}
        except Exception:
            # Preserve enough context to emit a terminal upstream failure. The
            # missing durable root then enters the fail-closed zero allowance.
            logger.warning(
                "Failed to restore Explore orchestration metadata",
                orchestration_id=orchestration_id,
                exc_info=True,
            )
            return {}

    @staticmethod
    def _resolve_root_turn_id(
        payload: Any,
        orchestration_metadata: dict[str, Any],
    ) -> str | None:
        explicit_root = str(getattr(payload, "root_turn_id", "") or "").strip()
        if explicit_root:
            return explicit_root
        persisted_root = str(
            orchestration_metadata.get("root_turn_id") or ""
        ).strip()
        if persisted_root:
            return persisted_root
        return None

    @staticmethod
    def _resolve_upstream_target(
        payload: Any,
        orchestration_metadata: dict[str, Any],
        *,
        fallback_session_id: str,
        fallback_user_id: str,
    ) -> tuple[str, str]:
        if isinstance(payload, ExploreTaskRequestPayload):
            return (
                payload.upstream_task_agent_type or TaskAgentType.CHAT.value,
                payload.upstream_task_agent_id
                or fallback_session_id
                or fallback_user_id,
            )
        upstream_type = str(
            orchestration_metadata.get("upstream_task_agent_type")
            or TaskAgentType.CHAT.value
        ).strip()
        upstream_id = str(
            orchestration_metadata.get("upstream_task_agent_id")
            or fallback_session_id
            or fallback_user_id
        ).strip()
        return upstream_type, upstream_id

    async def match_intent(self, context: ExploreRuntimeContext) -> ExploreIntentDecision:
        return await self._coordinator.match_intent(context)

    @asynccontextmanager
    async def execution_scope(
        self,
        context: ExploreRuntimeContext,
    ) -> AsyncIterator[None]:
        """Rehydrate the originating chat turn's budget for each admission."""
        store = self._durable_task_budget_store()
        if context.root_turn_id and store is not None:
            async with task_execution_budget_scope(
                root_turn_id=context.root_turn_id,
                store=store,
            ):
                yield
            return
        if self._chat_store is not None:
            raise RuntimeError(
                "Durable Explore task budget root identity is unavailable"
            )
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

    async def match_tools(
        self, context: ExploreRuntimeContext, intent_result: ExploreIntentDecision
    ):
        return await self._coordinator.match_tools(context, intent_result)

    async def assemble_llm_params(
        self, context: ExploreRuntimeContext, intent_result: ExploreIntentDecision, tool_result
    ):
        return await self._coordinator.assemble_request(context, intent_result, tool_result)

    async def call_llm(self, context: ExploreRuntimeContext, llm_params):
        _ = context
        async with task_execution_budget_scope():
            handler = self._handler_registry.get(llm_params.mode)
            prepared = await handler.build_request(llm_params)
            return await handler.execute(prepared)

    async def parse_result(
        self, context: ExploreRuntimeContext, raw_result: ExecutionResult
    ) -> None:
        await self._postprocess_service.handle(context, raw_result)

    async def handle_batch_failure(
        self,
        batch: list[FactRecord],
        *,
        error: BaseException,
        stage: str,
        context: ExploreRuntimeContext | None,
    ) -> None:
        """Close an Explore admission upstream instead of leaving Chat waiting."""
        _ = (batch, stage)
        if context is not None:
            await self._postprocess_service.handle_failure(context, error)
