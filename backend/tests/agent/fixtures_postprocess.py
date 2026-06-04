"""Fixtures for postprocess lifecycle-event tests."""
from __future__ import annotations

from typing import Any

from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext
from magi.agent.task_agents.common.contracts import (
    ExecutionMode,
    ExecutionResult,
    FunctionCallingExecutionResult,
    IncomingFactKind,
    UserMessagePayload,
)
from magi.agent.runtime.contracts import FactRecord
from magi.agent.run_control import null_run_control


def build_minimal_chat_context(
    *, session_id: str, session_run_id: str | None = None
) -> ChatRuntimeContext:
    """Build a minimal ChatRuntimeContext sufficient for postprocess.handle."""
    payload = UserMessagePayload(
        user_id="user_1",
        session_id=session_id,
        content="hello",
    )
    latest_fact = FactRecord(
        agent_id="test-agent",
        event_type="UserMessage",
        payload=payload.to_dict(),
        correlation_id="corr_1",
    )
    return ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[],
        batch_facts=[latest_fact],
        agent_id="test-agent",
        agent_type="chat",
        runtime_key="chat:test",
        user_id="user_1",
        session_id=session_id,
        history_key=f"history:{session_id}",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=payload,
        session_run_id=session_run_id,
        session_run_revision=0,
        control=null_run_control(),
    )


def build_execution_result_skip_emit_retracted() -> ExecutionResult:
    """Mirror OrchestrationLaunchHandler retract result."""
    return ExecutionResult(
        mode=ExecutionMode.ORCHESTRATION_LAUNCH,
        response_text="",
        skip_emit=True,
        llm_trace={"retracted": True},
    )


def build_execution_result_direct_retract() -> ExecutionResult:
    """Mirror DirectLLMHandler retract result."""
    return ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="",
        llm_trace={"abort_reason": "retract:user_retract"},
    )


def build_execution_result_fc_retracted() -> FunctionCallingExecutionResult:
    """Mirror FunctionCallingHandler retracted result."""
    return FunctionCallingExecutionResult(
        mode=ExecutionMode.FUNCTION_CALLING,
        response_text="",
        execution_outcome={
            "status": "retracted",
            "content": "",
            "iterations": 1,
            "snapshot": {"messages": [], "iterations": 1, "reason": "user_retract", "note": ""},
        },
    )


def build_execution_result_fc_suspended() -> FunctionCallingExecutionResult:
    return FunctionCallingExecutionResult(
        mode=ExecutionMode.FUNCTION_CALLING,
        response_text="",
        execution_outcome={
            "status": "suspended",
            "content": "",
            "iterations": 1,
            "snapshot": {"messages": [], "iterations": 1, "reason": "window_closed", "note": ""},
        },
    )


class _CapturingEventEmitter:
    """Fake event emitter that records all emit_runtime_event calls."""

    def __init__(self, captured: list[dict[str, Any]]) -> None:
        self._captured = captured

    async def emit_runtime_event(
        self,
        *,
        event_type: str,
        payload: Any = None,
        correlation_id: str | None = None,
        success: bool = True,
    ) -> None:
        self._captured.append(
            {"event_type": event_type, "payload": payload, "correlation_id": correlation_id}
        )

    async def emit_chat_response_event(self, **kwargs: Any) -> None:
        # Not under test here — silently ignore.
        pass


class _FakeToolStateView:
    """Minimal stand-in for ChatToolStateView; postprocess_service aliases
    ``context_assembler.tool_state_view`` onto ``_tool_state_view``."""

    def record(self, history_key: str, record: dict[str, Any]) -> None:
        pass


class _FakeContextAssembler:
    tool_state_view = _FakeToolStateView()

    def history_key(self, user_id: str, session_id: str) -> str:
        return f"history:{session_id}"

    def require_session_id(self, user_id: str, session_id: Any) -> str:
        return str(session_id or "")

    def append_user_message(self, history_key: str, user_message: str) -> None:
        pass

    def append_assistant_message(self, history_key: str, response_text: str) -> None:
        pass


def build_postprocess_with_capture() -> tuple[Any, list[dict[str, Any]]]:
    """Construct a minimal ChatPostProcessService whose event emitter
    captures events into a list. The history service / chat store / event
    bus dependencies are mocked since they're not under test here.

    Returns (service, captured_events). Each captured event is a dict
    {'event_type': str, 'payload': ...}.
    """
    from magi.chat.task_agent.postprocess_service import ChatPostProcessService

    captured: list[dict[str, Any]] = []
    emitter = _CapturingEventEmitter(captured)

    service = ChatPostProcessService(
        agent_id="chat:test-agent",
        context_assembler=_FakeContextAssembler(),  # type: ignore[arg-type]
        get_event_emitter=lambda: emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
    )

    return service, captured
