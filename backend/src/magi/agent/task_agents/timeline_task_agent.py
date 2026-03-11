"""Task agent dedicated to timeline fact ingestion."""
from __future__ import annotations

from ...core.runtime.contracts import FactRecord
from ...core.runtime.task_agent import TaskAgent, TaskAgentRuntimeContext
from ...core.runtime.types import TaskAgentType
from .timeline import (
    TimelineExecutionCoordinator,
    TimelineExecutionRequest,
    TimelineExecutionResult,
    TimelineFactClassifier,
    TimelineHandler,
    TimelineIntentDecision,
    TimelineRuntimeContext,
    TimelineToolSelection,
)


class TimelineTaskAgent(
    TaskAgent[
        TimelineRuntimeContext,
        TimelineIntentDecision,
        TimelineToolSelection,
        TimelineExecutionRequest,
        TimelineExecutionResult,
    ]
):
    """Runtime task agent for timeline ingestion facts."""

    def __init__(
        self,
        agent_id: str,
        timeline_handler: TimelineHandler | None = None,
        config=None,
        unified_memory=None,
    ) -> None:
        super().__init__(agent_type=TaskAgentType.TIMELINE, agent_id=agent_id)
        self.config = config
        self.unified_memory = unified_memory
        self._fact_classifier = TimelineFactClassifier()
        self._coordinator = TimelineExecutionCoordinator(timeline_handler=timeline_handler)
        self._last_batch_facts: list[FactRecord] = []

    async def handle_fact(self, fact: FactRecord) -> None:
        _ = fact

    async def merge_facts(self, new_facts: list[FactRecord]) -> list[FactRecord]:
        self._last_batch_facts = list(new_facts)
        return await super().merge_facts(new_facts)

    async def build_context(self, merged_facts: list[FactRecord]) -> TimelineRuntimeContext:
        base_context = await super().build_context(merged_facts)
        latest_fact = base_context.latest_fact if isinstance(base_context, TaskAgentRuntimeContext) else None
        payload = self._fact_classifier.classify(latest_fact, self._last_batch_facts)
        return TimelineRuntimeContext(
            latest_fact=latest_fact,
            recent_facts=list(base_context.recent_facts),
            agent_id=self.agent_id,
            agent_type=str(base_context.agent_type),
            runtime_key=str(base_context.runtime_key),
            batch_facts=list(self._last_batch_facts),
            latest_payload=payload,
        )

    async def match_intent(self, context: TimelineRuntimeContext) -> TimelineIntentDecision:
        return await self._coordinator.match_intent(context)

    async def match_tools(
        self,
        context: TimelineRuntimeContext,
        intent_result: TimelineIntentDecision,
    ) -> TimelineToolSelection:
        return await self._coordinator.match_tools(context, intent_result)

    async def assemble_llm_params(
        self,
        context: TimelineRuntimeContext,
        intent_result: TimelineIntentDecision,
        tool_result: TimelineToolSelection,
    ) -> TimelineExecutionRequest:
        return await self._coordinator.assemble_request(context, intent_result, tool_result)

    async def call_llm(
        self,
        context: TimelineRuntimeContext,
        llm_params: TimelineExecutionRequest,
    ) -> TimelineExecutionResult:
        _ = context
        return await self._coordinator.execute(llm_params)
