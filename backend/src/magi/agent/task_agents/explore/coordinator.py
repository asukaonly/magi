"""Execution coordination for ExploreTaskAgent."""
from __future__ import annotations

from ..common import (
    ExecutionMode,
    ExecutionRequest,
    IncomingFactKind,
    OrchestrationLaunchRequest,
    OrchestrationPlan,
    OrchestrationUpdateRequest,
    ToolSelection,
)
from .contracts import ExploreIntentDecision, ExploreRuntimeContext


class ExploreExecutionCoordinator:
    """Coordinates execution-mode selection for ExploreTaskAgent."""

    async def match_intent(self, context: ExploreRuntimeContext) -> ExploreIntentDecision:
        if context.incoming_fact_kind == IncomingFactKind.WORKER_UPDATE:
            return ExploreIntentDecision(
                intent="explore_orchestration_update",
                execution_mode=ExecutionMode.ORCHESTRATION_UPDATE,
                reasoning="Worker updates must advance ExploreTaskAgent orchestration state.",
            )
        if context.incoming_fact_kind == IncomingFactKind.EXPLORE_TASK_REQUEST:
            return ExploreIntentDecision(
                intent="explore_request",
                execution_mode=ExecutionMode.ORCHESTRATION_LAUNCH,
                orchestration_plan=OrchestrationPlan(
                    mode="decompose",
                    planner="task_agent",
                    default_leaf_type="Explore",
                    allow_parallel=True,
                ),
                reasoning="Explore requests always launch bounded Explore worker subtasks.",
            )
        return ExploreIntentDecision(
            intent="fact_only",
            execution_mode=ExecutionMode.FACT_ONLY,
            reasoning="Non-request facts do not require immediate action.",
        )

    async def match_tools(self, context: ExploreRuntimeContext, intent: ExploreIntentDecision) -> ToolSelection:
        _ = context
        return ToolSelection(tools=[], reasoning=intent.reasoning)

    async def assemble_request(self, context: ExploreRuntimeContext, intent: ExploreIntentDecision, tool_selection: ToolSelection):
        if intent.execution_mode == ExecutionMode.ORCHESTRATION_LAUNCH:
            return OrchestrationLaunchRequest(
                mode=intent.execution_mode,
                context=context,
                intent=intent,
                tool_selection=tool_selection,
            )
        if intent.execution_mode == ExecutionMode.ORCHESTRATION_UPDATE:
            return OrchestrationUpdateRequest(
                mode=intent.execution_mode,
                context=context,
                intent=intent,
                tool_selection=tool_selection,
            )
        return ExecutionRequest(
            mode=intent.execution_mode,
            context=context,
            intent=intent,
            tool_selection=tool_selection,
        )
