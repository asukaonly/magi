"""End-to-end smoke tests for the Phase A RunControl chain.

Validates that retract/cancel requests fired via SessionRunCoordinator and the
run-control signals propagate to handler / orchestrator outcomes.

NOTE: the orphaned run-lifecycle events (which had no subscriber and were
dropped at emit) were removed in #27. These tests therefore assert the real
retract/cancel behavior — signal observed, abort_reason, outcome status — not
event emission.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from magi.agent.cancel import EventCancelToken
from magi.agent.execution.function_calling import FunctionCallingOrchestrator
from magi.agent.run_control import (
    RetractRequested,
    null_run_control,
)
from magi.agent.turn_input import UserTurnInput

from agent.fixtures_direct_handler import (
    build_direct_handler_with_gated_stream,
    build_direct_handler_with_slow_stream,
    build_minimal_direct_request,
)
from agent.fixtures_session_run_coordinator import (
    build_coordinator_with_active_run,
)


class _FakeToolRegistry:
    def is_skill(self, _tool_name: str) -> bool:
        return False

    def get_tool_info(self, _tool_name: str):
        return None


def _build_fc_orchestrator() -> FunctionCallingOrchestrator:
    return FunctionCallingOrchestrator(
        tool_registry=_FakeToolRegistry(),
        llm_adapter=SimpleNamespace(model_name="fake-model", provider_name="fake-provider"),
    )


async def _noop_async(*args, **kwargs):
    return None


def _patch_fc_trace_helpers(orchestrator: FunctionCallingOrchestrator) -> None:
    """Patch trace/event helpers to no-ops (per existing FC integration test pattern)."""
    for helper in (
        "_start_iteration_trace",
        "_complete_iteration_trace",
        "_emit_loop_event",
        "_emit_tool_result",
        "_persist_llm_trace",
        "_persist_tool_trace",
    ):
        setattr(orchestrator, helper, _noop_async)


@pytest.mark.asyncio
async def test_e2e_direct_llm_retract_via_coordinator_observed_by_handler() -> None:
    """E2E: SessionRunCoordinator.request_retract sets control.retract_signal →
    DirectLLMHandler observes it and exits with a retract abort_reason."""
    # 1. Set up the coordinator with an active run + registered bundle.
    coordinator, control = build_coordinator_with_active_run(session_id="e2e_s1")

    # 2. Build the DirectLLMHandler with a stub stream.
    handler, _stub_prompt_service = build_direct_handler_with_slow_stream(
        chunks=["partial-content"],
        chunk_delay_seconds=0.0,
    )

    # 3. Fire retract THROUGH the coordinator. This sets control.retract_signal.
    fired = coordinator.request_retract(
        session_id="e2e_s1",
        payload=RetractRequested(reason="user_retract", note="e2e_test"),
    )
    assert fired is True
    assert control.retract_signal.is_requested()

    # 4. Execute the handler with the now-signaled bundle and verify it observed
    #    retract (empty result carrying a retract abort_reason).
    request = build_minimal_direct_request(
        control=control,
        streaming_enabled=True,
    )
    result = await handler.execute(request)

    assert "abort_reason" in (result.llm_trace or {})
    assert "retract" in result.llm_trace["abort_reason"]


@pytest.mark.asyncio
async def test_e2e_function_calling_retract_via_signal_yields_retracted_outcome() -> None:
    """E2E: retract pre-set on the bundle → FunctionCallingOrchestrator observes
    it at the iteration boundary and returns ExecutionOutcome(status='retracted')
    without ever calling the LLM."""
    orchestrator = _build_fc_orchestrator()
    _patch_fc_trace_helpers(orchestrator)

    async def _never_called(**_kwargs):
        raise AssertionError("LLM should not be called when retract already set")

    setattr(orchestrator, "_call_llm_with_tools", _never_called)

    # Build a bundle with pre-set retract.
    control = null_run_control()
    control.retract_signal.request(RetractRequested(reason="user_retract"))

    outcome = await orchestrator.execute_with_tools(
        turn=UserTurnInput(text="hi", attachments=[], user_id=None, session_id=None),
        system_prompt="sys",
        selected_tools=[],
        user_id="u",
        conversation_history=[],
        max_iterations=5,
        control=control,
    )

    assert outcome.status == "retracted"


@pytest.mark.asyncio
async def test_e2e_cancel_via_session_cancel_token_in_direct_llm() -> None:
    """E2E: A cancel token cancelled externally during a streaming direct LLM
    call results in a partial response + cancel abort_reason."""
    handler, _stub_prompt_service, gates = build_direct_handler_with_gated_stream(
        chunks=["a", "b", "c"],
    )

    cancel = EventCancelToken()
    control = null_run_control()
    control.cancel_token = cancel

    request = build_minimal_direct_request(
        control=control,
        streaming_enabled=True,
    )

    # Concurrently fire the cancel after the first chunk.
    async def trigger():
        await asyncio.sleep(0)
        gates[0].set()
        # Yield until handler has consumed first chunk.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        cancel.cancel(reason="user_request")
        for g in gates[1:]:
            g.set()

    task = asyncio.create_task(trigger())
    result = await asyncio.wait_for(handler.execute(request), timeout=2.0)
    await task

    # The cancel should produce a partial-or-empty result with abort_reason.
    abort_reason = (result.llm_trace or {}).get("abort_reason", "")
    assert "cancel" in abort_reason
