"""Tests for the ``detach_to_background`` builtin tool."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.agent.execution.function_calling import (
    FunctionCallingOrchestrator,
    ToolCall,
    ToolCallResult,
)
from magi.agent.run_control import (
    DetachSignal,
    bind_detach_signal,
    current_detach_signal,
)
from magi.tools.builtin.detach_to_background_tool import DetachToBackgroundTool
from magi.tools.schema import ToolExecutionContext
from magi.agent.turn_input import UserTurnInput


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent")


@pytest.mark.asyncio
async def test_detach_tool_fails_without_active_signal() -> None:
    tool = DetachToBackgroundTool()

    result = await tool.execute({"reason": "long_running"}, _ctx())

    assert result.success is False
    assert result.error_code == "detach_not_supported"


@pytest.mark.asyncio
async def test_detach_tool_flips_the_bound_signal() -> None:
    tool = DetachToBackgroundTool()
    signal = DetachSignal()

    with bind_detach_signal(signal):
        result = await tool.execute(
            {"reason": "deep_research", "note": "scanning 400 commits"},
            _ctx(),
        )

    assert result.success is True
    assert result.data["status"] == "detach_requested"
    assert result.data["reason"] == "deep_research"
    assert result.data["note"] == "scanning 400 commits"
    assert result.data["already_requested"] is False
    assert signal.is_requested() is True
    assert signal.payload is not None
    assert signal.payload.reason == "deep_research"
    assert signal.payload.requested_by == "llm"
    assert signal.payload.note == "scanning 400 commits"


@pytest.mark.asyncio
async def test_detach_tool_is_idempotent_for_second_call() -> None:
    tool = DetachToBackgroundTool()
    signal = DetachSignal()

    with bind_detach_signal(signal):
        first = await tool.execute({"reason": "first"}, _ctx())
        second = await tool.execute({"reason": "second"}, _ctx())

    assert first.success is True and first.data["already_requested"] is False
    assert second.success is True and second.data["already_requested"] is True
    # The first request's payload must be preserved.
    assert signal.payload is not None
    assert signal.payload.reason == "first"


def test_bind_detach_signal_restores_on_exit() -> None:
    outer = DetachSignal()
    inner = DetachSignal()

    with bind_detach_signal(outer):
        assert current_detach_signal() is outer
        with bind_detach_signal(inner):
            assert current_detach_signal() is inner
        assert current_detach_signal() is outer
    assert current_detach_signal() is None


def test_bind_detach_signal_none_is_noop() -> None:
    assert current_detach_signal() is None
    with bind_detach_signal(None):
        assert current_detach_signal() is None


# ---------------------------------------------------------------------
# Integration: orchestrator binds the signal so the tool works end-to-end
# ---------------------------------------------------------------------


class _FakeToolRegistry:
    def __init__(self, tool: DetachToBackgroundTool) -> None:
        self._tool = tool

    def is_skill(self, _tool_name: str) -> bool:
        return False

    def get_tool_info(self, _tool_name: str):  # type: ignore[no-untyped-def]
        return None


def _patch_trace_and_event_helpers(monkeypatch, orchestrator) -> None:  # type: ignore[no-untyped-def]
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
async def test_orchestrator_bind_makes_detach_tool_flip_signal_and_exit(
    monkeypatch,
) -> None:
    tool = DetachToBackgroundTool()
    orchestrator = FunctionCallingOrchestrator(
        tool_registry=_FakeToolRegistry(tool),
        llm_adapter=SimpleNamespace(
            model_name="fake-model", provider_name="fake-provider"
        ),
    )
    _patch_trace_and_event_helpers(monkeypatch, orchestrator)

    detach = DetachSignal()
    iteration_counter = {"value": 0}

    async def _fake_call_llm_with_tools(**_kwargs):  # type: ignore[no-untyped-def]
        iteration_counter["value"] += 1
        if iteration_counter["value"] == 1:
            return {
                "assistant_message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "detach_to_background",
                                "arguments": "{\"reason\": \"long_running\"}",
                            },
                        }
                    ],
                },
                "tool_calls": [
                    ToolCall(
                        id="call_1",
                        name="detach_to_background",
                        arguments={"reason": "long_running"},
                    )
                ],
                "llm_trace": {"model": "fake-model"},
            }
        raise AssertionError("second LLM call must not happen after detach")

    async def _fake_execute_tool_call(**kwargs):  # type: ignore[no-untyped-def]
        tool_call = kwargs["tool_call"]
        # The orchestrator binds the detach signal before the tool runs,
        # so the tool's ``current_detach_signal()`` lookup must succeed
        # and flip the signal we passed in.
        result = await tool.execute(
            tool_call.arguments,
            ToolExecutionContext(agent_id="chat:test"),
        )
        return ToolCallResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=result.success,
            data=result.data,
            error=result.error,
            error_code=result.error_code,
            execution_time=0.0,
        )

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _fake_call_llm_with_tools)
    monkeypatch.setattr(orchestrator, "_execute_tool_call", _fake_execute_tool_call)

    outcome = await orchestrator.execute_with_tools(
        turn=UserTurnInput(text="do a long task", attachments=[], user_id=None, session_id=None),
        system_prompt="sys",
        selected_tools=["detach_to_background"],
        user_id="u",
        max_iterations=5,
        detach_signal=detach,
    )

    assert outcome.status == "detached"
    assert outcome.detached is True
    assert outcome.snapshot is not None
    assert outcome.snapshot.reason == "long_running"
    # Tool must have observed the bound signal, not raised detach_not_supported.
    tool_msgs = [
        msg for msg in outcome.snapshot.messages if msg.get("role") == "tool"
    ]
    assert tool_msgs, "orchestrator should have recorded the tool result"
    assert "detach_requested" in tool_msgs[0].get("content", "")
