"""Behavioral contracts for host capability adapters."""

from types import SimpleNamespace
from unittest.mock import AsyncMock,call
import pytest

@pytest.fixture
def capabilities():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities,reset_tool_capabilities
    reset_tool_capabilities()
    try:
        yield build_tool_capabilities()
    finally:
        reset_tool_capabilities()

@pytest.mark.asyncio
async def test_delegation_ports_forward_event_state_and_artifact_scope(
    capabilities, monkeypatch, tmp_path
):
    from magi.transport import code_agent_events
    from magi.chat import code_delegation_artifacts

    event = AsyncMock()
    state = AsyncMock()
    register = AsyncMock()
    monkeypatch.setattr(code_agent_events, "broadcast_delegation_event", event)
    monkeypatch.setattr(code_agent_events, "broadcast_delegation_state", state)
    monkeypatch.setattr(
        code_delegation_artifacts,
        "ChatCodeDelegationArtifactRegistry",
        lambda: SimpleNamespace(register=register),
    )
    scope = {
        "user_id": "user-1",
        "session_id": "session-2",
        "turn_id": "turn-3",
        "delegation_id": "delegation-4",
    }
    payload = {"kind": "output", "text": "progress canary"}
    await capabilities.delegation_events.broadcast_event(**scope, event=payload)
    event.assert_awaited_once_with(**scope, event=payload)
    await capabilities.delegation_events.broadcast_state(
        **scope, state="completed", summary={"files": ["result.txt"]}
    )
    await capabilities.delegation_events.broadcast_state(**scope, state="running")
    assert state.await_args_list == [
        call(**scope, state="completed", summary={"files": ["result.txt"]}),
        call(**scope, state="running", summary={}),
    ]
    artifact_scope = {k: v for k, v in scope.items() if k != "user_id"}
    await capabilities.delegation_artifacts.register(**artifact_scope, workspace_path=str(tmp_path))
    register.assert_awaited_once_with(**artifact_scope, workspace_path=str(tmp_path))


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [False, True])
async def test_background_port_forwards_task_reason_and_outcome(capabilities, monkeypatch, result):
    from magi.agent.background import provider

    manager = SimpleNamespace(
        suspend_waiting_user=AsyncMock(return_value=result),
        resume_from_wait=AsyncMock(return_value=result),
    )
    monkeypatch.setattr(provider, "resolve_background_task_manager", lambda: manager)
    assert (
        await capabilities.background.suspend_waiting_user("task-canary", reason="approval_pending")
        is result
    )
    assert await capabilities.background.resume_from_wait("task-canary") is result
    manager.suspend_waiting_user.assert_awaited_once_with("task-canary", reason="approval_pending")
    manager.resume_from_wait.assert_awaited_once_with("task-canary")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answered,answer,resolution,timed_out",
    [(True, "choice-2", "answered", False), (False, None, "timeout", True)],
)
async def test_interaction_port_preserves_full_request_and_outcome(
    capabilities, monkeypatch, answered, answer, resolution, timed_out
):
    from magi.control.ask_service import ControlAskService, ControlAskRequest, ControlAskOutcome

    ask = AsyncMock(
        return_value=ControlAskOutcome(
            answered=answered, answer=answer, resolution=resolution, timed_out=timed_out
        )
    )
    monkeypatch.setattr(ControlAskService, "from_runtime", lambda: SimpleNamespace(ask=ask))
    request = {
        "session_id": "session-1",
        "user_id": "user-2",
        "turn_id": "turn-3",
        "question": "Which destination?",
        "options": ["choice-1", "choice-2"],
        "allow_free_text": False,
        "timeout_seconds": 12.5,
        "background": True,
        "background_task_id": "background-4",
        "background_port": capabilities.background,
        "cancellation": object(),
    }
    result = await capabilities.interaction.ask(**request)
    ask.assert_awaited_once_with(ControlAskRequest(**request))
    assert (result.answered, result.answer, result.resolution, result.timed_out) == (
        answered,
        answer,
        resolution,
        timed_out,
    )
