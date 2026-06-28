"""Integration: TaskOrchestrator plan/aggregate LLM calls + RunControl."""
from __future__ import annotations

import inspect

import pytest

from magi.agent.orchestration_plan import OrchestrationPlan
from magi.agent.run_control import (
    RetractRequested,
    RetractSignal,
    RunControl,
    null_run_control,
)


def test_task_orchestrator_start_accepts_control() -> None:
    from magi.agent.task_orchestrator import TaskOrchestrator

    params = inspect.signature(TaskOrchestrator.start_orchestration).parameters
    assert "control" in params, (
        "TaskOrchestrator.start_orchestration must accept a RunControl"
    )


def test_orchestration_execution_result_has_retracted_field() -> None:
    from magi.agent.orchestration_models import OrchestrationExecutionResult

    field_names = {f.name for f in OrchestrationExecutionResult.__dataclass_fields__.values()}
    assert "retracted" in field_names

    # Default is False; settable.
    r = OrchestrationExecutionResult()
    assert r.retracted is False
    r2 = OrchestrationExecutionResult(retracted=True)
    assert r2.retracted is True


def test_orchestration_launch_handler_reads_control_from_context() -> None:
    """OrchestrationLaunchHandler.execute must extract context.control
    and pass it to start_orchestration."""
    from magi.agent.task_agents.common.handlers import OrchestrationLaunchHandler

    src = inspect.getsource(OrchestrationLaunchHandler.execute)
    assert "context.control" in src or "request.context.control" in src, (
        "OrchestrationLaunchHandler.execute must read control from request.context"
    )
    assert "control=" in src, (
        "OrchestrationLaunchHandler.execute must pass control to start_orchestration"
    )


@pytest.mark.asyncio
async def test_plan_callback_aborts_on_retract() -> None:
    """When the plan_subtasks callback (which calls an LLM) receives a
    RunControl with retract_signal set, the LLM call raises RetractRaised
    which propagates back to TaskOrchestrator, which sets retracted=True
    on its OrchestrationExecutionResult."""
    from agent.fixtures_task_orchestrator import (
        build_test_task_orchestrator_with_aborting_planner,
    )

    control = null_run_control()
    retract = RetractSignal()
    retract.request(RetractRequested(reason="user_retract"))
    control.retract_signal = retract

    orch = build_test_task_orchestrator_with_aborting_planner(control=control)

    result = await orch.start_orchestration(
        user_id="u",
        session_id="s",
        user_message="do a thing",
        history=[],
        history_key="hk",
        turn_id=None,
        correlation_id=None,
        orchestration_plan=OrchestrationPlan(
            mode="decompose",
            planner="task_agent",
            default_leaf_type="general-purpose",
            allow_parallel=False,
        ),
        control=control,
    )

    assert result.retracted is True


def test_orchestration_launch_handler_uses_typed_orchestration_plan() -> None:
    """OrchestrationLaunchHandler consumes the typed plan on the intent."""
    import inspect

    from magi.agent.task_agents.common.handlers import OrchestrationLaunchHandler

    src = inspect.getsource(OrchestrationLaunchHandler)
    assert "orchestration_plan" in src
    assert "to_strategy_dict" not in src
