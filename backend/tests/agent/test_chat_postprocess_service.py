from __future__ import annotations

import json
import pytest

from magi.awareness.contracts import ActionEmissionRecord
from magi.agent.task_agents.chat.contracts import ChatRuntimeContext
from magi.agent.task_agents.chat.postprocess_service import ChatPostProcessService
from magi.agent.task_agents.common import ExecutionMode, ExecutionResult, IncomingFactKind, UserMessagePayload
from magi.agent.runtime.contracts import FactRecord
from magi.events.events import EventTypes
from magi.runtime_trace.store import RuntimeTraceStore


class _FakeHistoryService:
    def __init__(self) -> None:
        self.history: list[dict] = []

    def require_session_id(self, user_id: str, session_id: str | None = None) -> str:
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
        self.action_events: list[tuple[ActionEmissionRecord, bool, str | None]] = []
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

    async def emit_action_event(self, record: ActionEmissionRecord, success: bool, error: str | None = None) -> None:
        self.action_events.append((record, success, error))

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


class _FakeIntentDecision:
    def __init__(self) -> None:
        self.intent = "chat"
        self.execution_mode = ExecutionMode.DIRECT_LLM
        self.tools: list[str] = []
        self.reasoning = "direct response"
        self.orchestration_plan = None
        self.llm_trace = {
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "input_tokens": 48,
            "output_tokens": 12,
            "total_tokens": 60,
            "reasoning_tokens": 0,
            "thinking_enabled": False,
            "duration_ms": 310,
        }


class _FakeL1Store:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self._events = events

    async def query_events(self, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return list(self._events)


class _FakeUnifiedMemory:
    def __init__(self, events: list[dict[str, object]] | None = None) -> None:
        self.l1 = _FakeL1Store(events or [])
        self.task_packets = []

    async def persist_task_outcome_reflection(self, packet):  # type: ignore[no-untyped-def]
        self.task_packets.append(packet)
        return {"summary_id": "summary-1", "summary_category": "task_reflection"}


@pytest.fixture
async def runtime_trace_store(tmp_path):
    store = RuntimeTraceStore(db_path=str(tmp_path / "runtime_trace.db"))
    await store.initialize()
    try:
        yield store
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_record_tool_interaction_preserves_trace_identity() -> None:
    action_emitter = _FakeActionEmitter()
    service = ChatPostProcessService(
        agent_id="chat:web_user",
        history_service=_FakeHistoryService(),  # type: ignore[arg-type]
        get_action_emitter=lambda: action_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
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
    record, success, error = action_emitter.action_events[0]
    assert success is True
    assert error is None
    assert record.payload["turn_id"] == "turn-1"
    assert record.payload["orchestration_id"] == "orch-1"
    assert record.payload["tool_call_id"] == "call-1"
    assert record.payload["iteration"] == 3

    assert len(action_emitter.runtime_events) == 1
    runtime_payload = action_emitter.runtime_events[0]["payload"]
    assert runtime_payload["turn_id"] == "turn-1"
    assert runtime_payload["iteration"] == 3


@pytest.mark.asyncio
async def test_record_intent_resolution_stops_emitting_runtime_trace_events(
    runtime_trace_store: RuntimeTraceStore,
) -> None:
    action_emitter = _FakeActionEmitter()
    service = ChatPostProcessService(
        agent_id="chat:web_user",
        history_service=_FakeHistoryService(),  # type: ignore[arg-type]
        get_action_emitter=lambda: action_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:web_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "hello",
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
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="web_user",
            session_id="session-1",
            content="hello",
            turn_id="turn-1",
        ),
    )

    await service.record_intent_resolution(context, _FakeIntentDecision())

    assert action_emitter.runtime_events == []


@pytest.mark.asyncio
async def test_record_intent_resolution_persists_turn_and_intent_trace_rows(
    runtime_trace_store: RuntimeTraceStore,
) -> None:
    action_emitter = _FakeActionEmitter()
    service = ChatPostProcessService(
        agent_id="chat:web_user",
        history_service=_FakeHistoryService(),  # type: ignore[arg-type]
        get_action_emitter=lambda: action_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:web_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "hello",
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
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="web_user",
            session_id="session-1",
            content="hello",
            turn_id="turn-1",
        ),
    )

    await service.record_intent_resolution(context, _FakeIntentDecision())

    turn = await runtime_trace_store.get_turn("turn-1")
    intent_span = await runtime_trace_store.get_span("turn-1:intent_resolution")
    intent_resolution = await runtime_trace_store.get_intent_resolution("turn-1:intent_resolution")

    assert turn is not None
    assert turn.trace_id == "trace:turn-1"
    assert turn.status == "running"
    assert turn.user_message_preview == "hello"
    assert intent_span is not None
    assert intent_span.parent_span_id == "turn-1:turn"
    assert intent_span.node_type == "intent_resolution"
    assert intent_span.status == "completed"
    assert intent_resolution is not None
    assert intent_resolution.intent == "chat"
    assert intent_resolution.execution_mode == "direct_llm"
    assert json.loads(intent_resolution.selected_tools_json) == []


@pytest.mark.asyncio
async def test_record_tool_loop_fact_stops_persisting_llm_trace_rows(
    runtime_trace_store: RuntimeTraceStore,
) -> None:
    action_emitter = _FakeActionEmitter()
    service = ChatPostProcessService(
        agent_id="chat:web_user",
        history_service=_FakeHistoryService(),  # type: ignore[arg-type]
        get_action_emitter=lambda: action_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        max_fact_memory=10,
    )

    await service.record_tool_loop_fact(
        {
            "stage": "llm_requested_tools",
            "iteration": 2,
            "tool_names": ["web-search", "file_read"],
            "tool_count": 2,
            "user_id": "web_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "execution_agent_id": "chat:web_user",
            "llm_trace": {
                "provider": "openai",
                "model": "gpt-test",
                "input_tokens": 120,
                "output_tokens": 28,
                "total_tokens": 148,
                "thinking_enabled": False,
                "duration_ms": 840,
            },
        }
    )

    llm_span = await runtime_trace_store.get_span("turn-1:llm_call:llm_requested_tools:2")
    llm_call = await runtime_trace_store.get_llm_call("turn-1:llm_call:llm_requested_tools:2")

    assert llm_span is None
    assert llm_call is None


@pytest.mark.asyncio
async def test_handle_does_not_emit_chat_timeline_event(monkeypatch: pytest.MonkeyPatch) -> None:
    action_emitter = _FakeActionEmitter()
    runtime = _FakeRuntime()
    service = ChatPostProcessService(
        agent_id="chat:web_user",
        history_service=_FakeHistoryService(),  # type: ignore[arg-type]
        get_action_emitter=lambda: action_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=runtime.get_sensor_hub,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:web_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "I still like Asuka best.",
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
            content="I still like Asuka best.",
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
    assert runtime.sensor_hub.sensor_events == []
    assert action_emitter.runtime_events == []


@pytest.mark.asyncio
async def test_handle_stops_emitting_runtime_trace_events_when_llm_trace_exists(
    runtime_trace_store: RuntimeTraceStore,
) -> None:
    action_emitter = _FakeActionEmitter()
    service = ChatPostProcessService(
        agent_id="chat:web_user",
        history_service=_FakeHistoryService(),  # type: ignore[arg-type]
        get_action_emitter=lambda: action_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:web_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "hello",
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
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="web_user",
            session_id="session-1",
            content="hello",
            turn_id="turn-1",
        ),
    )
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="final answer",
        correlation_id="corr-1",
        turn_id="turn-1",
        llm_trace={
            "provider": "openai",
            "model": "gpt-test",
            "input_tokens": 64,
            "output_tokens": 18,
            "total_tokens": 82,
            "thinking_enabled": False,
            "duration_ms": 920,
        },
    )

    await service.handle(context, result)

    assert action_emitter.runtime_events == []


@pytest.mark.asyncio
async def test_handle_persists_turn_response_and_llm_trace_rows(
    runtime_trace_store: RuntimeTraceStore,
) -> None:
    action_emitter = _FakeActionEmitter()
    service = ChatPostProcessService(
        agent_id="chat:web_user",
        history_service=_FakeHistoryService(),  # type: ignore[arg-type]
        get_action_emitter=lambda: action_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        runtime_trace_store=runtime_trace_store,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:web_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "hello",
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
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="web_user",
            session_id="session-1",
            content="hello",
            turn_id="turn-1",
        ),
    )
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="final answer",
        correlation_id="corr-1",
        turn_id="turn-1",
        llm_trace={
            "provider": "openai",
            "model": "gpt-test",
            "input_tokens": 64,
            "output_tokens": 18,
            "total_tokens": 82,
            "thinking_enabled": False,
            "duration_ms": 920,
        },
    )

    await service.handle(context, result)

    turn = await runtime_trace_store.get_turn("turn-1")
    llm_span = await runtime_trace_store.get_span("turn-1:llm_call:direct")
    llm_call = await runtime_trace_store.get_llm_call("turn-1:llm_call:direct")
    response_span = await runtime_trace_store.get_span("turn-1:response_emit")
    root_span = await runtime_trace_store.get_span("turn-1:turn")

    assert turn is not None
    assert turn.status == "completed"
    assert turn.response_preview == "final answer"
    assert llm_span is not None
    assert llm_span.node_type == "llm_call"
    assert llm_call is not None
    assert llm_call.provider == "openai"
    assert llm_call.model == "gpt-test"
    assert llm_call.input_tokens == 64
    assert llm_call.output_tokens == 18
    assert response_span is not None
    assert response_span.node_type == "response_emit"
    assert root_span is not None
    assert root_span.status == "completed"


@pytest.mark.asyncio
async def test_handle_records_task_reflection_for_explore_completion() -> None:
    action_emitter = _FakeActionEmitter()
    unified_memory = _FakeUnifiedMemory(
        events=[
            {"event_id": "evt-1"},
            {"event_id": "evt-2"},
        ]
    )
    service = ChatPostProcessService(
        agent_id="chat:web_user",
        history_service=_FakeHistoryService(),  # type: ignore[arg-type]
        get_action_emitter=lambda: action_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        unified_memory=unified_memory,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:web_user",
        event_type="EXPLORE_TASK_COMPLETED",
        payload={
            "user_id": "web_user",
            "session_id": "session-1",
            "root_user_message": "Analyze the repository architecture",
            "markdown_dossier": "# Request\nAnalyze the repository architecture",
            "orchestration_id": "orch-1",
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
        latest_user_message="Analyze the repository architecture",
        incoming_fact_kind=IncomingFactKind.EXPLORE_TASK_COMPLETED,
        latest_payload=UserMessagePayload(
            user_id="web_user",
            session_id="session-1",
            content="Analyze the repository architecture",
            turn_id="turn-1",
        ),
    )
    result = ExecutionResult(
        mode=ExecutionMode.EXPLORE_TASK_RENDER,
        response_text="Here is the final architecture analysis.",
        root_user_message="Analyze the repository architecture",
        correlation_id="corr-1",
        orchestration_id="orch-1",
        turn_id="turn-1",
    )

    outcome = await service.handle(context, result)

    assert outcome.emitted is True
    assert outcome.memory_updated is True
    assert len(unified_memory.task_packets) == 1
    packet = unified_memory.task_packets[0]
    assert packet.task_id == "orch-1"
    assert packet.task_kind == "user_goal_task"
    assert packet.user_goal == "Analyze the repository architecture"
    assert packet.result_summary == "Here is the final architecture analysis."
    assert packet.evidence_event_ids == ["evt-1", "evt-2"]


@pytest.mark.asyncio
async def test_handle_does_not_record_task_reflection_for_plain_chat_reply() -> None:
    action_emitter = _FakeActionEmitter()
    unified_memory = _FakeUnifiedMemory(events=[{"event_id": "evt-1"}])
    service = ChatPostProcessService(
        agent_id="chat:web_user",
        history_service=_FakeHistoryService(),  # type: ignore[arg-type]
        get_action_emitter=lambda: action_emitter,
        get_task_agent_manager=lambda: None,
        get_sensor_hub=lambda: None,
        unified_memory=unified_memory,
        max_fact_memory=10,
    )
    latest_fact = FactRecord(
        agent_id="chat:web_user",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "Hello there",
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
        latest_user_message="Hello there",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="web_user",
            session_id="session-1",
            content="Hello there",
            turn_id="turn-1",
        ),
    )
    result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="Hi!",
        correlation_id="corr-1",
        turn_id="turn-1",
    )

    await service.handle(context, result)

    assert unified_memory.task_packets == []
