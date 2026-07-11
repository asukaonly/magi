from __future__ import annotations

import pytest

from magi.agent.execution.function_calling.loop_runner import FunctionCallingLoopRunner
from magi.agent.execution.function_calling.run_input import EngineRunInput
from magi.agent.execution.function_calling.step_models import (
    FunctionCallingStepOutcome,
    FunctionCallingStepState,
)
from magi.agent.turn_input import UserTurnInput
from magi.control.run_control import null_run_control


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

        async def apply_steer_messages(self, state: object, inbox: object) -> None:
            return None

        async def _try_compact(self, state: FunctionCallingStepState) -> None:
            events.append("compact")

    host = _Host()
    runner = FunctionCallingLoopRunner(host)
    run_input = EngineRunInput(
        turn=UserTurnInput(text="hello"),
        system_prompt="system",
        selected_tools=["demo"],
        user_id="user-1",
    )

    outcome = await runner.run(run_input, control=null_run_control())

    assert outcome.status == "completed"
    assert events == ["compact", "model_request"]
