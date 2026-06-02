"""Tests for chat-side detach-to-background hand-off wiring."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from magi.agent.background.contracts import BackgroundTaskTriggerSource
from magi.agent.run_control import DetachSignal
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext, IntentDecision
from magi.agent.task_agents.handlers.handlers import FunctionCallingHandler
from magi.agent.task_agents.common import (
    ExecutionMode,
    FunctionCallingExecutionResult,
    FunctionCallingRequest,
    IncomingFactKind,
    OrchestrationPlan,
    ToolSelection,
    UserMessagePayload,
)


def _make_request(*, user_message: str = "long task", turn_id: str = "t-1") -> FunctionCallingRequest:
    payload = UserMessagePayload(
        user_id="u",
        session_id="s",
        content=user_message,
        turn_id=turn_id,
    )
    context = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="chat:u",
        agent_type="chat",
        runtime_key="chat:u",
        user_id="u",
        session_id="s",
        history_key="u::s",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message=user_message,
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=payload,
    )
    return FunctionCallingRequest(
        mode=ExecutionMode.FUNCTION_CALLING,
        context=context,
        intent=IntentDecision(
            intent="chat",
            difficulty="normal",
            execution_mode=ExecutionMode.FUNCTION_CALLING,
            reasoning="",
            memory_route="none",
        ),
        tool_selection=ToolSelection(tools=["detach_to_background"], reasoning=""),
        selected_tools=["detach_to_background"],
        system_prompt="sys",
    )


class _RecordingLaunchService:
    """Stand-in for :class:`BackgroundLaunchService`."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def enqueue_from_request(  # type: ignore[no-untyped-def]
        self,
        request,
        *,
        trigger_source,
        timeout_seconds=1800,
        max_iterations=20,
        initial_messages=None,
    ):
        self.calls.append(
            {
                "trigger_source": trigger_source,
                "initial_messages": initial_messages,
                "turn_id": getattr(request.context.latest_payload, "turn_id", None),
            }
        )
        return FunctionCallingExecutionResult(
            mode=request.mode,
            response_text="Started background task",
            root_user_message=request.context.latest_user_message,
            turn_id=getattr(request.context.latest_payload, "turn_id", None),
            execution_outcome={"status": "ack"},
            orchestration_id="bg_stub",
        )


def _make_handler(launch_service) -> FunctionCallingHandler:
    deps = SimpleNamespace(
        background_launch_service=launch_service,
    )
    return FunctionCallingHandler(deps)


def test_build_detach_signal_returns_none_without_launch_service() -> None:
    handler = _make_handler(launch_service=None)
    assert handler._build_detach_signal() is None


def test_build_detach_signal_returns_signal_when_launch_service_present() -> None:
    handler = _make_handler(launch_service=_RecordingLaunchService())
    signal = handler._build_detach_signal()
    assert isinstance(signal, DetachSignal)
    assert signal.is_requested() is False


@pytest.mark.asyncio
async def test_handoff_detached_outcome_enqueues_with_snapshot_messages() -> None:
    launch_service = _RecordingLaunchService()
    handler = _make_handler(launch_service=launch_service)

    snapshot_messages = [
        {"role": "user", "content": "long task"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "{\"ok\": true}"},
    ]
    detached_result = FunctionCallingExecutionResult(
        mode=ExecutionMode.FUNCTION_CALLING,
        response_text="",
        root_user_message="long task",
        execution_outcome={
            "status": "detached",
            "content": "",
            "failure_reason": None,
            "tool_failures": [],
            "iterations": 1,
            "snapshot": {
                "messages": snapshot_messages,
                "iterations": 1,
                "reason": "long_running",
                "note": "",
            },
        },
        turn_id="t-1",
    )

    request = _make_request()
    ack = await handler._maybe_handoff_detached_outcome(request, detached_result)

    assert ack is not None
    assert ack.response_text == "Started background task"
    assert ack.orchestration_id == "bg_stub"
    assert len(launch_service.calls) == 1
    call = launch_service.calls[0]
    assert call["trigger_source"] is BackgroundTaskTriggerSource.MANUAL
    assert call["initial_messages"] == snapshot_messages
    # Launch service must receive a fresh copy so later mutations of the
    # original result dict cannot retroactively alter the spec.
    assert call["initial_messages"] is not snapshot_messages


@pytest.mark.asyncio
async def test_handoff_noop_when_outcome_is_not_detached() -> None:
    launch_service = _RecordingLaunchService()
    handler = _make_handler(launch_service=launch_service)

    completed_result = FunctionCallingExecutionResult(
        mode=ExecutionMode.FUNCTION_CALLING,
        response_text="done",
        root_user_message="hi",
        execution_outcome={"status": "completed", "content": "done"},
        turn_id="t-1",
    )

    ack = await handler._maybe_handoff_detached_outcome(_make_request(), completed_result)

    assert ack is None
    assert launch_service.calls == []


@pytest.mark.asyncio
async def test_handoff_noop_when_no_launch_service_wired() -> None:
    handler = _make_handler(launch_service=None)
    detached_result = FunctionCallingExecutionResult(
        mode=ExecutionMode.FUNCTION_CALLING,
        response_text="",
        root_user_message="hi",
        execution_outcome={
            "status": "detached",
            "snapshot": {"messages": [], "iterations": 0, "reason": "x", "note": ""},
        },
        turn_id="t-1",
    )

    ack = await handler._maybe_handoff_detached_outcome(_make_request(), detached_result)
    assert ack is None


@pytest.mark.asyncio
async def test_handoff_returns_none_on_launch_failure_so_surface_stays_honest() -> None:
    class _BrokenLaunchService:
        async def enqueue_from_request(self, *args, **kwargs):
            raise RuntimeError("queue offline")

    handler = _make_handler(launch_service=_BrokenLaunchService())
    detached_result = FunctionCallingExecutionResult(
        mode=ExecutionMode.FUNCTION_CALLING,
        response_text="",
        root_user_message="hi",
        execution_outcome={
            "status": "detached",
            "snapshot": {
                "messages": [{"role": "user", "content": "hi"}],
                "iterations": 0,
                "reason": "x",
                "note": "",
            },
        },
        turn_id="t-1",
    )

    ack = await handler._maybe_handoff_detached_outcome(_make_request(), detached_result)
    assert ack is None


def test_build_detached_chat_result_preserves_snapshot_and_messages() -> None:
    handler = _make_handler(launch_service=_RecordingLaunchService())
    signal = DetachSignal()
    from magi.agent.run_control import DetachRequested

    signal.request(DetachRequested(reason="deep_research", note="scanning"))
    step_state = SimpleNamespace(
        messages=[
            {"role": "user", "content": "research energy"},
            {"role": "assistant", "content": "searching..."},
        ],
        iteration=2,
        tool_failures=[],
    )

    result = handler._build_detached_chat_result(
        request=_make_request(user_message="research energy", turn_id="t-7"),
        step_state=step_state,
        detach_signal=signal,
        current_user_message="research energy",
        current_turn_id="t-7",
    )

    assert result.execution_outcome["status"] == "detached"
    snapshot = result.execution_outcome["snapshot"]
    assert snapshot["iterations"] == 2
    assert snapshot["reason"] == "deep_research"
    assert snapshot["note"] == "scanning"
    assert snapshot["messages"] == [
        {"role": "user", "content": "research energy"},
        {"role": "assistant", "content": "searching..."},
    ]
    # Deep copy: mutating the snapshot must not reach step_state.
    snapshot["messages"][0]["content"] = "mutated"
    assert step_state.messages[0]["content"] == "research energy"
