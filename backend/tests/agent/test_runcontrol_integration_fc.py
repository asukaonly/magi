"""Integration: FunctionCallingOrchestrator + RunControl bundle.

Verifies:
  - the bundle can be passed in place of the three legacy kwargs
  - retract is honored at the iteration boundary
  - suspend is honored at the iteration boundary
  - cancel/detach/steer continue to work via the bundle (regression check)
"""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

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


def test_execute_with_tools_accepts_control_kwarg() -> None:
    params = inspect.signature(FunctionCallingOrchestrator.execute_with_tools).parameters
    assert "control" in params, (
        "execute_with_tools must accept a `control: RunControl` kwarg"
    )


def test_execute_with_tools_legacy_kwargs_still_present_for_one_release() -> None:
    """Legacy cancel_token / steer_inbox / detach_signal must remain
    accepted for one release. They are folded into the bundle internally."""
    params = inspect.signature(FunctionCallingOrchestrator.execute_with_tools).parameters
    assert "cancel_token" in params
    assert "steer_inbox" in params
    assert "detach_signal" in params


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

    outcome = await orchestrator.execute_with_tools(
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

    outcome = await orchestrator.execute_with_tools(
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
async def test_execute_loop_with_legacy_kwargs_still_works(monkeypatch) -> None:
    """Legacy 3-kwarg API (cancel_token / steer_inbox / detach_signal)
    must continue to function — this preserves the existing FC test
    suite and external callers during the deprecation period."""
    from magi.agent.cancel import EventCancelToken

    orchestrator = _build_orchestrator()
    _patch_trace_and_event_helpers(monkeypatch, orchestrator)

    async def _never_called(**_kwargs):
        raise AssertionError("LLM should not be called when cancel is already set")

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _never_called)

    cancel = EventCancelToken()
    cancel.cancel(reason="user_request")

    outcome = await orchestrator.execute_with_tools(
        turn=UserTurnInput(text="hi", attachments=[], user_id=None, session_id=None),
        system_prompt="sys",
        selected_tools=[],
        user_id="u",
        conversation_history=[],
        max_iterations=5,
        cancel_token=cancel,
    )

    assert outcome.status == "cancelled"


@pytest.mark.asyncio
async def test_control_supplied_silently_ignores_legacy_kwargs(monkeypatch) -> None:
    """When both `control` and legacy kwargs are passed, the bundle is
    canonical and the legacy kwargs are silently dropped (by design —
    callers should pick one API or the other, not mix). Pin this
    behavior so a future "fix" that raises on the mixed-call path
    doesn't accidentally break external callers who pass extras."""
    from magi.agent.cancel import EventCancelToken

    orchestrator = _build_orchestrator()
    _patch_trace_and_event_helpers(monkeypatch, orchestrator)

    async def _never_called(**_kwargs):
        raise AssertionError("LLM should not be called when retract is already set")

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _never_called)

    # Bundle has retract set — that's what should win.
    control = null_run_control()
    retract = RetractSignal()
    retract.request(RetractRequested(reason="user_retract"))
    control.retract_signal = retract

    # Legacy kwarg has a cancelled token — this should be IGNORED.
    legacy_cancel = EventCancelToken()
    legacy_cancel.cancel(reason="legacy_should_be_ignored")

    outcome = await orchestrator.execute_with_tools(
        turn=UserTurnInput(text="hi", attachments=[], user_id=None, session_id=None),
        system_prompt="sys",
        selected_tools=[],
        user_id="u",
        conversation_history=[],
        max_iterations=5,
        cancel_token=legacy_cancel,
        control=control,
    )

    # Status should be "retracted" (from the bundle), NOT "cancelled" (from the legacy kwarg).
    assert outcome.status == "retracted"


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

    outcome = await orchestrator.execute_with_tools(
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
    """status='aborted' is a new value introduced by Task 7."""
    from magi.agent.execution.function_calling.step_executor import (
        FunctionCallingStepOutcome,
    )

    outcome = FunctionCallingStepOutcome(status="aborted", iteration=0)
    assert outcome.status == "aborted"


def test_function_calling_handler_passes_context_control_to_orchestrator() -> None:
    """Regression guard: FunctionCallingHandler must forward
    request.context.control as control= to execute_with_tools so signals
    fired via SessionRunCoordinator.request_retract reach the FC loop.

    Pre-fix: handler passed only legacy kwargs (cancel_token, detach_signal,
    steer_inbox), causing _resolve_control() to discard the registered bundle.
    """
    import inspect
    from magi.agent.task_agents.handlers.handlers import FunctionCallingHandler

    src = inspect.getsource(FunctionCallingHandler.execute)
    assert "control=" in src and (
        "request.context.control" in src or "context.control" in src
    ), (
        "FunctionCallingHandler.execute must pass `control=request.context.control` "
        "to execute_with_tools; otherwise SessionRunCoordinator.request_retract "
        "cannot reach the FC orchestrator"
    )


def test_function_calling_orchestrator_execute_with_tools_accepts_route_decision() -> None:
    import inspect
    from magi.agent.execution.function_calling import FunctionCallingOrchestrator

    sig = inspect.signature(FunctionCallingOrchestrator.execute_with_tools)
    assert "route_decision" in sig.parameters, (
        "FunctionCallingOrchestrator.execute_with_tools must accept route_decision"
    )


def test_function_calling_handler_passes_route_decision_to_orchestrator() -> None:
    """FunctionCallingHandler.execute must forward request.intent.route_decision
    as route_decision= to execute_with_tools."""
    import inspect
    from magi.agent.task_agents.handlers.handlers import FunctionCallingHandler

    src = inspect.getsource(FunctionCallingHandler.execute)
    assert "route_decision" in src and (
        "request.intent" in src or "intent.route_decision" in src
    ), (
        "FunctionCallingHandler.execute must pass intent.route_decision through"
    )


def test_function_calling_handler_passes_route_decision_to_engine() -> None:
    """FunctionCallingHandler must pass the typed routing result to the engine."""
    import inspect

    from magi.agent.task_agents.handlers.handlers import FunctionCallingHandler

    src = inspect.getsource(FunctionCallingHandler.execute)
    assert "route_decision=route_decision" in src
    assert "to_strategy_dict" not in src
