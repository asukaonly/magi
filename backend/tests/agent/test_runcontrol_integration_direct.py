"""Integration: DirectLLMHandler + RunControl.

DirectLLMHandler historically accepted no cancel/detach token, so the
user-visible cancel button did not work for direct LLM replies. After
Task 8, DirectLLMHandler must honor cancel and retract.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from magi.agent.cancel import EventCancelToken
from magi.agent.run_control import (
    RetractRequested,
    RetractSignal,
    RunControl,
    null_run_control,
)


def test_chat_runtime_context_carries_run_control() -> None:
    """ChatRuntimeContext must expose a ``control`` field so handlers can poll it."""
    from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext

    field_names = {f.name for f in ChatRuntimeContext.__dataclass_fields__.values()}
    assert "control" in field_names, (
        "ChatRuntimeContext must carry RunControl so handlers can poll it"
    )


def test_direct_llm_handler_execute_uses_control_from_context() -> None:
    """Verify DirectLLMHandler.execute reads request.context.control and
    propagates it into prompt_service calls. We assert this via source
    inspection — behavior tests below cover the runtime path."""
    import magi.agent.task_agents.handlers.direct_handler as dh

    src = inspect.getsource(dh.DirectLLMHandler.execute)
    assert "request.context.control" in src or "context.control" in src, (
        "DirectLLMHandler.execute must read control from the request context"
    )


@pytest.mark.asyncio
async def test_direct_llm_handler_aborts_stream_on_cancel(monkeypatch) -> None:
    """When the cancel_token in the runtime context's control is set,
    DirectLLMHandler.execute must stop reading from the stream and
    return a partial ExecutionResult with the chunks accumulated so far
    plus an abort_reason in llm_trace."""
    from agent.fixtures_direct_handler import (
        build_direct_handler_with_slow_stream,
        build_minimal_direct_request,
    )

    handler, prompt_service = build_direct_handler_with_slow_stream(
        chunks=["a", "b", "c"],
        chunk_delay_seconds=0.0,
    )
    control = null_run_control()
    cancel = EventCancelToken()
    cancel.cancel(reason="user_request")
    control.cancel_token = cancel

    request = build_minimal_direct_request(control=control, streaming_enabled=True)

    result = await handler.execute(request)

    # Pre-cancelled: zero chunks accumulated (stub raises CancellationRaised
    # before the first chunk).
    assert result.response_text == ""
    abort_reason = (result.llm_trace or {}).get("abort_reason", "")
    assert "cancel" in abort_reason


@pytest.mark.asyncio
async def test_direct_llm_handler_aborts_stream_on_retract(monkeypatch) -> None:
    """Retract during a direct LLM stream produces a partial result with
    abort_reason containing 'retract' and the chunks accumulated so far."""
    from agent.fixtures_direct_handler import (
        build_direct_handler_with_gated_stream,
        build_minimal_direct_request,
    )

    handler, prompt_service, gates = build_direct_handler_with_gated_stream(
        chunks=["x", "y", "z"],
    )
    control = null_run_control()
    retract = RetractSignal()
    control.retract_signal = retract

    request = build_minimal_direct_request(control=control, streaming_enabled=True)

    async def runner():
        return await handler.execute(request)

    # Let first chunk emit, then fire retract, then release the second gate.
    gates[0].set()
    task = asyncio.create_task(runner())

    # Spin a tick so the handler reads the first chunk.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    retract.request(RetractRequested(reason="user_retract"))
    gates[1].set()
    # Set remaining gates so the stream can complete naturally if not aborted.
    for g in gates[2:]:
        g.set()

    result = await asyncio.wait_for(task, timeout=2.0)

    abort_reason = (result.llm_trace or {}).get("abort_reason", "")
    assert "retract" in abort_reason
    # At least one chunk made it through before the retract.
    assert len(result.response_text) >= 1


@pytest.mark.asyncio
async def test_direct_llm_handler_aborts_non_streaming_call_on_pre_cancel(
    monkeypatch,
) -> None:
    """Non-streaming direct LLM with pre-cancelled control returns empty
    response with abort_reason and the underlying call_llm is not invoked."""
    from agent.fixtures_direct_handler import (
        build_direct_handler_with_simple_call,
        build_minimal_direct_request,
    )

    handler, prompt_service, call_count = build_direct_handler_with_simple_call(
        response_text="should-not-be-returned",
    )
    control = null_run_control()
    cancel = EventCancelToken()
    cancel.cancel(reason="user_request")
    control.cancel_token = cancel

    request = build_minimal_direct_request(control=control, streaming_enabled=False)
    result = await handler.execute(request)

    assert result.response_text == ""
    abort_reason = (result.llm_trace or {}).get("abort_reason", "")
    assert "cancel" in abort_reason
    assert call_count() == 0


@pytest.mark.asyncio
async def test_direct_llm_handler_aborts_non_streaming_call_on_pre_retract(
    monkeypatch,
) -> None:
    """Non-streaming direct LLM with pre-retract control returns empty
    response with abort_reason='retract:user_retract' and bridge call not made."""
    from agent.fixtures_direct_handler import (
        build_direct_handler_with_simple_call,
        build_minimal_direct_request,
    )

    handler, prompt_service, call_count = build_direct_handler_with_simple_call(
        response_text="should-not-be-returned",
    )
    control = null_run_control()
    retract = RetractSignal()
    retract.request(RetractRequested(reason="user_retract"))
    control.retract_signal = retract

    request = build_minimal_direct_request(control=control, streaming_enabled=False)
    result = await handler.execute(request)

    assert result.response_text == ""
    abort_reason = (result.llm_trace or {}).get("abort_reason", "")
    assert "retract" in abort_reason
    assert "user_retract" in abort_reason
    assert call_count() == 0
