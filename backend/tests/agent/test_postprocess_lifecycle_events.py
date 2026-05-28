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
