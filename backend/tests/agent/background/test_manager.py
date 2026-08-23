from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import pytest

from magi.agent.background import (
    BackgroundTask,
    BackgroundTaskEvent,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskStore,
    BackgroundTaskTriggerSource,
)
from magi.agent.background.executor import BackgroundTaskRunResult
from magi.agent.background.manager import (
    BackgroundTaskAdmissionBlockedError,
    BackgroundTaskManager,
)
from magi.agent.cancel import CancelToken


def _make_spec(
    *,
    user_id: str = "u",
    session_id: str = "s",
    origin_turn_id: str = "turn-1",
    pending_message_id: str | None = None,
) -> BackgroundTaskSpec:
    return BackgroundTaskSpec(
        user_id=user_id,
        session_id=session_id,
        origin_turn_id=origin_turn_id,
        title="Demo task",
        goal="do something",
        selected_tools=[],
        trigger_source=BackgroundTaskTriggerSource.PLANNER,
        pending_message_id=pending_message_id,
    )


async def _wait_until(
    predicate: Callable[[], bool | Awaitable[bool]],
    *,
    timeout: float = 5.0,
) -> None:
    """Poll ``predicate`` on a tight event-loop cycle until it is truthy.

    The timeout only bounds how long a *failing* wait blocks before raising — a satisfied
    condition returns within a poll cycle. It is generous (5s) so that CPU contention under
    parallel test runs (``pytest -n auto``) does not turn a slow-but-correct transition into
    a spurious timeout; a genuinely stuck task still fails, just a little later.
    """
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


async def _get_status(store: BackgroundTaskStore, task_id: str) -> BackgroundTaskStatus | None:
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


async def _wait_for_terminal_event(
    store: BackgroundTaskStore,
    task_id: str,
    terminal: BackgroundTaskStatus,
) -> None:
    """Wait until the event log's last transition is ``terminal``.

    The status column and the event-log rows are written on separate paths, so a
    ``_status_reaches`` wait can return before the terminal event row is visible. Tests
    that assert on ``list_events()`` must wait on the log itself, not the status column, or
    they flake under parallel runs (the terminal event lags the status write). Use this only
    for tasks whose transitions are strictly linear; for racy append orders (e.g. cancel,
    where the executor's CANCELLED can precede the manager's CANCELLING) wait on membership.
    """

    async def _check() -> bool:
        recorded = [e.to_status for e in await store.list_events(task_id)]
        return bool(recorded) and recorded[-1] == terminal

    await _wait_until(_check)


# ----------------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueued_task_runs_to_succeeded(runtime_paths_with_schema) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

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

        # Wait for the SUCCEEDED event row, not just the status column (separate write paths).
        await _wait_for_terminal_event(store, task.task_id, BackgroundTaskStatus.SUCCEEDED)
        transitions = [e.to_status for e in await store.list_events(task.task_id)]
        assert transitions == [
            BackgroundTaskStatus.PENDING,
            BackgroundTaskStatus.RUNNING,
            BackgroundTaskStatus.SUCCEEDED,
        ]
        assert await store.count_pending_completion_intents() == 1
    finally:
        await manager.stop()


# ----------------------------------------------------------------------
# Concurrency cap
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrency_cap_is_respected(runtime_paths_with_schema) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
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
                row is not None and row.status == BackgroundTaskStatus.SUCCEEDED for row in rows
            )

        await _wait_until(_all_succeeded)
        assert peak["value"] == 2
    finally:
        await manager.stop()


# ----------------------------------------------------------------------
# Cancellation
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_running_task_transitions_to_cancelled(runtime_paths_with_schema) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
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

        # The status column and the event-log rows are written on separate paths, so
        # status==CANCELLED does NOT guarantee the CANCELLED event row is visible yet.
        # Both transitions are recorded, but their append-order is non-deterministic under
        # load: manager.cancel() flips the token (waking the run loop) before it appends
        # the CANCELLING event, so the executor can append CANCELLED first. Wait for the
        # event log to actually contain both before asserting on its contents — polling the
        # log (not the status) is what makes this robust under parallel test runs.
        async def _events_have_both() -> bool:
            recorded = [e.to_status for e in await store.list_events(task.task_id)]
            return (
                BackgroundTaskStatus.CANCELLING in recorded
                and BackgroundTaskStatus.CANCELLED in recorded
            )

        await _wait_until(_events_have_both)

        transitions = [e.to_status for e in await store.list_events(task.task_id)]
        assert BackgroundTaskStatus.CANCELLING in transitions
        assert BackgroundTaskStatus.CANCELLED in transitions
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_cancel_unknown_task_returns_false(runtime_paths_with_schema) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        assert await manager.cancel("bg_missing") is False
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_cancel_pending_task_skips_dispatch(runtime_paths_with_schema) -> None:
    """Cancelling a queued-but-not-dispatched task must flip it to cancelled
    without ever invoking ``run_fn``."""
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
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


@pytest.mark.asyncio
async def test_cancel_pending_returns_before_listener_and_stop_waits_for_it(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    first_running = asyncio.Event()
    release_first = asyncio.Event()
    listener_started = asyncio.Event()
    release_listener = asyncio.Event()

    async def run_fn(
        task: BackgroundTask,
        token: CancelToken,
    ) -> BackgroundTaskRunResult:
        if task.spec.origin_turn_id == "first":
            first_running.set()
            await release_first.wait()
        return BackgroundTaskRunResult()

    async def listener(task: BackgroundTask) -> None:
        if task.spec.origin_turn_id == "cancelled-pending":
            listener_started.set()
            await release_listener.wait()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    manager.add_listener(listener)
    await manager.start()
    try:
        await manager.enqueue(_make_spec(origin_turn_id="first"))
        pending = await manager.enqueue(_make_spec(origin_turn_id="cancelled-pending"))
        await first_running.wait()

        assert await asyncio.wait_for(
            manager.cancel(pending.task_id),
            timeout=0.2,
        )
        await listener_started.wait()

        release_first.set()
        stopping = asyncio.create_task(manager.stop())
        await asyncio.sleep(0)
        assert not stopping.done()

        release_listener.set()
        await stopping
    finally:
        release_first.set()
        release_listener.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_cancel_scope_waits_for_matching_terminal_listener(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    target_running = asyncio.Event()
    survivor_running = asyncio.Event()
    listener_started = asyncio.Event()
    release_listener = asyncio.Event()
    release_survivor = asyncio.Event()

    async def run_fn(
        task: BackgroundTask,
        token: CancelToken,
    ) -> BackgroundTaskRunResult:
        if task.spec.origin_turn_id == "target":
            target_running.set()
            while not await token.is_cancelled():
                await asyncio.sleep(0.005)
            raise asyncio.CancelledError
        survivor_running.set()
        await release_survivor.wait()
        return BackgroundTaskRunResult(summary="kept")

    async def listener(task: BackgroundTask) -> None:
        if task.spec.origin_turn_id == "target":
            listener_started.set()
            await release_listener.wait()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=2)
    manager.add_listener(listener)
    await manager.start()
    try:
        target = await manager.enqueue(_make_spec(origin_turn_id="target"))
        survivor = await manager.enqueue(_make_spec(origin_turn_id="survivor"))
        await asyncio.gather(target_running.wait(), survivor_running.wait())

        cancellation = asyncio.create_task(
            manager.cancel_scope_and_wait(
                user_id="u",
                session_id="s",
                origin_turn_ids={"target"},
            )
        )
        await listener_started.wait()
        assert not cancellation.done()

        release_listener.set()
        assert await cancellation == 1
        target_row = await store.get_task(target.task_id)
        survivor_row = await store.get_task(survivor.task_id)
        assert target_row is not None
        assert target_row.status == BackgroundTaskStatus.CANCELLED
        assert survivor_row is not None
        assert survivor_row.status == BackgroundTaskStatus.RUNNING

        release_survivor.set()
        await _wait_until(
            _status_reaches(
                store,
                survivor.task_id,
                BackgroundTaskStatus.SUCCEEDED,
            )
        )
    finally:
        release_listener.set()
        release_survivor.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_cancel_scope_collects_attempt_notification_created_after_wait_started(
    runtime_paths_with_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.agent.background.manager as manager_module

    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    attempt_callback_entered = asyncio.Event()
    initial_wait_started = asyncio.Event()
    allow_attempt_notification = asyncio.Event()
    listener_started = asyncio.Event()
    release_listener = asyncio.Event()

    async def run_fn(
        task: BackgroundTask,
        token: CancelToken,
    ) -> BackgroundTaskRunResult:
        if await token.is_cancelled():
            raise asyncio.CancelledError
        return BackgroundTaskRunResult()

    async def attempt_listener(task: BackgroundTask) -> None:
        listener_started.set()
        await release_listener.wait()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    manager.add_attempt_listener(attempt_listener)
    await manager.start()
    assert manager._executor is not None
    real_schedule = manager._schedule_attempt_notification
    real_shield = asyncio.shield

    def tracking_shield(waiter, *args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(waiter, asyncio.Task) and waiter.get_name().startswith("background-task:"):
            initial_wait_started.set()
        return real_shield(waiter, *args, **kwargs)

    monkeypatch.setattr(manager_module.asyncio, "shield", tracking_shield)

    async def delayed_schedule(task: BackgroundTask) -> None:
        attempt_callback_entered.set()
        await allow_attempt_notification.wait()
        await real_schedule(task)

    manager._executor._on_attempt_started = delayed_schedule
    try:
        task = await manager.enqueue(_make_spec(origin_turn_id="late-notification"))
        await attempt_callback_entered.wait()
        cancellation = asyncio.create_task(
            manager.cancel_scope_and_wait(
                user_id="u",
                session_id="s",
                origin_turn_ids={"late-notification"},
            )
        )
        await initial_wait_started.wait()
        assert manager._attempt_notifications == {}
        assert not cancellation.done()

        allow_attempt_notification.set()
        await listener_started.wait()
        await asyncio.sleep(0)
        assert not cancellation.done()

        release_listener.set()
        assert await cancellation == 1
        persisted = await store.get_task(task.task_id)
        assert persisted is not None
        assert persisted.status == BackgroundTaskStatus.CANCELLED
    finally:
        allow_attempt_notification.set()
        release_listener.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_cancel_scope_cancels_suspended_task(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    running = asyncio.Event()

    async def run_fn(
        task: BackgroundTask,
        token: CancelToken,
    ) -> BackgroundTaskRunResult:
        running.set()
        while not await token.is_cancelled():
            await asyncio.sleep(0.005)
        raise asyncio.CancelledError

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        task = await manager.enqueue(_make_spec(origin_turn_id="suspended"))
        await running.wait()
        persisted = await store.get_task(task.task_id)
        assert persisted is not None
        persisted.status = BackgroundTaskStatus.SUSPENDED_WAITING_USER
        await store.update_task(persisted)

        assert (
            await manager.cancel_scope_and_wait(
                user_id="u",
                session_id="s",
                origin_turn_ids={"suspended"},
            )
            == 1
        )
        cancelled = await store.get_task(task.task_id)
        assert cancelled is not None
        assert cancelled.status == BackgroundTaskStatus.CANCELLED
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_cancel_scope_fails_when_matching_work_does_not_stop(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    running = asyncio.Event()
    release = asyncio.Event()

    async def run_fn(
        task: BackgroundTask,
        token: CancelToken,
    ) -> BackgroundTaskRunResult:
        running.set()
        await release.wait()
        return BackgroundTaskRunResult()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        await manager.enqueue(_make_spec(origin_turn_id="stuck"))
        await running.wait()

        with pytest.raises(
            RuntimeError,
            match="did not stop before deletion",
        ):
            await manager.cancel_scope_and_wait(
                user_id="u",
                session_id="s",
                origin_turn_ids={"stuck"},
                timeout_seconds=0.01,
            )
    finally:
        release.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_conversation_scope_boundary_rejects_exact_pending_message_admission(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    release = asyncio.Event()

    async def run_fn(
        task: BackgroundTask,
        token: CancelToken,
    ) -> BackgroundTaskRunResult:
        await release.wait()
        return BackgroundTaskRunResult(summary=task.spec.pending_message_id)

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=2)
    await manager.start()
    try:
        target_spec = _make_spec(
            origin_turn_id="",
            pending_message_id="pending-target",
        )
        survivor_spec = _make_spec(
            origin_turn_id="",
            pending_message_id="pending-survivor",
        )
        async with manager.conversation_scope_boundary(
            user_id="u",
            session_id="s",
            origin_turn_ids=set(),
            pending_message_ids={"pending-target"},
        ):
            with pytest.raises(BackgroundTaskAdmissionBlockedError):
                await manager.enqueue(target_spec)
            survivor = await manager.enqueue(survivor_spec)
            persisted = await store.list_tasks(limit=10)
            assert [task.task_id for task in persisted] == [survivor.task_id]

        target = await manager.enqueue(target_spec)
        release.set()
        await _wait_until(
            _status_reaches(
                store,
                survivor.task_id,
                BackgroundTaskStatus.SUCCEEDED,
            )
        )
        await _wait_until(
            _status_reaches(
                store,
                target.task_id,
                BackgroundTaskStatus.SUCCEEDED,
            )
        )
    finally:
        release.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_clear_all_history_requires_and_uses_global_admission_seal(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult(summary="done")

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        with pytest.raises(RuntimeError, match="global admission seal"):
            await manager.clear_all_history()

        async with manager.conversation_scope_boundary(
            session_id="different-session",
            reason="scoped_conversation_clear",
        ):
            with pytest.raises(RuntimeError, match="global admission seal"):
                await manager.clear_all_history()

        task = BackgroundTask.new(_make_spec(origin_turn_id="terminal-before-clear"))
        await store.create_task(task)
        task.status = BackgroundTaskStatus.SUCCEEDED
        await store.persist_terminal_transition(
            task,
            BackgroundTaskEvent.transition(
                task_id=task.task_id,
                attempt_index=task.attempt_index,
                from_status=BackgroundTaskStatus.PENDING,
                to_status=BackgroundTaskStatus.SUCCEEDED,
            ),
        )

        async with manager.conversation_scope_boundary(reason="user_clear_all_memory"):
            removed = await manager.clear_all_history()

        assert removed == {
            "tool_effect_attempts": 0,
            "background_tasks": 1,
            "background_task_events": 1,
            "background_task_completion_intents": 1,
        }
        assert await store.get_task(task.task_id) is None
        assert await store.list_events(task.task_id) == []
        assert await store.count_pending_completion_intents() == 0
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_conversation_scope_boundary_cancels_existing_pending_message_task(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    blocker_running = asyncio.Event()
    release_blocker = asyncio.Event()
    target_started = False

    async def run_fn(
        task: BackgroundTask,
        token: CancelToken,
    ) -> BackgroundTaskRunResult:
        nonlocal target_started
        if task.spec.origin_turn_id == "blocker":
            blocker_running.set()
            await release_blocker.wait()
        else:
            target_started = True
        return BackgroundTaskRunResult()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        await manager.enqueue(_make_spec(origin_turn_id="blocker"))
        target = await manager.enqueue(
            _make_spec(
                origin_turn_id="",
                pending_message_id="pending-target",
            )
        )
        await blocker_running.wait()

        async with manager.conversation_scope_boundary(
            user_id="u",
            session_id="s",
            origin_turn_ids=set(),
            pending_message_ids={"pending-target"},
        ):
            persisted = await store.get_task(target.task_id)
            assert persisted is not None
            assert persisted.status is BackgroundTaskStatus.CANCELLED
            assert await store.count_pending_completion_intents() == 0
            assert target_started is False
    finally:
        release_blocker.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_conversation_scope_boundary_rejects_matching_retry(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

    async def run_fn(
        task: BackgroundTask,
        token: CancelToken,
    ) -> BackgroundTaskRunResult:
        raise RuntimeError("failed")

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())
        await _wait_until(
            _status_reaches(
                store,
                task.task_id,
                BackgroundTaskStatus.FAILED,
            )
        )

        async with manager.conversation_scope_boundary(
            user_id="u",
            session_id="s",
            task_ids={task.task_id},
        ):
            with pytest.raises(BackgroundTaskAdmissionBlockedError):
                await manager.retry(task.task_id)
            persisted = await store.get_task(task.task_id)
            assert persisted is not None
            assert persisted.status is BackgroundTaskStatus.FAILED
            assert persisted.attempt_index == 0
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_conversation_scope_boundary_blocks_only_the_selected_session(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    release = asyncio.Event()

    async def run_fn(
        task: BackgroundTask,
        token: CancelToken,
    ) -> BackgroundTaskRunResult:
        await release.wait()
        return BackgroundTaskRunResult()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        async with manager.conversation_scope_boundary(
            user_id="u",
            session_id="deleted-session",
        ):
            with pytest.raises(BackgroundTaskAdmissionBlockedError):
                await manager.enqueue(_make_spec(session_id="deleted-session"))
            survivor = await manager.enqueue(_make_spec(session_id="surviving-session"))

        release.set()
        await _wait_until(
            _status_reaches(
                store,
                survivor.task_id,
                BackgroundTaskStatus.SUCCEEDED,
            )
        )
    finally:
        release.set()
        await manager.stop()


# ----------------------------------------------------------------------
# Failure paths
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_fn_exception_marks_task_failed(runtime_paths_with_schema) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

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
async def test_run_fn_timeout_marks_task_failed(runtime_paths_with_schema) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

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
async def test_retry_after_failure_reruns_with_incremented_attempt(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
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
async def test_retry_during_slow_terminal_listener_is_not_lost(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    listener_started = asyncio.Event()
    release_listener = asyncio.Event()
    run_attempts: list[int] = []

    async def run_fn(
        task: BackgroundTask,
        token: CancelToken,
    ) -> BackgroundTaskRunResult:
        run_attempts.append(task.attempt_index)
        if task.attempt_index == 0:
            raise RuntimeError("first attempt failed")
        return BackgroundTaskRunResult(summary="retry completed")

    async def listener(task: BackgroundTask) -> None:
        if task.attempt_index == 0 and task.status == BackgroundTaskStatus.FAILED:
            listener_started.set()
            await release_listener.wait()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    manager.add_listener(listener)
    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())
        await listener_started.wait()

        retried = await manager.retry(task.task_id)
        assert retried is not None
        assert retried.attempt_index == 1
        release_listener.set()

        await _wait_until(
            _status_reaches(
                store,
                task.task_id,
                BackgroundTaskStatus.SUCCEEDED,
            )
        )
        assert run_attempts == [0, 1]
    finally:
        release_listener.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_concurrent_retry_admits_only_one_new_attempt(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    release_retry = asyncio.Event()

    async def run_fn(
        task: BackgroundTask,
        token: CancelToken,
    ) -> BackgroundTaskRunResult:
        if task.attempt_index == 0:
            raise RuntimeError("first attempt failed")
        await release_retry.wait()
        return BackgroundTaskRunResult(summary="retry completed")

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())
        await _wait_until(
            _status_reaches(
                store,
                task.task_id,
                BackgroundTaskStatus.FAILED,
            )
        )
        results = await asyncio.gather(
            manager.retry(task.task_id),
            manager.retry(task.task_id),
        )
        assert sum(result is not None for result in results) == 1
        assert {result.attempt_index for result in results if result is not None} == {1}

        release_retry.set()
        await _wait_until(
            _status_reaches(
                store,
                task.task_id,
                BackgroundTaskStatus.SUCCEEDED,
            )
        )
        persisted = await store.get_task(task.task_id)
        assert persisted is not None and persisted.attempt_index == 1
    finally:
        release_retry.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_retry_running_task_is_rejected(runtime_paths_with_schema) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
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
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

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
async def test_start_is_idempotent(runtime_paths_with_schema) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

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
async def test_enqueue_before_start_raises(runtime_paths_with_schema) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    with pytest.raises(RuntimeError):
        await manager.enqueue(_make_spec())


@pytest.mark.asyncio
async def test_stop_cancels_in_flight_tasks(runtime_paths_with_schema) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
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
async def test_slow_attempt_listener_does_not_delay_task_execution(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    listener_started = asyncio.Event()
    release_listener = asyncio.Event()
    run_started = asyncio.Event()

    async def run_fn(
        task: BackgroundTask,
        token: CancelToken,
    ) -> BackgroundTaskRunResult:
        run_started.set()
        return BackgroundTaskRunResult(summary="ok")

    async def attempt_listener(task: BackgroundTask) -> None:
        listener_started.set()
        await release_listener.wait()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    manager.add_attempt_listener(attempt_listener)
    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())
        await listener_started.wait()
        await asyncio.wait_for(run_started.wait(), timeout=0.2)
        await _wait_until(
            _status_reaches(
                store,
                task.task_id,
                BackgroundTaskStatus.SUCCEEDED,
            )
        )
    finally:
        release_listener.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_listener_is_invoked_on_succeeded_terminal_state(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

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
        await _wait_until(_status_reaches(store, task.task_id, BackgroundTaskStatus.SUCCEEDED))
        await _wait_until(lambda: len(seen) == 1)
        assert seen == [(task.task_id, BackgroundTaskStatus.SUCCEEDED)]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_listener_is_invoked_on_failure_terminal_state(runtime_paths_with_schema) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

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
        await _wait_until(_status_reaches(store, task.task_id, BackgroundTaskStatus.FAILED))
        await _wait_until(lambda: len(seen) == 1)
        assert seen == [BackgroundTaskStatus.FAILED]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_listener_exception_does_not_break_other_listeners(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

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
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

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
        await _wait_until(_status_reaches(store, second.task_id, BackgroundTaskStatus.SUCCEEDED))
        # Let any pending listener dispatch complete.
        await asyncio.sleep(0.02)
        assert calls == [first.task_id]
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_suspend_and_resume_waiting_user(runtime_paths_with_schema) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    running = asyncio.Event()
    proceed = asyncio.Event()

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        running.set()
        await proceed.wait()
        return BackgroundTaskRunResult()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        task = await manager.enqueue(_make_spec())
        await running.wait()
        await _wait_until(_status_reaches(store, task.task_id, BackgroundTaskStatus.RUNNING))

        assert (
            await manager.suspend_waiting_user(task.task_id, reason="awaiting_user_answer") is True
        )
        fetched = await store.get_task(task.task_id)
        assert fetched is not None
        assert fetched.status == BackgroundTaskStatus.SUSPENDED_WAITING_USER

        # Suspending twice is a no-op (only RUNNING → SUSPENDED allowed).
        assert await manager.suspend_waiting_user(task.task_id) is False

        assert await manager.resume_from_wait(task.task_id) is True
        fetched = await store.get_task(task.task_id)
        assert fetched is not None
        assert fetched.status == BackgroundTaskStatus.RUNNING

        proceed.set()
        # Wait for the SUCCEEDED event row, not just the status column (separate write paths,
        # so status==SUCCEEDED can precede the terminal event append and flake transitions[-1]).
        await _wait_for_terminal_event(store, task.task_id, BackgroundTaskStatus.SUCCEEDED)

        transitions = [e.to_status for e in await store.list_events(task.task_id)]
        assert BackgroundTaskStatus.SUSPENDED_WAITING_USER in transitions
        # After resume the task should be RUNNING again before succeeding.
        assert transitions.count(BackgroundTaskStatus.RUNNING) >= 2
        assert transitions[-1] == BackgroundTaskStatus.SUCCEEDED
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_resume_from_wait_unknown_or_non_suspended(runtime_paths_with_schema) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult()

    manager = BackgroundTaskManager(store=store, run_fn=run_fn, max_concurrent=1)
    await manager.start()
    try:
        # Unknown task.
        assert await manager.resume_from_wait("bg_missing") is False
        assert await manager.suspend_waiting_user("bg_missing") is False
    finally:
        await manager.stop()
