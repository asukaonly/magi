from __future__ import annotations

import sqlite3

import pytest

from magi.agent.background import (
    BackgroundTask,
    BackgroundTaskEvent,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskStore,
)
from magi.agent.background.executor import (
    BackgroundTaskExecutor,
    BackgroundTaskRunResult,
)
from magi.agent.cancel import EventCancelToken


def _spec() -> BackgroundTaskSpec:
    return BackgroundTaskSpec(
        user_id="user-1",
        session_id="session-1",
        origin_turn_id="turn-1",
        title="Durable task",
        goal="finish reliably",
    )


@pytest.mark.asyncio
async def test_terminal_state_event_and_completion_intent_roll_back_together(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)
    )
    task = BackgroundTask.new(_spec())
    task.status = BackgroundTaskStatus.RUNNING
    await store.create_task(task)
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            f"""
            CREATE TRIGGER reject_completion_{task.task_id}
            BEFORE INSERT ON background_task_completion_intents
            WHEN NEW.task_id = '{task.task_id}'
            BEGIN
                SELECT RAISE(ABORT, 'completion insert rejected');
            END
            """
        )

    task.status = BackgroundTaskStatus.SUCCEEDED
    task.summary = "done"
    task.finished_at = 100.0
    task.updated_at = 100.0
    with pytest.raises(sqlite3.IntegrityError, match="completion insert rejected"):
        await store.persist_terminal_transition(
            task,
            BackgroundTaskEvent.transition(
                task_id=task.task_id,
                attempt_index=0,
                from_status=BackgroundTaskStatus.RUNNING,
                to_status=BackgroundTaskStatus.SUCCEEDED,
            ),
        )

    persisted = await store.get_task(task.task_id)
    assert persisted is not None
    assert persisted.status is BackgroundTaskStatus.RUNNING
    assert await store.list_events(task.task_id) == []
    assert await store.count_pending_completion_intents() == 0


@pytest.mark.asyncio
async def test_each_retry_attempt_keeps_its_own_immutable_completion_snapshot(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)
    )
    task = BackgroundTask.new(_spec())
    task.status = BackgroundTaskStatus.RUNNING
    await store.create_task(task)

    task.status = BackgroundTaskStatus.FAILED
    task.error = "first attempt failed"
    task.finished_at = 100.0
    task.updated_at = 100.0
    await store.persist_terminal_transition(
        task,
        BackgroundTaskEvent.transition(
            task_id=task.task_id,
            attempt_index=0,
            from_status=BackgroundTaskStatus.RUNNING,
            to_status=BackgroundTaskStatus.FAILED,
        ),
    )

    task.attempt_index = 1
    task.status = BackgroundTaskStatus.PENDING
    task.error = None
    task.finished_at = None
    task.updated_at = 101.0
    await store.update_task(task)
    task.status = BackgroundTaskStatus.RUNNING
    task.started_at = 102.0
    task.updated_at = 102.0
    await store.update_task(task)
    task.status = BackgroundTaskStatus.SUCCEEDED
    task.summary = "second attempt succeeded"
    task.finished_at = 103.0
    task.updated_at = 103.0
    await store.persist_terminal_transition(
        task,
        BackgroundTaskEvent.transition(
            task_id=task.task_id,
            attempt_index=1,
            from_status=BackgroundTaskStatus.RUNNING,
            to_status=BackgroundTaskStatus.SUCCEEDED,
        ),
    )

    completions = await store.list_pending_completions()

    assert [
        (
            completion.task.attempt_index,
            completion.task.status,
            completion.task.error,
            completion.task.summary,
        )
        for completion in completions
    ] == [
        (
            0,
            BackgroundTaskStatus.FAILED,
            "first attempt failed",
            None,
        ),
        (
            1,
            BackgroundTaskStatus.SUCCEEDED,
            None,
            "second attempt succeeded",
        ),
    ]


@pytest.mark.asyncio
async def test_cancel_wins_race_before_attempt_start_without_running_work(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)
    )
    task = BackgroundTask.new(_spec())
    await store.create_task(task)
    cancelled = await store.persist_cancellation_request(
        task_id=task.task_id,
        reason="deleted_before_start",
        updated_at=100.0,
    )
    assert cancelled is not None
    assert cancelled.status is BackgroundTaskStatus.CANCELLED
    run_calls = 0

    async def run_fn(_task, _token):
        nonlocal run_calls
        run_calls += 1
        return BackgroundTaskRunResult()

    executor = BackgroundTaskExecutor(
        store=store,
        run_fn=run_fn,
        clock=lambda: 101.0,
    )
    finished = await executor.execute(task, EventCancelToken())

    assert finished.status is BackgroundTaskStatus.CANCELLED
    assert run_calls == 0
    assert await store.count_pending_completion_intents() == 1
