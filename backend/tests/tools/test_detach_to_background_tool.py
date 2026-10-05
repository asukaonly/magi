"""Tests for the ``detach_to_background`` builtin tool."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import pytest
from agent.agent_run_helpers import run_agent

from magi.agent.execution.function_calling import (
    FunctionCallingOrchestrator,
    ToolCall,
)
from magi.control.run_control import (
    DetachSignal,
    bind_detach_signal,
    current_detach_signal,
    null_run_control,
)
from magi.tools.builtin.detach_to_background_tool import DetachToBackgroundTool
from magi.tools.schema import ToolExecutionContext
from magi.core.tool_capabilities import ToolCapabilities
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
@pytest.mark.parametrize(
    "capabilities", [None, ToolCapabilities(), ToolCapabilities(detach=_UnavailableDetachPort())]
)
async def test_unavailable_detach_capability_never_requests_a_signal(capabilities):
    result = await DetachToBackgroundTool().execute(
        {"reason": "long_running"},
        ToolExecutionContext(agent_id="test-agent", capabilities=capabilities),
    )
    assert not result.success
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

    repeated = await tool.execute(
        {"reason": "second", "note": "must not overwrite"}, _ctx_with(port)
    )
    assert repeated.success and repeated.data["already_requested"] is True
    assert port.recorded_reason == "deep_research"
    assert port.recorded_note == "scanning 400 commits"


# ---------------------------------------------------------------------------
# Unit tests — already-requested (idempotent) branch
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ContextVar smoke-tests (still valid: bind_detach_signal still works)
# ---------------------------------------------------------------------------

def test_bind_detach_signal_restores_on_exit() -> None:
    outer = DetachSignal()
    inner = DetachSignal()

    with bind_detach_signal(outer):
        assert current_detach_signal() is outer
        with bind_detach_signal(None):
            assert current_detach_signal() is outer
        with bind_detach_signal(inner):
            assert current_detach_signal() is inner
        assert current_detach_signal() is outer
    assert current_detach_signal() is None


# ---------------------------------------------------------------------------
# Integration: orchestrator binds the signal so the tool works end-to-end.
# The production executor builds the context using the host capability provider.
# ---------------------------------------------------------------------------


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
    from magi.tools.registry import ToolRegistry
    from magi.tools import capabilities
    from magi.bootstrap.tool_capabilities import build_tool_capabilities

    registry = ToolRegistry()
    registry.register(DetachToBackgroundTool)
    monkeypatch.setattr(capabilities, "_provider", build_tool_capabilities)
    orchestrator = FunctionCallingOrchestrator(
        tool_registry=registry,
        llm_adapter=SimpleNamespace(model_name="fake-model", provider_name="fake-provider"),
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
                                "arguments": '{"reason": "long_running"}',
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

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _fake_call_llm_with_tools)

    outcome = await run_agent(
        orchestrator,
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
    tool_msgs = [msg for msg in outcome.snapshot.messages if msg.get("role") == "tool"]
    assert tool_msgs, "orchestrator should have recorded the tool result"
    assert "detach_requested" in tool_msgs[0].get("content", "")

    assert iteration_counter["value"] == 1
    assert current_detach_signal() is None
