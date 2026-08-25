"""Deterministic domain admission for chat facts."""

from __future__ import annotations

from magi.agent.task_agents.common import ExecutionMode, IncomingFactKind
from magi.agent.task_agents.handlers.contracts import (
    ChatRuntimeContext,
    TraceDisplayMode,
    TurnAdmissionDecision,
    TurnUXPlan,
)
from magi.agent.execution.reasoning import ReasoningPreference


class ChatTurnAdmissionService:
    """Separate domain events from ordinary user turns without semantic routing."""

    def resolve(self, context: ChatRuntimeContext) -> TurnAdmissionDecision:
        kind = _resolve_fact_kind(context)
        if kind is IncomingFactKind.OTHER_FACT:
            return _decision(
                "non_user_fact",
                ExecutionMode.FACT_ONLY,
                "Non-user fact does not start a model-facing run.",
            )
        return _decision(
            "unified_agent_run",
            None,
            "Ordinary user turns enter the unified agent loop without classification.",
            reasoning_preference=_reasoning_preference(context),
            ux_plan=TurnUXPlan(trace_display_mode=TraceDisplayMode.COLLAPSIBLE),
        )


def _decision(
    run_kind: str,
    mode: ExecutionMode | None,
    reasoning: str,
    reasoning_preference: ReasoningPreference = ReasoningPreference.AUTO,
    ux_plan: TurnUXPlan | None = None,
) -> TurnAdmissionDecision:
    return TurnAdmissionDecision(
        run_kind=run_kind,
        execution_mode=mode,
        reasoning=reasoning,
        reasoning_preference=reasoning_preference,
        ux_plan=ux_plan or TurnUXPlan(),
    )


def _reasoning_preference(context: ChatRuntimeContext) -> ReasoningPreference:
    value = str(getattr(context.latest_payload, "reasoning_preference", "") or "").strip()
    if not value:
        return ReasoningPreference.AUTO
    try:
        return ReasoningPreference(value)
    except ValueError:
        return ReasoningPreference.AUTO


def _resolve_fact_kind(context: ChatRuntimeContext) -> IncomingFactKind:
    if (
        context.planner_fact is not None
        or context.planner_fact_kind is not IncomingFactKind.OTHER_FACT
    ):
        return context.planner_fact_kind
    return context.incoming_fact_kind


__all__ = ["ChatTurnAdmissionService"]
