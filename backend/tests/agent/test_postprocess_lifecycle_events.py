"""Postprocess emits run.retracted and run.suspended events alongside
the existing run.cancelled / run.completed events."""
from __future__ import annotations

import pytest

from magi.events.events import EventTypes


def test_event_types_define_retracted_and_suspended() -> None:
    assert hasattr(EventTypes, "RUN_RETRACTED")
    assert hasattr(EventTypes, "RUN_SUSPENDED")
    # Values are strings.
    assert isinstance(EventTypes.RUN_RETRACTED, str)
    assert isinstance(EventTypes.RUN_SUSPENDED, str)


def test_domain_payloads_define_run_retracted_and_run_suspended() -> None:
    from magi.events.domain_payloads import RunRetracted, RunSuspended

    r = RunRetracted(session_id="s", run_id="r", reason="user_retract", requested_by="user")
    assert r.session_id == "s"
    assert r.note == ""  # default

    s = RunSuspended(session_id="s", run_id="r", reason="window_closed", requested_by="user", note="bye")
    assert s.note == "bye"


@pytest.mark.asyncio
async def test_postprocess_emits_retracted_event_for_skip_emit_retracted_result() -> None:
    """OrchestrationLaunchHandler path: skip_emit=True, llm_trace={'retracted': True}.
    Postprocess must detect this and emit a run.retracted event despite the early skip-emit return."""
    from fixtures_postprocess import (
        build_postprocess_with_capture,
        build_execution_result_skip_emit_retracted,
        build_minimal_chat_context,
    )

    service, captured_events = build_postprocess_with_capture()
    context = build_minimal_chat_context(session_id="s1", session_run_id="r1")
    result = build_execution_result_skip_emit_retracted()

    await service.handle(context, result)

    event_types = [e["event_type"] for e in captured_events]
    assert EventTypes.RUN_RETRACTED in event_types
    matching = next(e for e in captured_events if e["event_type"] == EventTypes.RUN_RETRACTED)
    assert isinstance(matching["payload"], dict)
    assert "session_id" in matching["payload"]
    assert "run_id" in matching["payload"]
    assert "reason" in matching["payload"]


@pytest.mark.asyncio
async def test_postprocess_emits_retracted_event_for_direct_llm_abort_reason() -> None:
    """DirectLLMHandler path: response_text='', llm_trace={'abort_reason': 'retract:user_retract'}.
    Postprocess must detect this in the empty-response branch and emit run.retracted."""
    from fixtures_postprocess import (
        build_postprocess_with_capture,
        build_execution_result_direct_retract,
        build_minimal_chat_context,
    )

    service, captured_events = build_postprocess_with_capture()
    context = build_minimal_chat_context(session_id="s1", session_run_id="r1")
    result = build_execution_result_direct_retract()

    await service.handle(context, result)

    event_types = [e["event_type"] for e in captured_events]
    assert EventTypes.RUN_RETRACTED in event_types
    matching = next(e for e in captured_events if e["event_type"] == EventTypes.RUN_RETRACTED)
    assert isinstance(matching["payload"], dict)
    assert "session_id" in matching["payload"]
    assert "run_id" in matching["payload"]
    assert "reason" in matching["payload"]


@pytest.mark.asyncio
async def test_postprocess_emits_retracted_event_for_fc_execution_outcome() -> None:
    """FunctionCallingExecutionResult path: execution_outcome['status'] == 'retracted'.
    Postprocess must detect this and emit run.retracted."""
    from fixtures_postprocess import (
        build_postprocess_with_capture,
        build_execution_result_fc_retracted,
        build_minimal_chat_context,
    )

    service, captured_events = build_postprocess_with_capture()
    context = build_minimal_chat_context(session_id="s1", session_run_id="r1")
    result = build_execution_result_fc_retracted()

    await service.handle(context, result)

    event_types = [e["event_type"] for e in captured_events]
    assert EventTypes.RUN_RETRACTED in event_types
    matching = next(e for e in captured_events if e["event_type"] == EventTypes.RUN_RETRACTED)
    assert isinstance(matching["payload"], dict)
    assert "session_id" in matching["payload"]
    assert "run_id" in matching["payload"]
    assert "reason" in matching["payload"]


@pytest.mark.asyncio
async def test_postprocess_emits_suspended_event_for_fc_execution_outcome() -> None:
    """FunctionCallingExecutionResult: execution_outcome['status'] == 'suspended' → run.suspended."""
    from fixtures_postprocess import (
        build_postprocess_with_capture,
        build_execution_result_fc_suspended,
        build_minimal_chat_context,
    )

    service, captured_events = build_postprocess_with_capture()
    context = build_minimal_chat_context(session_id="s1", session_run_id="r1")
    result = build_execution_result_fc_suspended()

    await service.handle(context, result)

    event_types = [e["event_type"] for e in captured_events]
    assert EventTypes.RUN_SUSPENDED in event_types
    matching = next(e for e in captured_events if e["event_type"] == EventTypes.RUN_SUSPENDED)
    assert isinstance(matching["payload"], dict)
    assert "session_id" in matching["payload"]
    assert "run_id" in matching["payload"]
    assert "reason" in matching["payload"]


@pytest.mark.asyncio
async def test_postprocess_handle_does_not_crash_when_emitter_raises() -> None:
    """Lifecycle event emission is best-effort: if the emitter raises,
    postprocess.handle still returns a ChatParseOutcome without
    propagating the exception."""
    from fixtures_postprocess import (
        build_postprocess_with_capture,
        build_execution_result_skip_emit_retracted,
        build_minimal_chat_context,
    )

    service, _captured = build_postprocess_with_capture()

    # Replace emit_runtime_event on the live emitter instance with a raiser.
    async def _raising_emit(**_kwargs):
        raise RuntimeError("simulated emit failure")

    emitter = service._get_event_emitter()
    emitter.emit_runtime_event = _raising_emit

    context = build_minimal_chat_context(session_id="s1", session_run_id="r1")
    result = build_execution_result_skip_emit_retracted()

    # handle() must NOT raise — emission failures are best-effort.
    outcome = await service.handle(context, result)
    assert outcome is not None


@pytest.mark.asyncio
async def test_postprocess_does_not_emit_lifecycle_event_for_normal_completed_result() -> None:
    """A normal completed turn (response_text='hello', no retract markers)
    must NOT emit run.retracted or run.suspended events. Regression
    guard against future _detect_terminal_status drift."""
    from fixtures_postprocess import (
        build_postprocess_with_capture,
        build_minimal_chat_context,
    )
    from magi.agent.task_agents.common.contracts import ExecutionMode, ExecutionResult

    service, captured_events = build_postprocess_with_capture()
    context = build_minimal_chat_context(session_id="s1", session_run_id="r1")
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="hello, this is a normal completed response",
        llm_trace={},
    )

    await service.handle(context, result)

    lifecycle_event_types = {EventTypes.RUN_RETRACTED, EventTypes.RUN_SUSPENDED}
    captured_lifecycle = [
        e for e in captured_events if e["event_type"] in lifecycle_event_types
    ]
    assert captured_lifecycle == [], (
        f"Normal completion should not emit lifecycle events, but got: {captured_lifecycle}"
    )
