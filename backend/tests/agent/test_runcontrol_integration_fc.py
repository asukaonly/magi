"""Integration coverage for unified agent-run control signals."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from agent.agent_run_helpers import run_agent

from magi.agent.execution.function_calling import (
    ExecutionOutcome,
    FunctionCallingOrchestrator,
)
from magi.control.run_control import (
    RetractRequested,
    RetractSignal,
    RunControl,
    SuspendRequested,
    SuspendSignal,
    null_run_control,
)
from magi.agent.turn_input import UserTurnInput


class _FakeToolRegistry:
    def is_skill(self, _tool_name: str) -> bool:
        return False

    def get_tool_info(self, _tool_name: str):
        return None


def _build_orchestrator() -> FunctionCallingOrchestrator:
    return FunctionCallingOrchestrator(
        tool_registry=_FakeToolRegistry(),
        llm_adapter=SimpleNamespace(model_name="fake-model", provider_name="fake-provider"),
    )


def _patch_trace_and_event_helpers(monkeypatch, orchestrator: FunctionCallingOrchestrator) -> None:
    async def _noop_async(*args, **kwargs):
        _ = (args, kwargs)
        return None

    monkeypatch.setattr(orchestrator, "_start_iteration_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_complete_iteration_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_emit_loop_event", _noop_async)
    monkeypatch.setattr(orchestrator, "_emit_tool_result", _noop_async)
    monkeypatch.setattr(orchestrator, "_persist_llm_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_persist_tool_trace", _noop_async)


@pytest.mark.asyncio
async def test_execute_loop_returns_retracted_outcome_when_retract_signal_set(
    monkeypatch,
) -> None:
    """When RetractSignal is set, the FC loop must exit at the next
    iteration boundary with ExecutionOutcome(status='retracted')."""
    orchestrator = _build_orchestrator()
    _patch_trace_and_event_helpers(monkeypatch, orchestrator)

    async def _never_called(**_kwargs):
        raise AssertionError("LLM should not be called when retract is already set")

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _never_called)

    control = null_run_control()
    retract = RetractSignal()
    retract.request(RetractRequested(reason="user_retract"))
    control.retract_signal = retract

    outcome = await run_agent(orchestrator,
        turn=UserTurnInput(text="hi", attachments=[], user_id=None, session_id=None),
        system_prompt="sys",
        selected_tools=[],
        user_id="u",
        conversation_history=[],
        max_iterations=5,
        control=control,
    )

    assert isinstance(outcome, ExecutionOutcome)
    assert outcome.status == "retracted"
    # Snapshot is preserved so DeliveryRouter could roll back partial output.
    assert outcome.snapshot is not None


@pytest.mark.asyncio
async def test_execute_loop_returns_suspended_outcome_when_suspend_signal_set(
    monkeypatch,
) -> None:
    """When SuspendSignal is set, the FC loop must exit at the next
    iteration boundary with ExecutionOutcome(status='suspended')."""
    orchestrator = _build_orchestrator()
    _patch_trace_and_event_helpers(monkeypatch, orchestrator)

    async def _never_called(**_kwargs):
        raise AssertionError("LLM should not be called when suspend is already set")

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _never_called)

    control = null_run_control()
    suspend = SuspendSignal()
    suspend.request(SuspendRequested(reason="window_closed"))
    control.suspend_signal = suspend

    outcome = await run_agent(orchestrator,
        turn=UserTurnInput(text="hi", attachments=[], user_id=None, session_id=None),
        system_prompt="sys",
        selected_tools=[],
        user_id="u",
        conversation_history=[],
        max_iterations=5,
        control=control,
    )

    assert outcome.status == "suspended"
    assert outcome.snapshot is not None


@pytest.mark.asyncio
async def test_execute_loop_returns_retracted_when_retract_fires_during_llm_call(
    monkeypatch,
) -> None:
    """When RetractSignal is set DURING the LLM call (not at iteration
    boundary), CancellableLLMClient raises RetractRaised, step_executor
    converts to status='aborted', and the orchestrator's next iteration
    polls control and returns ExecutionOutcome(status='retracted')."""
    orchestrator = _build_orchestrator()
    _patch_trace_and_event_helpers(monkeypatch, orchestrator)

    control = null_run_control()
    retract = RetractSignal()
    control.retract_signal = retract

    # Fake the LLM call to set the retract signal DURING the call.
    call_count = 0

    async def _fake_call_llm_with_tools(**_kwargs):
        nonlocal call_count
        call_count += 1
        # Set retract during the LLM call. The orchestrator should
        # observe it at the next iteration boundary and return retracted.
        retract.request(RetractRequested(reason="user_retract"))
        return {
            "assistant_message": {"role": "assistant", "content": "ack"},
            "content": "ack",
            "tool_calls": [],
            "llm_trace": {"model": "fake-model"},
        }

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _fake_call_llm_with_tools)

    outcome = await run_agent(orchestrator,
        turn=UserTurnInput(text="hi", attachments=[], user_id=None, session_id=None),
        system_prompt="sys",
        selected_tools=[],
        user_id="u",
        conversation_history=[],
        max_iterations=3,
        control=control,
    )

    assert outcome.status == "retracted"
    # The LLM was called exactly once (the first iteration); the second
    # iteration short-circuits on retract before another LLM call.
    assert call_count == 1


def test_step_executor_accepts_control_kwarg() -> None:
    import inspect
    from magi.agent.execution.function_calling.step_executor import (
        FunctionCallingStepExecutor,
    )

    params = inspect.signature(FunctionCallingStepExecutor.execute_step).parameters
    assert "control" in params, (
        "FunctionCallingStepExecutor.execute_step must accept a `control: RunControl` kwarg"
    )


def test_step_outcome_supports_aborted_status() -> None:
    from magi.agent.execution.function_calling.step_executor import (
        FunctionCallingStepOutcome,
    )

    outcome = FunctionCallingStepOutcome(status="aborted", iteration=0)
    assert outcome.status == "aborted"
