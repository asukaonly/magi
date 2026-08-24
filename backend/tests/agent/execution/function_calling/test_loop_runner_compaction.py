from __future__ import annotations

import pytest

from magi.agent.execution.function_calling.loop_runner import FunctionCallingLoopRunner
from magi.agent.execution.function_calling.run_input import AgentRunRequest
from magi.agent.execution.function_calling.step_models import (
    FunctionCallingStepOutcome,
    FunctionCallingStepState,
)
from magi.agent.execution.function_calling.types import ExecutionOutcome
from magi.agent.execution.model_capabilities import ModelCapabilityProfile
from magi.agent.turn_input import UserTurnInput
from magi.control.run_control import null_run_control


@pytest.mark.asyncio
async def test_required_capability_fails_before_model_call_when_tools_are_unsupported() -> None:
    class _StepExecutor:
        async def execute_step(self, **kwargs: object) -> FunctionCallingStepOutcome:
            raise AssertionError("model call must not run")

    class _Host:
        step_executor = _StepExecutor()
        _current_messages: list[dict[str, object]] = []

        def build_step_state(self, **kwargs: object) -> FunctionCallingStepState:
            return FunctionCallingStepState(
                messages=[{"role": "user", "content": "inspect the attachment"}],
                effective_system_prompt="system",
                tools=[],
            )

    runner = FunctionCallingLoopRunner(_Host())
    outcome = await runner.run(
        AgentRunRequest(
            turn=UserTurnInput(text="inspect the attachment"),
            system_prompt="system",
            selected_tools=[],
            user_id="user-1",
            capability_resolution={"required_tools": ["photo_resolver"]},
            model_capabilities=ModelCapabilityProfile(supports_tool_calls=False),
        ),
        control=null_run_control(),
    )

    assert outcome.status == "failed"
    assert outcome.failure_reason == "tool_calls_unsupported"


@pytest.mark.asyncio
async def test_oversized_tool_schemas_fail_before_model_call() -> None:
    class _StepExecutor:
        async def execute_step(self, **kwargs: object) -> FunctionCallingStepOutcome:
            raise AssertionError("model call must not run")

    class _Host:
        step_executor = _StepExecutor()
        _current_messages: list[dict[str, object]] = []

        def build_step_state(self, **kwargs: object) -> FunctionCallingStepState:
            return FunctionCallingStepState(
                messages=[{"role": "user", "content": "use the tool"}],
                effective_system_prompt="system",
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "demo",
                            "description": "x" * 2_000,
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                selected_tool_names=["demo"],
            )

    runner = FunctionCallingLoopRunner(_Host())
    outcome = await runner.run(
        AgentRunRequest(
            turn=UserTurnInput(text="use the tool"),
            system_prompt="system",
            selected_tools=["demo"],
            user_id="user-1",
            model_capabilities=ModelCapabilityProfile(max_schema_tokens=20),
        ),
        control=null_run_control(),
    )

    assert outcome.status == "failed"
    assert outcome.failure_reason == "tool_schema_token_limit_exceeded"


@pytest.mark.asyncio
async def test_compacts_before_first_model_request() -> None:
    events: list[str] = []

    class _StepExecutor:
        async def execute_step(self, **kwargs: object) -> FunctionCallingStepOutcome:
            events.append("model_request")
            return FunctionCallingStepOutcome(status="completed", iteration=1, content="done")

    class _Host:
        step_executor = _StepExecutor()
        _current_messages: list[dict[str, object]] = []

        def build_step_state(self, **kwargs: object) -> FunctionCallingStepState:
            return FunctionCallingStepState(
                messages=[{"role": "user", "content": "hello"}],
                effective_system_prompt="system",
                tools=[{"type": "function", "function": {"name": "demo"}}],
            )

        async def apply_run_inputs(self, state: object, inbox: object) -> None:
            return None

        async def _prepare_context_for_model(
            self,
            state: FunctionCallingStepState,
            *,
            include_tools: bool = True,
        ) -> ExecutionOutcome | None:
            _ = (state, include_tools)
            events.append("compact")
            return None

    host = _Host()
    runner = FunctionCallingLoopRunner(host)
    run_input = AgentRunRequest(
        turn=UserTurnInput(text="hello"),
        system_prompt="system",
        selected_tools=["demo"],
        user_id="user-1",
    )

    outcome = await runner.run(run_input, control=null_run_control())

    assert outcome.status == "completed"
    assert events == ["compact", "model_request"]


@pytest.mark.asyncio
async def test_context_failure_stops_before_model_request() -> None:
    events: list[str] = []

    class _StepExecutor:
        async def execute_step(self, **kwargs: object) -> FunctionCallingStepOutcome:
            events.append("model_request")
            return FunctionCallingStepOutcome(status="completed", iteration=1, content="done")

    class _Host:
        step_executor = _StepExecutor()
        _current_messages: list[dict[str, object]] = []

        def build_step_state(self, **kwargs: object) -> FunctionCallingStepState:
            return FunctionCallingStepState(
                messages=[{"role": "user", "content": "hello"}],
                effective_system_prompt="system",
                tools=[],
            )

        async def apply_run_inputs(self, state: object, inbox: object) -> None:
            return None

        async def _prepare_context_for_model(
            self,
            state: FunctionCallingStepState,
            *,
            include_tools: bool = True,
        ) -> ExecutionOutcome | None:
            _ = include_tools
            events.append("prepare")
            return ExecutionOutcome(
                status="failed",
                content="",
                failure_reason="Context window exceeded",
                iterations=state.iteration,
            )

    runner = FunctionCallingLoopRunner(_Host())
    run_input = AgentRunRequest(
        turn=UserTurnInput(text="hello"),
        system_prompt="system",
        selected_tools=[],
        user_id="user-1",
    )

    outcome = await runner.run(run_input, control=null_run_control())

    assert outcome.status == "failed"
    assert outcome.failure_reason == "Context window exceeded"
    assert events == ["prepare"]


@pytest.mark.asyncio
async def test_plan_reader_failure_blocks_completion() -> None:
    class _FailingPlanReader:
        def current(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("plan store unavailable")

    class _StepExecutor:
        async def execute_step(self, **kwargs: object) -> FunctionCallingStepOutcome:
            return FunctionCallingStepOutcome(status="completed", iteration=1, content="done")

    class _Host:
        step_executor = _StepExecutor()
        _current_messages: list[dict[str, object]] = []

        def build_step_state(self, **kwargs: object) -> FunctionCallingStepState:
            return FunctionCallingStepState(
                messages=[{"role": "user", "content": "finish the task"}],
                effective_system_prompt="system",
                tools=[],
            )

        async def apply_run_inputs(self, state: object, inbox: object) -> None:
            return None

        async def _prepare_context_for_model(
            self,
            state: FunctionCallingStepState,
            *,
            include_tools: bool = True,
        ) -> ExecutionOutcome | None:
            _ = (state, include_tools)
            return None

    outcome = await FunctionCallingLoopRunner(_Host()).run(
        AgentRunRequest(
            turn=UserTurnInput(text="finish the task"),
            system_prompt="system",
            selected_tools=[],
            user_id="user-1",
            run_plan_reader=_FailingPlanReader(),
        ),
        control=null_run_control(),
    )

    assert outcome.status == "blocked"
    assert outcome.failure_reason == "plan_governance_unavailable"
    assert "canonical run plan" in outcome.content
