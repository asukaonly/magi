from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Awaitable, Callable

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


def _make_spec(*, origin_turn_id: str = "turn-1") -> BackgroundTaskSpec:
    return BackgroundTaskSpec(
        user_id="u",
        session_id="s",
        origin_turn_id=origin_turn_id,
        title="Demo task",
        goal="do something",
        selected_tools=[],
        trigger_source=BackgroundTaskTriggerSource.PLANNER,
    )


async def _wait_until(
    predicate: Callable[[], bool | Awaitable[bool]],
    *,
    timeout: float = 2.0,
) -> None:
    """Poll ``predicate`` on a tight event-loop cycle until it is truthy."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"condition not met within {timeout}s")
        await asyncio.sleep(0.005)


async def _get_status(
    store: BackgroundTaskStore, task_id: str
) -> BackgroundTaskStatus | None:
    task = await store.get_task(task_id)
    return task.status if task is not None else None


def _status_reaches(
    store: BackgroundTaskStore,
    task_id: str,
    target: BackgroundTaskStatus,
) -> Callable[[], Awaitable[bool]]:
    async def _check() -> bool:
        return (await _get_status(store, task_id)) == target

    return _check


# ----------------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueued_task_runs_to_succeeded(tmp_path: Path) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult(
            summary="done",
            result_payload={"answer": 42},
            orchestration_id="orch-1",
        )

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())
        await _wait_until(_status_reaches(store, task.task_id, BackgroundTaskStatus.SUCCEEDED))
        fetched = await store.get_task(task.task_id)
        assert fetched is not None
        assert fetched.summary == "done"
        assert fetched.result_payload == {"answer": 42}
        assert fetched.orchestration_id == "orch-1"
        assert fetched.started_at is not None
        assert fetched.finished_at is not None

        events = await store.list_events(task.task_id)
        transitions = [e.to_status for e in events]
        assert transitions == [
            BackgroundTaskStatus.PENDING,
            BackgroundTaskStatus.RUNNING,
            BackgroundTaskStatus.SUCCEEDED,
        ]
    finally:
        await manager.stop()


# ----------------------------------------------------------------------
# Concurrency cap
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrency_cap_is_respected(tmp_path: Path) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))
    gate = asyncio.Event()
    active_ids: list[str] = []
    peak = {"value": 0}

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        active_ids.append(task.task_id)
        peak["value"] = max(peak["value"], len(active_ids))
        await gate.wait()
        active_ids.remove(task.task_id)
        return BackgroundTaskRunResult(summary="ok")

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=2)
    await manager.start()
    try:
        tasks = [await manager.enqueue(_make_spec(origin_turn_id=f"t{i}")) for i in range(4)]
        await _wait_until(lambda: len(active_ids) == 2)
        assert manager.active_count() == 2
        gate.set()

        async def _all_succeeded() -> bool:
            rows = await asyncio.gather(*[store.get_task(t.task_id) for t in tasks])
            return all(
                row is not None and row.status == BackgroundTaskStatus.SUCCEEDED
                for row in rows
            )

        await _wait_until(_all_succeeded)
        assert peak["value"] == 2
    finally:
        await manager.stop()


# ----------------------------------------------------------------------
# Cancellation
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_running_task_transitions_to_cancelled(tmp_path: Path) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))
    running = asyncio.Event()

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        running.set()
        # Poll the token like a well-behaved orchestrator would.
        while not await token.is_cancelled():
            await asyncio.sleep(0.01)
        raise asyncio.CancelledError

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())
        await running.wait()

        assert await manager.cancel(task.task_id, reason="user_stop") is True

        await _wait_until(_status_reaches(store, task.task_id, BackgroundTaskStatus.CANCELLED))
        fetched = await store.get_task(task.task_id)
        assert fetched is not None
        assert fetched.cancel_reason == "user_stop"

        events = await store.list_events(task.task_id)
        transitions = [e.to_status for e in events]
        assert BackgroundTaskStatus.CANCELLING in transitions
        assert transitions[-1] == BackgroundTaskStatus.CANCELLED
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_cancel_unknown_task_returns_false(tmp_path: Path) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        assert await manager.cancel("bg_missing") is False
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_cancel_pending_task_skips_dispatch(tmp_path: Path) -> None:
    """Cancelling a queued-but-not-dispatched task must flip it to cancelled
    without ever invoking ``run_fn``."""
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))
    first_running = asyncio.Event()
    release_first = asyncio.Event()
    run_calls: list[str] = []

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        run_calls.append(task.task_id)
        if task.spec.origin_turn_id == "first":
            first_running.set()
            await release_first.wait()
        return BackgroundTaskRunResult()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        first = await manager.enqueue(_make_spec(origin_turn_id="first"))
        second = await manager.enqueue(_make_spec(origin_turn_id="second"))
        await first_running.wait()  # first is now consuming the only slot

        assert await manager.cancel(second.task_id, reason="not_needed") is True
        fetched_second = await store.get_task(second.task_id)
        assert fetched_second is not None
        assert fetched_second.status == BackgroundTaskStatus.CANCELLED
        assert fetched_second.cancel_reason == "not_needed"

        release_first.set()
        await _wait_until(_status_reaches(store, first.task_id, BackgroundTaskStatus.SUCCEEDED))
        assert run_calls == [first.task_id]
    finally:
        await manager.stop()


# ----------------------------------------------------------------------
# Failure paths
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_fn_exception_marks_task_failed(tmp_path: Path) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        raise RuntimeError("boom")

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())
        await _wait_until(_status_reaches(store, task.task_id, BackgroundTaskStatus.FAILED))
        fetched = await store.get_task(task.task_id)
        assert fetched is not None
        assert fetched.error is not None
        assert "RuntimeError" in fetched.error
        assert "boom" in fetched.error
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_run_fn_timeout_marks_task_failed(tmp_path: Path) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        raise asyncio.TimeoutError

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())
        await _wait_until(_status_reaches(store, task.task_id, BackgroundTaskStatus.FAILED))
        fetched = await store.get_task(task.task_id)
        assert fetched is not None
        assert fetched.error == "timeout"
    finally:
        await manager.stop()


# ----------------------------------------------------------------------
# Retry
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_after_failure_reruns_with_incremented_attempt(tmp_path: Path) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))
    attempt_counter = {"value": 0}

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        attempt_counter["value"] += 1
        if attempt_counter["value"] == 1:
            raise RuntimeError("flaky")
        return BackgroundTaskRunResult(summary="succeeded on retry")

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())
        await _wait_until(_status_reaches(store, task.task_id, BackgroundTaskStatus.FAILED))

        retried = await manager.retry(task.task_id)
        assert retried is not None
        assert retried.attempt_index == 1

        await _wait_until(_status_reaches(store, task.task_id, BackgroundTaskStatus.SUCCEEDED))
        fetched = await store.get_task(task.task_id)
        assert fetched is not None
        assert fetched.summary == "succeeded on retry"
        assert fetched.attempt_index == 1
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_retry_running_task_is_rejected(tmp_path: Path) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))
    running = asyncio.Event()
    release = asyncio.Event()

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        running.set()
        await release.wait()
        return BackgroundTaskRunResult()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())
        await running.wait()

        assert await manager.retry(task.task_id) is None

        release.set()
        await _wait_until(_status_reaches(store, task.task_id, BackgroundTaskStatus.SUCCEEDED))
    finally:
        await manager.stop()


# ----------------------------------------------------------------------
# Restart recovery
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_marks_stale_running_as_failed_and_rehydrates_pending(
    tmp_path: Path,
) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))

    # Simulate a previous process that was mid-run.
    stale = BackgroundTask.new(_make_spec(origin_turn_id="stale"))
    stale.status = BackgroundTaskStatus.RUNNING
    stale.started_at = 100.0
    pending = BackgroundTask.new(_make_spec(origin_turn_id="pending"))
    for t in (stale, pending):
        await store.create_task(t)

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult(summary="rehydrated")

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        await _wait_until(_status_reaches(store, pending.task_id, BackgroundTaskStatus.SUCCEEDED))
        stale_row = await store.get_task(stale.task_id)
        assert stale_row is not None
        assert stale_row.status == BackgroundTaskStatus.FAILED
        assert stale_row.error == "backend_restart"
    finally:
        await manager.stop()


# ----------------------------------------------------------------------
# Lifecycle
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path: Path) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    await manager.start()  # must not raise
    try:
        assert manager.active_count() == 0
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_enqueue_before_start_raises(tmp_path: Path) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    with pytest.raises(RuntimeError):
        await manager.enqueue(_make_spec())


@pytest.mark.asyncio
async def test_stop_cancels_in_flight_tasks(tmp_path: Path) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))
    running = asyncio.Event()

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        running.set()
        while not await token.is_cancelled():
            await asyncio.sleep(0.01)
        raise asyncio.CancelledError

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    task = await manager.enqueue(_make_spec())
    await running.wait()

    await manager.stop()

    fetched = await store.get_task(task.task_id)
    assert fetched is not None
    assert fetched.status == BackgroundTaskStatus.CANCELLED
    assert fetched.cancel_reason == "shutdown"


# ----------------------------------------------------------------------
# Listener API
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listener_is_invoked_on_succeeded_terminal_state(
    tmp_path: Path,
) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult(summary="ok", result_payload={})

    seen: list[tuple[str, BackgroundTaskStatus]] = []

    async def listener(task: BackgroundTask) -> None:
        seen.append((task.task_id, task.status))

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    manager.add_listener(listener)
    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())
        await _wait_until(
            _status_reaches(store, task.task_id, BackgroundTaskStatus.SUCCEEDED)
        )
        await _wait_until(lambda: len(seen) == 1)
        assert seen == [(task.task_id, BackgroundTaskStatus.SUCCEEDED)]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_listener_is_invoked_on_failure_terminal_state(tmp_path: Path) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        raise RuntimeError("boom")

    seen: list[BackgroundTaskStatus] = []

    async def listener(task: BackgroundTask) -> None:
        seen.append(task.status)

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    manager.add_listener(listener)
    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())
        await _wait_until(
            _status_reaches(store, task.task_id, BackgroundTaskStatus.FAILED)
        )
        await _wait_until(lambda: len(seen) == 1)
        assert seen == [BackgroundTaskStatus.FAILED]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_listener_exception_does_not_break_other_listeners(
    tmp_path: Path,
) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult(summary="ok", result_payload={})

    async def bad_listener(task: BackgroundTask) -> None:
        raise ValueError("nope")

    captured: list[str] = []

    async def good_listener(task: BackgroundTask) -> None:
        captured.append(task.task_id)

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    manager.add_listener(bad_listener)
    manager.add_listener(good_listener)
    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())
        await _wait_until(lambda: len(captured) == 1)
        assert captured == [task.task_id]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_remove_listener_stops_subsequent_invocations(
    tmp_path: Path,
) -> None:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult(summary="ok", result_payload={})

    calls: list[str] = []

    async def listener(task: BackgroundTask) -> None:
        calls.append(task.task_id)

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    manager.add_listener(listener)
    # add_listener is idempotent per-reference.
    manager.add_listener(listener)
    await manager.start()
    try:
        first = await manager.enqueue(_make_spec(origin_turn_id="t1"))
        await _wait_until(lambda: len(calls) == 1)
        assert calls == [first.task_id]

        manager.remove_listener(listener)
        # remove_listener of an unknown listener is a no-op.
        manager.remove_listener(listener)

        second = await manager.enqueue(_make_spec(origin_turn_id="t2"))
        await _wait_until(
            _status_reaches(store, second.task_id, BackgroundTaskStatus.SUCCEEDED)
        )
        # Let any pending listener dispatch complete.
        await asyncio.sleep(0.02)
        assert calls == [first.task_id]
    finally:
        await manager.stop()

