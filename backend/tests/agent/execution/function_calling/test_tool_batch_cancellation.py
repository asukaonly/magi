from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from magi.agent.cancel import EventCancelToken
from magi.agent.execution.function_calling.step_models import (
    FunctionCallingStepState,
    StepExecutionContext,
)
from magi.agent.execution.function_calling.step_tool_batch import (
    FunctionCallingToolBatchExecutor,
)
from magi.agent.execution.function_calling.types import ToolCallResult


def _state() -> FunctionCallingStepState:
    return FunctionCallingStepState(
        messages=[],
        effective_system_prompt="system",
        tools=[],
    )


def _context() -> StepExecutionContext:
    return StepExecutionContext(
        user_message="run tool",
        user_id="user-1",
        session_id="session-1",
        session_run_id="run-1",
        session_run_revision=0,
        turn_id="turn-1",
        intent="test",
        execution_agent_id="agent-1",
        execution_workspace="/tmp/workspace",
        route_decision=None,
    )


@pytest.mark.asyncio
async def test_cancellation_stops_in_flight_tool_and_waits_for_cleanup() -> None:
    started = asyncio.Event()
    cleaned = asyncio.Event()

    class _Driver:
        @staticmethod
        def _tool_call_fingerprint(name, arguments):  # type: ignore[no-untyped-def]
            return f"{name}:{arguments}"

        @staticmethod
        async def _execute_tool_call(**kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

    executor = FunctionCallingToolBatchExecutor(_Driver())
    cancel_token = EventCancelToken()
    tool_call = SimpleNamespace(id="call-1", name="long_tool", arguments={})
    execution = asyncio.create_task(
        executor._execute_one_tool_call(
            state=_state(),
            tool_call=tool_call,
            ctx=_context(),
            iteration=1,
            cancel_token=cancel_token,
        )
    )

    await started.wait()
    cancel_token.cancel(reason="user_cancelled")
    record = await asyncio.wait_for(execution, timeout=1.0)

    assert cleaned.is_set()
    assert record.result.success is False
    assert record.result.error_code == "CANCELLED"
    assert record.result.error == "user_cancelled"


@pytest.mark.asyncio
async def test_completed_tool_result_wins_before_cancellation() -> None:
    expected = ToolCallResult(
        tool_call_id="call-1",
        tool_name="fast_tool",
        success=True,
        data={"ok": True},
    )

    class _Driver:
        @staticmethod
        def _tool_call_fingerprint(name, arguments):  # type: ignore[no-untyped-def]
            return f"{name}:{arguments}"

        @staticmethod
        async def _execute_tool_call(**kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return expected

    executor = FunctionCallingToolBatchExecutor(_Driver())
    record = await executor._execute_one_tool_call(
        state=_state(),
        tool_call=SimpleNamespace(id="call-1", name="fast_tool", arguments={}),
        ctx=_context(),
        iteration=1,
        cancel_token=EventCancelToken(),
    )

    assert record.result is expected
