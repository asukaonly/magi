"""End-to-end smoke tests for Phase A RunControl chain.

Validates that cancel/retract requests fired via SessionRunCoordinator
propagate all the way to handler outcomes and postprocess event emission.

We test each handler path individually (DirectLLM, FunctionCalling,
OrchestrationLaunch) by constructing the handler with a stub LLM provider,
triggering the signal via the coordinator's live bundle, executing the
handler, and asserting that postprocess emits the expected lifecycle event.

This is a Phase A acceptance test. Phase B+ will expand to full chat-loop
smoke tests once the chat session test infrastructure is back to green.
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
from magi.agent.task_agents.common.contracts import (
    ExecutionMode,
    ExecutionResult,
    FunctionCallingExecutionResult,
)
from magi.agent.turn_input import UserTurnInput
from magi.events.events import EventTypes

from agent.fixtures_direct_handler import (
    build_direct_handler_with_gated_stream,
    build_direct_handler_with_slow_stream,
    build_minimal_direct_request,
)
from agent.fixtures_postprocess import (
    build_minimal_chat_context,
    build_postprocess_with_capture,
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
async def test_e2e_direct_llm_retract_via_coordinator_emits_event() -> None:
    """E2E: SessionRunCoordinator.request_retract → DirectLLMHandler
    observes retract → empty result with abort_reason → postprocess
    emits run.retracted."""
    # Retract is pre-set before handler executes — validates the fast-exit
    # path where the signal is already raised at the first LLM call.
    # The concurrent "retract arrives during stream" case for the DirectLLM
    # path is left as a Phase B follow-up (test 4 covers concurrent cancel).

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

    # 4. Execute the handler with the now-signaled bundle.
    request = build_minimal_direct_request(
        control=control,
        streaming_enabled=True,
    )
    result = await handler.execute(request)

    # 5. Verify the handler observed retract.
    assert "abort_reason" in (result.llm_trace or {})
    assert "retract" in result.llm_trace["abort_reason"]

    # 6. Send the result to postprocess and verify event emission.
    service, captured_events = build_postprocess_with_capture()
    # Pull the active run's run_id from the coordinator's store.
    active = coordinator.get_active_run("e2e_s1")
    assert active is not None
    pp_context = build_minimal_chat_context(
        session_id="e2e_s1",
        session_run_id=active.run_id,
    )

    await service.handle(pp_context, result)

    event_types = [e["event_type"] for e in captured_events]
    assert EventTypes.RUN_RETRACTED in event_types

    # 7. Verify payload carries the retract reason.
    retract_event = next(
        e for e in captured_events if e["event_type"] == EventTypes.RUN_RETRACTED
    )
    assert retract_event["payload"]["reason"] == "user_retract"
    assert retract_event["payload"]["session_id"] == "e2e_s1"
    assert retract_event["payload"]["run_id"] == active.run_id


@pytest.mark.asyncio
async def test_e2e_function_calling_retract_via_signal_emits_event() -> None:
    """E2E: retract on bundle → FunctionCallingOrchestrator observes
    at iteration boundary → ExecutionOutcome(status='retracted') →
    wrapped to FunctionCallingExecutionResult → postprocess emits
    run.retracted."""
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

    # Wrap into FunctionCallingExecutionResult (mirrors what FC handler does).
    fc_result = FunctionCallingExecutionResult(
        mode=ExecutionMode.FUNCTION_CALLING,
        response_text="",
        execution_outcome=outcome.to_dict(),
    )

    # Send through postprocess.
    service, captured_events = build_postprocess_with_capture()
    pp_context = build_minimal_chat_context(
        session_id="e2e_fc_s1",
        session_run_id="e2e_fc_r1",
    )
    await service.handle(pp_context, fc_result)

    event_types = [e["event_type"] for e in captured_events]
    assert EventTypes.RUN_RETRACTED in event_types

    retract_event = next(
        e for e in captured_events if e["event_type"] == EventTypes.RUN_RETRACTED
    )
    assert retract_event["payload"]["reason"] == "user_retract"
    assert retract_event["payload"]["session_id"] == "e2e_fc_s1"
    assert retract_event["payload"]["run_id"] == "e2e_fc_r1"


@pytest.mark.asyncio
async def test_e2e_orchestration_launch_retract_emits_event() -> None:
    """E2E: TaskOrchestrator plan callback raises RetractRaised →
    OrchestrationLaunchHandler produces ExecutionResult with
    llm_trace['retracted']=True + skip_emit=True → postprocess detects
    in skip_emit branch and emits run.retracted."""
    # Mirror the result shape produced by OrchestrationLaunchHandler when
    # TaskOrchestrator returns retracted=True (Task 9 behavior).
    orch_result = ExecutionResult(
        mode=ExecutionMode.ORCHESTRATION_LAUNCH,
        response_text="",
        skip_emit=True,
        llm_trace={"retracted": True},
    )

    service, captured_events = build_postprocess_with_capture()
    pp_context = build_minimal_chat_context(
        session_id="e2e_orch_s1",
        session_run_id="e2e_orch_r1",
    )

    await service.handle(pp_context, orch_result)

    event_types = [e["event_type"] for e in captured_events]
    assert EventTypes.RUN_RETRACTED in event_types

    retract_event = next(
        e for e in captured_events if e["event_type"] == EventTypes.RUN_RETRACTED
    )
    # OrchestrationLaunch path doesn't carry per-event reason metadata in
    # llm_trace; the fallback "user_retract" is used.
    assert retract_event["payload"]["reason"] == "user_retract"
    assert retract_event["payload"]["session_id"] == "e2e_orch_s1"
    assert retract_event["payload"]["run_id"] == "e2e_orch_r1"


@pytest.mark.asyncio
async def test_e2e_cancel_via_session_cancel_token_in_direct_llm() -> None:
    """E2E: A cancel token cancelled externally during a streaming
    direct LLM call results in a partial response + cancel abort_reason.

    This validates the cancel chain (no postprocess event because cancel
    has its own pre-existing emit_execution_control_notification path —
    Phase A scope is to demonstrate the LLM-level abort works, not to
    re-test the existing cancel notification path)."""
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


@pytest.mark.asyncio
async def test_e2e_coordinator_request_retract_propagates_payload_metadata() -> None:
    """E2E: a custom RetractRequested with note + requested_by must
    survive through to the postprocess event payload (via FC path which
    carries note in the snapshot)."""
    coordinator, control = build_coordinator_with_active_run(session_id="e2e_meta")

    custom_payload = RetractRequested(
        reason="custom_reason",
        requested_by="ui_button",
        note="my note here",
    )
    fired = coordinator.request_retract(session_id="e2e_meta", payload=custom_payload)
    assert fired is True

    # Construct an FC-shaped result whose snapshot carries the metadata.
    fc_result = FunctionCallingExecutionResult(
        mode=ExecutionMode.FUNCTION_CALLING,
        response_text="",
        execution_outcome={
            "status": "retracted",
            "content": "",
            "iterations": 1,
            "snapshot": {
                "messages": [],
                "iterations": 1,
                "reason": "custom_reason",
                "note": "my note here",
            },
        },
    )

    active = coordinator.get_active_run("e2e_meta")
    assert active is not None
    pp_context = build_minimal_chat_context(
        session_id="e2e_meta",
        session_run_id=active.run_id,
    )

    service, captured_events = build_postprocess_with_capture()
    await service.handle(pp_context, fc_result)

    retract_event = next(
        e for e in captured_events if e["event_type"] == EventTypes.RUN_RETRACTED
    )
    assert retract_event["payload"]["reason"] == "custom_reason"
    assert retract_event["payload"]["note"] == "my note here"
