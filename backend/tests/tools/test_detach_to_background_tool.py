"""Tests for the ``detach_to_background`` builtin tool."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import pytest
from agent.agent_run_helpers import run_agent

from magi.agent.execution.function_calling import (
    FunctionCallingOrchestrator,
    ToolCall,
    ToolCallResult,
)
from magi.control.run_control import (
    DetachSignal,
    bind_detach_signal,
    current_detach_signal,
    null_run_control,
)
from magi.tools.builtin.detach_to_background_tool import DetachToBackgroundTool
from magi.tools.schema import ToolExecutionContext
from magi_plugin_sdk.capabilities import DetachPort, ToolCapabilities
from magi.agent.turn_input import UserTurnInput


# ---------------------------------------------------------------------------
# Fake DetachPort implementations
# ---------------------------------------------------------------------------

class _UnavailableDetachPort:
    """Simulates no active detach signal (is_available() returns False)."""

    def is_available(self) -> bool:
        return False

    def is_requested(self) -> bool:
        return False

    def request(self, *, reason: str, requested_by: str = "llm", note: str = "") -> None:
        raise AssertionError("request() must not be called when unavailable")


class _FakeDetachPort:
    """Simulates a live DetachSignal with controllable state."""

    def __init__(self, *, already_requested: bool = False) -> None:
        self._available = True
        self._requested = already_requested
        self.recorded_reason: Optional[str] = None
        self.recorded_by: Optional[str] = None
        self.recorded_note: Optional[str] = None

    def is_available(self) -> bool:
        return self._available

    def is_requested(self) -> bool:
        return self._requested

    def request(self, *, reason: str, requested_by: str = "llm", note: str = "") -> None:
        self._requested = True
        self.recorded_reason = reason
        self.recorded_by = requested_by
        self.recorded_note = note


def _ctx_no_caps() -> ToolExecutionContext:
    """Context with no capabilities at all (old-style call path)."""
    return ToolExecutionContext(agent_id="test-agent")


def _ctx_with(port) -> ToolExecutionContext:
    """Context with a DetachPort wired into capabilities."""
    caps = ToolCapabilities(detach=port)
    return ToolExecutionContext(agent_id="test-agent", capabilities=caps)


def _run_control_with_detach(detach_signal: DetachSignal):
    control = null_run_control()
    control.detach_signal = detach_signal
    return control


# ---------------------------------------------------------------------------
# Unit tests — no-signal branch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detach_tool_fails_without_capabilities() -> None:
    """No capabilities at all → detach_not_supported."""
    tool = DetachToBackgroundTool()

    result = await tool.execute({"reason": "long_running"}, _ctx_no_caps())

    assert result.success is False
    assert result.error_code == "detach_not_supported"


@pytest.mark.asyncio
async def test_detach_tool_fails_when_not_available() -> None:
    """DetachPort present but is_available() is False → detach_not_supported."""
    tool = DetachToBackgroundTool()

    result = await tool.execute({"reason": "long_running"}, _ctx_with(_UnavailableDetachPort()))

    assert result.success is False
    assert result.error_code == "detach_not_supported"


# ---------------------------------------------------------------------------
# Unit tests — newly-requested branch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detach_tool_flips_the_port() -> None:
    """First call records the request and returns already_requested=False."""
    tool = DetachToBackgroundTool()
    port = _FakeDetachPort()

    result = await tool.execute(
        {"reason": "deep_research", "note": "scanning 400 commits"},
        _ctx_with(port),
    )

    assert result.success is True
    assert result.data["status"] == "detach_requested"
    assert result.data["reason"] == "deep_research"
    assert result.data["note"] == "scanning 400 commits"
    assert result.data["already_requested"] is False
    assert port.is_requested() is True
    assert port.recorded_reason == "deep_research"
    assert port.recorded_by == "llm"
    assert port.recorded_note == "scanning 400 commits"


# ---------------------------------------------------------------------------
# Unit tests — already-requested (idempotent) branch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detach_tool_is_idempotent_for_second_call() -> None:
    """Second call sees already_requested=True and does not re-request."""
    tool = DetachToBackgroundTool()
    port = _FakeDetachPort()

    first = await tool.execute({"reason": "first"}, _ctx_with(port))
    # Simulate second call with an already-requested port
    port2 = _FakeDetachPort(already_requested=True)
    second = await tool.execute({"reason": "second"}, _ctx_with(port2))

    assert first.success is True and first.data["already_requested"] is False
    assert second.success is True and second.data["already_requested"] is True
    # The second call must NOT call request() again (port2 recorded nothing)
    assert port2.recorded_reason is None


# ---------------------------------------------------------------------------
# ContextVar smoke-tests (still valid: bind_detach_signal still works)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Integration: orchestrator binds the signal so the tool works end-to-end.
# The orchestrator creates a ToolExecutionContext with capabilities wired,
# so we patch _execute_tool_call to pass the right context.
# ---------------------------------------------------------------------------


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
        # Build a context with the HostDetachPort backed by the live signal.
        # We use a thin _FakeDetachPort that reads the signal via bind_detach_signal.
        from magi.control.run_control import current_detach_signal as _cds
        from magi_plugin_sdk.capabilities import ToolCapabilities

        class _SignalBridgePort:
            def is_available(self):
                return _cds() is not None

            def is_requested(self):
                s = _cds()
                return bool(s and s.is_requested())

            def request(self, *, reason, requested_by="llm", note=""):
                from magi.control.run_control import DetachRequested
                s = _cds()
                if s is not None:
                    s.request(DetachRequested(reason=reason, requested_by=requested_by, note=note))

        ctx = ToolExecutionContext(
            agent_id="chat:test",
            capabilities=ToolCapabilities(detach=_SignalBridgePort()),
        )
        result = await tool.execute(tool_call.arguments, ctx)
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

    outcome = await run_agent(orchestrator,
        turn=UserTurnInput(text="do a long task", attachments=[], user_id=None, session_id=None),
        system_prompt="sys",
        selected_tools=["detach_to_background"],
        user_id="u",
        max_iterations=5,
        control=_run_control_with_detach(detach),
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
