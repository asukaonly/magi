from __future__ import annotations

import pytest

from magi.agent.task_agents.chat.contracts import ChatRuntimeContext
from magi.agent.task_agents.chat.postprocess_service import ChatPostProcessService
from magi.agent.task_agents.common import ExecutionMode, ExecutionResult, IncomingFactKind, UserMessagePayload
from magi.core.runtime.contracts import FactRecord
from magi.events.events import EventTypes


class _FakeSessionService:
    def __init__(self) -> None:
        self.history: list[dict] = []

    def resolve_session_id(self, user_id: str, session_id: str | None = None) -> str:
        return session_id or "generated-session"

    def history_key(self, user_id: str, session_id: str) -> str:
        return f"{user_id}::{session_id}"

    def append_user_message(self, history_key: str, user_message: str) -> None:
        self.history.append({"history_key": history_key, "role": "user", "content": user_message})

    def append_assistant_message(self, history_key: str, response_text: str) -> None:
        self.history.append({"history_key": history_key, "role": "assistant", "content": response_text})

    def store_tool_interaction(self, history_key: str, record: dict) -> None:
        _ = (history_key, record)


class _FakeActionEmitter:
    def __init__(self) -> None:
        self.action_events: list[tuple[object, bool, str | None]] = []
        self.chat_response_events: list[dict] = []
        self.runtime_events: list[dict] = []

    async def emit_chat_response_event(
        self,
        *,
        user_id: str,
        session_id: str,
        response: str,
        correlation_id: str | None = None,
        turn_id: str | None = None,
        orchestration_id: str | None = None,
        trace_summary: dict | None = None,
        trace_available: bool = False,
    ) -> None:
        self.chat_response_events.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "response": response,
                "correlation_id": correlation_id,
                "turn_id": turn_id,
                "orchestration_id": orchestration_id,
                "trace_summary": trace_summary,
                "trace_available": trace_available,
            }
        )

    async def emit_action_event(self, fact, success: bool, error: str | None = None) -> None:
        self.action_events.append((fact, success, error))

    async def emit_runtime_event(
        self,
        *,
        event_type: str,
        payload: dict[str, object],
        correlation_id: str | None = None,
        success: bool = True,
    ) -> None:
        self.runtime_events.append(
            {
                "event_type": event_type,
                "payload": payload,
                "correlation_id": correlation_id,
                "success": success,
            }
        )


class _FakeSensorHub:
    def __init__(self) -> None:
        self.sensor_events = []

    async def push_sensor_event(self, sensor_event) -> None:
        self.sensor_events.append(sensor_event)


class _FakeRuntime:
    def __init__(self) -> None:
        self.sensor_hub = _FakeSensorHub()

    def get_sensor_hub(self):
        return self.sensor_hub


@pytest.mark.asyncio
async def test_record_tool_interaction_preserves_trace_identity() -> None:
    action_emitter = _FakeActionEmitter()
    service = ChatPostProcessService(
        agent_id="chat:web_user",
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        get_action_emitter=lambda: action_emitter,
        max_fact_memory=10,
    )

    await service.record_tool_interaction(
        {
            "user_id": "web_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "orchestration_id": "orch-1",
            "tool_call_id": "call-1",
            "iteration": 3,
            "tool_name": "web-search",
            "arguments": {"query": "Hangzhou news"},
            "execution_time": 0.25,
            "success": True,
            "error": None,
            "error_code": None,
            "data": {"provider": "duckduckgo"},
            "intent": "news_query",
        }
    )

    assert len(action_emitter.action_events) == 1
    fact, success, error = action_emitter.action_events[0]
    assert success is True
    assert error is None
    assert fact.payload["turn_id"] == "turn-1"
    assert fact.payload["orchestration_id"] == "orch-1"
    assert fact.payload["tool_call_id"] == "call-1"
    assert fact.payload["iteration"] == 3

    assert len(action_emitter.runtime_events) == 1
    runtime_payload = action_emitter.runtime_events[0]["payload"]
    assert runtime_payload["turn_id"] == "turn-1"
    assert runtime_payload["iteration"] == 3


@pytest.mark.asyncio
async def test_handle_emits_targeted_chat_timeline_event(monkeypatch: pytest.MonkeyPatch) -> None:
    action_emitter = _FakeActionEmitter()
    runtime = _FakeRuntime()
    monkeypatch.setattr("magi.core.runtime_bindings.require_agent_runtime", lambda: runtime)
    service = ChatPostProcessService(
        agent_id="chat:web_user",
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        get_action_emitter=lambda: action_emitter,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:web_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "message": "I still like Asuka best.",
            "user_id": "web_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
        },
        agent_type="chat",
        agent_instance_id="web_user",
        timestamp=1710000000.0,
        correlation_id="corr-1",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[latest_fact],
        batch_facts=[latest_fact],
        agent_id="web_user",
        agent_type="chat",
        runtime_key="chat:web_user",
        user_id="web_user",
        session_id="session-1",
        history_key="web_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="I still like Asuka best.",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="web_user",
            session_id="session-1",
            message="I still like Asuka best.",
            turn_id="turn-1",
        ),
    )
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="You bring up Asuka a lot.",
        correlation_id="corr-1",
        turn_id="turn-1",
    )

    outcome = await service.handle(context, result)

    assert outcome.emitted is True
    assert len(action_emitter.chat_response_events) == 1
    assert len(runtime.sensor_hub.sensor_events) == 1
    timeline_event = runtime.sensor_hub.sensor_events[0]
    assert timeline_event.event_type == "TimelineSourceDetected"
    assert timeline_event.payload["target_task_agent_type"] == "timeline"
    assert timeline_event.payload["target_task_agent_id"] == "timeline-main"
    assert timeline_event.payload["source_type"] == "chat"
    assert timeline_event.payload["message"] == "I still like Asuka best."
    assert timeline_event.payload["assistant_message"] == "You bring up Asuka a lot."
    assert timeline_event.payload["turn_id"] == "turn-1"
