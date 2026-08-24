"""End-to-end integration coverage for the background-task subsystem.

Runs a real :class:`BackgroundTaskManager` with the production
``broadcast_background_task_state_changed`` listener registered and asserts
that a task enqueued through the manager reaches ``succeeded``, appends the
correct transitions + terminal events, and mirrors each state change onto
the runtime-trace notification channel that the Rust gateway relays to the
Tasks UI.
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
    broadcast_background_task_state_changed,
)
from magi.agent.background import notifications as notifications_module
from magi.agent.background.executor import BackgroundTaskRunResult
from magi.agent.background.manager import BackgroundTaskManager
from magi.agent.cancel import CancelToken


class _RecordingTraceStore:
    """Minimal stand-in for the runtime-trace notification store."""

    def __init__(self) -> None:
        self.records = []

    async def append_notification(self, record) -> None:
        self.records.append(record)


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

    # Stand-in runtime-trace store wired into the background-task broadcaster.
    trace_store = _RecordingTraceStore()
    monkeypatch.setattr(
        notifications_module, "resolve_runtime_trace_store", lambda: trace_store
    )

    # Stub run_fn: succeeds with a summary + orchestration id.
    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult(
            summary="Proposal draft ready.",
            result_payload={"word_count": 512},
        )

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=2)

    # Register the production terminal-state listener.
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
    assert persisted.result_payload == {"word_count": 512}

    events = await store.list_events(task.task_id)
    transitions = [event.to_status for event in events]
    assert transitions == [
        BackgroundTaskStatus.PENDING,
        BackgroundTaskStatus.RUNNING,
        BackgroundTaskStatus.SUCCEEDED,
    ]

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


@pytest.mark.asyncio
async def test_background_task_failure_broadcasts(
    runtime_paths_with_schema, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)
    )
    trace_store = _RecordingTraceStore()
    monkeypatch.setattr(
        notifications_module, "resolve_runtime_trace_store", lambda: trace_store
    )

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        raise RuntimeError("network timeout")

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    manager.add_listener(broadcast_background_task_state_changed)

    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())

        async def _failed() -> bool:
            persisted = await store.get_task(task.task_id)
            return (
                persisted is not None
                and persisted.status is BackgroundTaskStatus.FAILED
                and len(trace_store.records) == 1
            )

        await _wait_until(_failed)
    finally:
        await manager.stop()

    persisted = await store.get_task(task.task_id)
    assert persisted is not None
    assert persisted.status is BackgroundTaskStatus.FAILED
    assert persisted.error and "network timeout" in persisted.error

    assert len(trace_store.records) == 1
    payload = json.loads(trace_store.records[0].payload_json)
    assert payload["status"] == "failed"
    assert "network timeout" in (payload["error"] or "")
