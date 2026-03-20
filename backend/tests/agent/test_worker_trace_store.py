from __future__ import annotations

import time
from pathlib import Path

import pytest

from magi.runtime_trace.store import RuntimeTraceStore
from magi.tools.builtin.agent_tool import AgentTool, WorkerRunState


@pytest.fixture
async def runtime_trace_store(tmp_path: Path):
    store = RuntimeTraceStore(db_path=str(tmp_path / "runtime_trace.db"))
    await store.initialize()
    try:
        yield store
    finally:
        await store.shutdown()


def _run_state() -> WorkerRunState:
    now = time.time()
    return WorkerRunState(
        worker_id="worker-1",
        subagent_type="Explore",
        description="scan auth flow",
        prompt="Locate token generation points",
        orchestration_id="orch-1",
        subtask_id="subtask-1",
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
) -> None:
    manager = AgentTool()._manager
    manager.configure(llm_adapter=object(), runtime_trace_store=runtime_trace_store)
    run_state = _run_state()

    await manager._emit_worker_dispatch_trace(run_state)
    await manager._emit_worker_attempt_started_trace(run_state)
    await manager._emit_worker_started_trace(run_state)

    dispatch_span = await runtime_trace_store.get_span("turn-1:worker_dispatch:subtask-1")
    attempt_span = await runtime_trace_store.get_span("turn-1:worker_attempt:subtask-1:1")
    worker_span = await runtime_trace_store.get_span("turn-1:worker:subtask-1:1")

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
) -> None:
    manager = AgentTool()._manager
    manager.configure(llm_adapter=object(), runtime_trace_store=runtime_trace_store)
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

    llm_span = await runtime_trace_store.get_span("turn-1:worker_llm:subtask-1:1:final_response:1")
    llm_call = await runtime_trace_store.get_llm_call("turn-1:worker_llm:subtask-1:1:final_response:1")
    tool_span = await runtime_trace_store.get_span("turn-1:worker_tool:subtask-1:1:call-1")
    tool_call = await runtime_trace_store.get_tool_call("turn-1:worker_tool:subtask-1:1:call-1")

    assert llm_span is not None
    assert llm_span.node_type == "llm_call"
    assert llm_call is not None
    assert llm_call.model == "gpt-test"
    assert llm_call.output_tokens == 12
    assert tool_span is not None
    assert tool_span.node_type == "tool_call"
    assert tool_call is not None
    assert tool_call.tool_name == "glob"
    assert tool_call.success is True
