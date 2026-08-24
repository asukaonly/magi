from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock

import pytest

from magi.agent.execution.function_calling import ExecutionOutcome
from magi.events.in_memory_backend import InMemoryMessageBusBackend
from magi.llm.streaming_events import LLMStreamEvent, emit_stream_event, stream_scope
from magi.runtime_trace.store import RuntimeTraceStore
from magi.runtime_trace.subscribers.runtime_trace_subscriber import (
    RuntimeTraceSubscriber,
)
from magi.agent.runtime_tools import AgentTool, WorkerRunState
from magi.agent.workers.child_preset import ChildRunPreset


@pytest.fixture
async def runtime_trace_store(runtime_paths_with_schema):
    store = RuntimeTraceStore(db_path=str(runtime_paths_with_schema.runtime_trace_db_path))
    await store.initialize()
    try:
        yield store
    finally:
        await store.shutdown()


@pytest.fixture
async def trace_bus_and_subscriber(runtime_trace_store: RuntimeTraceStore):
    bus = InMemoryMessageBusBackend()
    await bus.start()
    subscriber = RuntimeTraceSubscriber(event_bus=bus, trace_store=runtime_trace_store)
    await subscriber.start()

    async def _flush() -> None:
        # Wait for the bus queue to drain into the subscriber, then drain the
        # subscriber's in-flight projection tasks.
        import asyncio as _asyncio

        while True:
            stats = await bus.get_stats()
            if stats["queue_length"] == 0 and stats["active_dispatches"] == 0:
                break
            await _asyncio.sleep(0.01)
        await subscriber.drain()

    try:
        yield bus, subscriber, _flush
    finally:
        await subscriber.stop()
        await bus.stop()


def _run_state() -> WorkerRunState:
    now = time.time()
    return WorkerRunState(
        worker_id="worker-1",
        child_run_id="child-1",
        preset=ChildRunPreset.READ_ONLY,
        description="scan auth flow",
        prompt="Locate token generation points",
        parent_run_id="run-1",
        parent_task_agent_type="chat",
        parent_task_agent_id="chat:u-chat",
        target_task_agent_type="chat",
        target_task_agent_id="u-chat",
        user_id="u-chat",
        session_id="s-chat",
        turn_id="turn-1",
        created_at=now,
        updated_at=now,
        started_at_ms=1710000000000,
        started_monotonic=1.0,
    )


@pytest.mark.asyncio
async def test_worker_trace_store_persists_dispatch_and_worker_spans(
    runtime_trace_store: RuntimeTraceStore,
    trace_bus_and_subscriber,
) -> None:
    bus, subscriber, flush = trace_bus_and_subscriber
    manager = AgentTool()._manager
    manager.configure(
        llm_adapter=object(),
        runtime_trace_store=runtime_trace_store,
        message_bus=bus,
    )
    run_state = _run_state()

    await manager._emit_worker_dispatch_trace(run_state)
    await manager._emit_worker_attempt_started_trace(run_state)
    await manager._emit_worker_started_trace(run_state)
    await flush()

    dispatch_span = await runtime_trace_store.get_span("turn-1:worker_dispatch:child-1")
    attempt_span = await runtime_trace_store.get_span("turn-1:worker_attempt:child-1:1")
    worker_span = await runtime_trace_store.get_span("turn-1:worker:child-1:1")

    assert dispatch_span is not None
    assert dispatch_span.node_type == "worker_dispatch"
    assert dispatch_span.status == "completed"
    assert attempt_span is not None
    assert attempt_span.node_type == "worker_attempt"
    assert attempt_span.status == "running"
    assert worker_span is not None
    assert worker_span.node_type == "worker"
    assert worker_span.status == "running"


@pytest.mark.asyncio
async def test_worker_trace_store_persists_llm_and_tool_rows(
    runtime_trace_store: RuntimeTraceStore,
    trace_bus_and_subscriber,
) -> None:
    bus, subscriber, flush = trace_bus_and_subscriber
    manager = AgentTool()._manager
    manager.configure(
        llm_adapter=object(),
        runtime_trace_store=runtime_trace_store,
        message_bus=bus,
    )
    run_state = _run_state()

    await manager._handle_worker_loop_event(
        run_state,
        {
            "stage": "final_response",
            "iteration": 1,
            "response_preview": "worker finished",
            "llm_trace": {
                "provider": "openai",
                "model": "gpt-test",
                "input_tokens": 30,
                "output_tokens": 12,
                "duration_ms": 510,
            },
            "context_usage": {
                "used_tokens": 30,
                "window_size": 128000,
                "threshold": 96000,
            },
        },
    )
    await manager._handle_tool_result(
        run_state,
        {
            "tool_name": "glob",
            "tool_call_id": "call-1",
            "arguments": {"pattern": "*.py"},
            "success": True,
            "execution_time": 0.01,
            "error": None,
            "error_code": None,
            "data": {"matches": 3},
        },
    )
    await flush()

    llm_span = await runtime_trace_store.get_span("turn-1:worker_llm:child-1:1:final_response:1")
    llm_call = await runtime_trace_store.get_llm_call(
        "turn-1:worker_llm:child-1:1:final_response:1"
    )
    tool_span = await runtime_trace_store.get_span("turn-1:worker_tool:child-1:1:call-1")
    tool_call = await runtime_trace_store.get_tool_call("turn-1:worker_tool:child-1:1:call-1")

    assert llm_span is None
    assert llm_call is None
    # D phase 4: worker_trace no longer publishes llm_call SpanCompleted; the
    # canonical publish now comes from provider_bridge on real LLM calls.
    assert tool_span is not None
    assert tool_span.node_type == "tool_invocation"
    assert tool_call is not None
    assert tool_call.tool_name == "glob"
    assert tool_call.success is True
    notifications = await runtime_trace_store.list_notifications(after_id=0, limit=10)
    context_usage_notification = next(
        (
            item
            for item in notifications
            if item.channel == "worker_context_usage"
        ),
        None,
    )
    assert context_usage_notification is not None
    assert context_usage_notification.session_id == "s-chat"
    assert context_usage_notification.turn_id == "turn-1"
    payload = json.loads(context_usage_notification.payload_json)
    assert payload["used_tokens"] == 30
    assert payload["window_size"] == 128000
    assert payload["threshold"] == 96000


@pytest.mark.asyncio
async def test_worker_run_marks_stream_events_as_worker_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[LLMStreamEvent] = []

    async def sink(event: LLMStreamEvent) -> None:
        captured.append(event)

    class FakeFunctionCallingOrchestrator:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def run(self, run_input) -> ExecutionOutcome:
            _ = run_input
            await emit_stream_event(LLMStreamEvent(kind="text_delta", text="worker json leak"))
            await emit_stream_event(
                LLMStreamEvent(
                    kind="tool_call_start",
                    tool_call_id="call-worker",
                    tool_name="web-search",
                )
            )
            return ExecutionOutcome(
                status="completed",
                content=(
                    '{"result_status":"success","summary":"done",'
                    '"findings":[],"evidence":[],"records":[],"gaps":[],"next_steps":[],'
                    '"failure_reason":null}'
                ),
            )

    manager = AgentTool()._manager
    manager.configure(llm_adapter=object())
    manager._emit_worker_completed_trace = AsyncMock()
    manager._emit_worker_failed_trace = AsyncMock()
    from magi.agent.workers import worker_execution as worker_execution_module

    monkeypatch.setattr(
        worker_execution_module,
        "FunctionCallingOrchestrator",
        FakeFunctionCallingOrchestrator,
    )

    run_state = _run_state()

    async with stream_scope(sink, source="chat"):
        await manager._run_worker(
            run_state=run_state,
            worker_system_prompt="worker prompt",
            selected_tools=[],
            max_iterations=1,
            execution_workspace="/tmp",
        )

    assert run_state.status == "completed"
    assert [event.kind for event in captured] == ["tool_call_start"]
    assert captured[0].source == "worker"
