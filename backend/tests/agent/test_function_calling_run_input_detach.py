"""Integration tests for run-input and detach handling in the unified loop."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from agent.agent_run_helpers import run_agent

from magi.agent.execution.function_calling import (
    ExecutionOutcome,
    FunctionCallingOrchestrator,
    ToolCall,
    ToolCallResult,
)
from magi.control.run_control import (
    DetachRequested,
    DetachSignal,
    RunInputInbox,
    RunInputMessage,
    null_run_control,
)
from magi.agent.turn_input import UserTurnInput


class _FakeToolRegistry:
    def is_skill(self, _tool_name: str) -> bool:
        return False

    def get_tool_info(self, _tool_name: str):  # type: ignore[no-untyped-def]
        return None


def _build_orchestrator() -> FunctionCallingOrchestrator:
    return FunctionCallingOrchestrator(
        tool_registry=_FakeToolRegistry(),
        llm_adapter=SimpleNamespace(model_name="fake-model", provider_name="fake-provider"),
    )


def _run_control(*, input_queue=None, detach_signal=None):  # type: ignore[no-untyped-def]
    control = null_run_control()
    if input_queue is not None:
        control.input_queue = input_queue
    if detach_signal is not None:
        control.detach_signal = detach_signal
    return control


def _patch_trace_and_event_helpers(monkeypatch, orchestrator: FunctionCallingOrchestrator) -> None:
    async def _noop_async(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        return None

    monkeypatch.setattr(orchestrator, "_start_iteration_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_complete_iteration_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_emit_loop_event", _noop_async)
    monkeypatch.setattr(orchestrator, "_emit_tool_result", _noop_async)
    monkeypatch.setattr(orchestrator, "_persist_llm_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_persist_tool_trace", _noop_async)


@pytest.mark.asyncio
async def test_execute_with_tools_injects_run_inputs_before_next_llm_call(
    monkeypatch,
) -> None:
    orchestrator = _build_orchestrator()
    _patch_trace_and_event_helpers(monkeypatch, orchestrator)

    inbox = RunInputInbox()
    # Push an input *before* the run starts so the first iteration
    # already sees it — this mimics the chat handler routing a follow-up
    # into an in-flight run at the boundary preceding the next LLM call.
    await inbox.push(RunInputMessage(content="use Python, not JavaScript"))

    llm_call_messages: list[list[dict[str, object]]] = []

    async def _fake_call_llm_with_tools(*, messages, **_kwargs):  # type: ignore[no-untyped-def]
        # Capture a shallow copy so later mutations don't change history.
        llm_call_messages.append([dict(m) for m in messages])
        return {
            "assistant_message": {"role": "assistant", "content": "acknowledged"},
            "content": "acknowledged",
            "tool_calls": [],
            "llm_trace": {"model": "fake-model"},
        }

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _fake_call_llm_with_tools)

    outcome = await run_agent(orchestrator,
        turn=UserTurnInput(text="Write a sorting example.", attachments=[], user_id=None, session_id=None),
        system_prompt="system prompt",
        selected_tools=[],
        user_id="u",
        max_iterations=5,
        control=_run_control(input_queue=inbox),
    )

    assert outcome.status == "completed"
    assert len(llm_call_messages) == 1
    # The run input lands after the original user message as a separate
    # ``user`` entry and precedes any assistant response, ready for the next
    # LLM call.
    contents = [(m.get("role"), m.get("content")) for m in llm_call_messages[0]]
    assert contents == [
        ("user", "Write a sorting example."),
        ("user", "use Python, not JavaScript"),
    ]


@pytest.mark.asyncio
async def test_execute_with_tools_skips_empty_run_inputs(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    _patch_trace_and_event_helpers(monkeypatch, orchestrator)

    inbox = RunInputInbox()
    await inbox.push(RunInputMessage(content="   "))
    await inbox.push(RunInputMessage(content=""))

    async def _fake_call_llm_with_tools(*, messages, **_kwargs):  # type: ignore[no-untyped-def]
        return {
            "assistant_message": {"role": "assistant", "content": "ok"},
            "content": "ok",
            "tool_calls": [],
            "llm_trace": {"model": "fake-model"},
        }

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _fake_call_llm_with_tools)

    outcome = await run_agent(orchestrator,
        turn=UserTurnInput(text="hi", attachments=[], user_id=None, session_id=None),
        system_prompt="sys",
        selected_tools=[],
        user_id="u",
        max_iterations=3,
        control=_run_control(input_queue=inbox),
    )
    assert outcome.status == "completed"


@pytest.mark.asyncio
async def test_execute_with_tools_returns_detached_with_snapshot(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    _patch_trace_and_event_helpers(monkeypatch, orchestrator)

    detach = DetachSignal()
    iteration_counter = {"value": 0}

    async def _fake_call_llm_with_tools(*, messages, **_kwargs):  # type: ignore[no-untyped-def]
        iteration_counter["value"] += 1
        if iteration_counter["value"] == 1:
            # First iteration: model asks for a tool. Detach is flipped
            # *after* the tool batch so the second iteration's boundary
            # observes the signal and exits.
            return {
                "assistant_message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "noop_tool", "arguments": "{}"},
                        }
                    ],
                },
                "tool_calls": [ToolCall(id="call_1", name="noop_tool", arguments={})],
                "llm_trace": {"model": "fake-model"},
            }
        # Should never be reached; detach fires before second LLM call.
        raise AssertionError("second LLM call must not happen after detach")

    async def _fake_execute_tool_call(**kwargs):  # type: ignore[no-untyped-def]
        tool_call = kwargs["tool_call"]
        # Simulate the chat layer setting the detach flag while the tool
        # result arrives.
        detach.request(DetachRequested(reason="user_request", note="move to bg"))
        return ToolCallResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=True,
            data={"ok": True},
            execution_time=0.01,
        )

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _fake_call_llm_with_tools)
    monkeypatch.setattr(orchestrator, "_execute_tool_call", _fake_execute_tool_call)

    outcome = await run_agent(orchestrator,
        turn=UserTurnInput(text="start work", attachments=[], user_id=None, session_id=None),
        system_prompt="sys",
        selected_tools=["noop_tool"],
        user_id="u",
        max_iterations=5,
        control=_run_control(detach_signal=detach),
    )

    assert isinstance(outcome, ExecutionOutcome)
    assert outcome.status == "detached"
    assert outcome.detached is True
    assert outcome.iterations == 1  # boundary after iter 1, before iter 2
    assert outcome.content == ""
    assert outcome.snapshot is not None
    # Snapshot must preserve the in-progress messages so a background
    # worker can resume at exactly this point.
    roles = [msg.get("role") for msg in outcome.snapshot.messages]
    assert roles[0] == "user"
    assert "assistant" in roles
    assert "tool" in roles
    assert outcome.snapshot.reason == "user_request"
    assert outcome.snapshot.note == "move to bg"


@pytest.mark.asyncio
async def test_execute_with_tools_detach_before_first_llm_call(monkeypatch) -> None:
    """Pre-flipped detach exits on iteration 0 without any LLM call."""
    orchestrator = _build_orchestrator()
    _patch_trace_and_event_helpers(monkeypatch, orchestrator)

    detach = DetachSignal()
    detach.request(DetachRequested(reason="pre_flight"))

    async def _never_called(**_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("LLM must not be invoked when detach is pre-set")

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _never_called)

    outcome = await run_agent(orchestrator,
        turn=UserTurnInput(text="hi", attachments=[], user_id=None, session_id=None),
        system_prompt="sys",
        selected_tools=[],
        user_id="u",
        max_iterations=5,
        control=_run_control(detach_signal=detach),
    )

    assert outcome.status == "detached"
    assert outcome.iterations == 0
    assert outcome.snapshot is not None
    # The seeded user message is preserved so the background worker can
    # start from scratch but with the correct goal.
    assert outcome.snapshot.messages == [{"role": "user", "content": "hi"}]
    assert outcome.snapshot.reason == "pre_flight"


@pytest.mark.asyncio
async def test_execute_with_tools_without_signals_behaves_like_before(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    _patch_trace_and_event_helpers(monkeypatch, orchestrator)

    async def _fake_call_llm_with_tools(**_kwargs):  # type: ignore[no-untyped-def]
        return {
            "assistant_message": {"role": "assistant", "content": "done"},
            "content": "done",
            "tool_calls": [],
            "llm_trace": {"model": "fake-model"},
        }

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _fake_call_llm_with_tools)

    outcome = await run_agent(orchestrator,
        turn=UserTurnInput(text="hi", attachments=[], user_id=None, session_id=None),
        system_prompt="sys",
        selected_tools=[],
        user_id="u",
        max_iterations=3,
    )

    assert outcome.status == "completed"
    assert outcome.content == "done"
    assert outcome.snapshot is None
