"""End-to-end integration coverage for the background-task subsystem.

Runs a real :class:`BackgroundTaskManager` with both production listeners
registered (``broadcast_background_task_state_changed`` + the completion
handshake) and asserts that a task enqueued through the manager reaches
``succeeded``, appends the correct transitions + terminal events, surfaces
a chat-visible completion via the post-process service, and mirrors each
state change onto the runtime-trace notification channel that the Rust
gateway relays to the Tasks UI.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from magi.agent.background import (
    BackgroundTask,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskStore,
    BackgroundTaskTriggerSource,
)
from magi.agent.background.executor import BackgroundTaskRunResult
from magi.agent.background.manager import BackgroundTaskManager
from magi.agent.cancel import CancelToken
from magi.bootstrap.background_tasks import build_completion_handshake_listener
from magi.transport import chat_events as chat_events_module
from magi.transport.chat_events import broadcast_background_task_state_changed


class _RecordingTraceStore:
    """Minimal stand-in for the runtime-trace notification store."""

    def __init__(self) -> None:
        self.records = []

    async def append_notification(self, record) -> None:
        self.records.append(record)


class _CapturingPostProcess:
    def __init__(self) -> None:
        self.calls: list[BackgroundTask] = []

    async def deliver_background_task_completion(self, task: BackgroundTask) -> None:
        self.calls.append(task)


class _FakeChatAgent:
    def __init__(self, postprocess: _CapturingPostProcess) -> None:
        self.postprocess_service = postprocess


class _FakeTaskAgentManager:
    def __init__(self, agent: _FakeChatAgent) -> None:
        self._agent = agent
        self.ensure_calls: list[tuple[object, str]] = []

    async def ensure_agent(self, agent_type, agent_id: str):
        self.ensure_calls.append((agent_type, agent_id))
        return self._agent


def _make_spec() -> BackgroundTaskSpec:
    return BackgroundTaskSpec(
        user_id="alice",
        session_id="session-7",
        origin_turn_id="turn-42",
        title="Draft proposal",
        goal="Draft the proposal and share a summary.",
        selected_tools=["web_search"],
        trigger_source=BackgroundTaskTriggerSource.PLANNER,
    )


async def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if await predicate():
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"condition not met within {timeout}s")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_background_task_end_to_end_pipeline(
    runtime_paths_with_schema, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Persistent store for the manager.
    store = BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)
    )

    # Stand-in runtime-trace store wired into the transport broadcaster.
    trace_store = _RecordingTraceStore()
    monkeypatch.setattr(
        chat_events_module, "resolve_runtime_trace_store", lambda: trace_store
    )

    # Fake chat post-process pipeline so we can assert the handshake listener
    # routed the terminal task through ``deliver_background_task_completion``.
    postprocess = _CapturingPostProcess()
    task_agent_manager = _FakeTaskAgentManager(_FakeChatAgent(postprocess))

    # Stub run_fn: succeeds with a summary + orchestration id.
    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult(
            summary="Proposal draft ready.",
            result_payload={"word_count": 512},
            orchestration_id="orch-e2e",
        )

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=2)

    # Register the two production listeners in the same order as lifecycle.py.
    handshake_listener = build_completion_handshake_listener(
        get_task_agent_manager=lambda: task_agent_manager,
    )
    manager.add_listener(handshake_listener)
    manager.add_listener(broadcast_background_task_state_changed)

    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())

        async def _reached_terminal() -> bool:
            persisted = await store.get_task(task.task_id)
            events = await store.list_events(task.task_id)
            terminal_statuses = {
                BackgroundTaskStatus.SUCCEEDED,
                BackgroundTaskStatus.FAILED,
                BackgroundTaskStatus.CANCELLED,
            }
            return (
                persisted is not None
                and persisted.status in terminal_statuses
                and BackgroundTaskStatus.SUCCEEDED in {event.to_status for event in events}
                and len(postprocess.calls) == 1
                and len(trace_store.records) == 1
            )

        await _wait_until(_reached_terminal)
    finally:
        await manager.stop()

    # --- Store assertions ------------------------------------------------
    persisted = await store.get_task(task.task_id)
    assert persisted is not None
    assert persisted.status is BackgroundTaskStatus.SUCCEEDED
    assert persisted.summary == "Proposal draft ready."
    assert persisted.orchestration_id == "orch-e2e"
    assert persisted.result_payload == {"word_count": 512}

    events = await store.list_events(task.task_id)
    transitions = [event.to_status for event in events]
    assert transitions == [
        BackgroundTaskStatus.PENDING,
        BackgroundTaskStatus.RUNNING,
        BackgroundTaskStatus.SUCCEEDED,
    ]

    # --- Handshake listener assertions ----------------------------------
    assert len(postprocess.calls) == 1
    delivered = postprocess.calls[0]
    assert delivered.task_id == task.task_id
    assert delivered.status is BackgroundTaskStatus.SUCCEEDED
    # The listener must resolve the chat agent through the task-agent manager.
    assert len(task_agent_manager.ensure_calls) == 1
    _, resolved_agent_id = task_agent_manager.ensure_calls[0]
    assert resolved_agent_id == "default"

    # --- Broadcaster assertions -----------------------------------------
    # Only the terminal transition is broadcast (listeners fire on terminal
    # statuses per TERMINAL_BACKGROUND_TASK_STATUSES).
    assert len(trace_store.records) == 1
    record = trace_store.records[0]
    assert record.channel == "background_task_state_changed"
    assert record.user_id == "alice"
    assert record.session_id == "session-7"
    payload = json.loads(record.payload_json)
    assert payload["task_id"] == task.task_id
    assert payload["status"] == "succeeded"
    assert payload["summary"] == "Proposal draft ready."
    assert payload["orchestration_id"] == "orch-e2e"


@pytest.mark.asyncio
async def test_background_task_failure_broadcasts_and_delivers(
    runtime_paths_with_schema, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)
    )
    trace_store = _RecordingTraceStore()
    monkeypatch.setattr(
        chat_events_module, "resolve_runtime_trace_store", lambda: trace_store
    )
    postprocess = _CapturingPostProcess()
    task_agent_manager = _FakeTaskAgentManager(_FakeChatAgent(postprocess))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        raise RuntimeError("network timeout")

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    manager.add_listener(
        build_completion_handshake_listener(
            get_task_agent_manager=lambda: task_agent_manager,
        )
    )
    manager.add_listener(broadcast_background_task_state_changed)

    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())

        async def _failed() -> bool:
            persisted = await store.get_task(task.task_id)
            return (
                persisted is not None
                and persisted.status is BackgroundTaskStatus.FAILED
                and len(postprocess.calls) == 1
                and len(trace_store.records) == 1
            )

        await _wait_until(_failed)
    finally:
        await manager.stop()

    persisted = await store.get_task(task.task_id)
    assert persisted is not None
    assert persisted.status is BackgroundTaskStatus.FAILED
    assert persisted.error and "network timeout" in persisted.error

    assert len(postprocess.calls) == 1
    assert postprocess.calls[0].status is BackgroundTaskStatus.FAILED

    assert len(trace_store.records) == 1
    payload = json.loads(trace_store.records[0].payload_json)
    assert payload["status"] == "failed"
    assert "network timeout" in (payload["error"] or "")
