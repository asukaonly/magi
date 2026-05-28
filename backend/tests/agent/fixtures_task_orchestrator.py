"""Fixtures for TaskOrchestrator integration tests."""
from __future__ import annotations

from magi.agent.run_control import RunControl
from magi.agent.task_orchestrator import TaskOrchestrator
from magi.llm.cancellable_client import RetractRaised
from magi.tools.registry import ToolRegistry


def _noop_register_user_message(history_key: str, message: str) -> None:
    pass


async def _aborting_plan_subtasks(*args, **kwargs):
    """Planner that raises RetractRaised as if the LLM call inside it
    had observed the retract signal via CancellableLLMClient."""
    raise RetractRaised(payload=None)


async def _noop_aggregate_orchestration(state):
    return ""


def build_test_task_orchestrator_with_aborting_planner(
    *, control: RunControl
) -> TaskOrchestrator:
    """Construct a minimal TaskOrchestrator whose plan callback raises
    RetractRaised on invocation, simulating a retract during plan LLM."""
    return TaskOrchestrator(
        runtime_key="test:agent",
        tool_registry=ToolRegistry(),
        plan_subtasks=_aborting_plan_subtasks,
        aggregate_orchestration=_noop_aggregate_orchestration,
        register_user_message=_noop_register_user_message,
        parent_task_agent_type="chat",
    )
