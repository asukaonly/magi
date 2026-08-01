from __future__ import annotations

import pytest

from magi.agent.background import (
    BackgroundTask,
    BackgroundTaskEvent,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskStore,
    BackgroundTaskTriggerSource,
)


def _make_spec(
    *,
    user_id: str = "u-alice",
    session_id: str = "s-1",
    origin_turn_id: str = "turn-root",
    title: str = "Deep research",
    goal: str = "Research the latest papers on transformer distillation.",
    trigger_source: BackgroundTaskTriggerSource = BackgroundTaskTriggerSource.PLANNER,
    selected_tools: list[str] | None = None,
    timeout_seconds: int | None = 900,
) -> BackgroundTaskSpec:
    return BackgroundTaskSpec(
        user_id=user_id,
        session_id=session_id,
        origin_turn_id=origin_turn_id,
        title=title,
        goal=goal,
        selected_tools=list(selected_tools or ["web_search", "deep_research"]),
        trigger_source=trigger_source,
        timeout_seconds=timeout_seconds,
    )


@pytest.fixture
def store(runtime_paths_with_schema) -> BackgroundTaskStore:
    return BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)
    )


# ----------------------------------------------------------------------
# Spec / task dataclass round-trips (serialization boundary sanity)
# ----------------------------------------------------------------------


def test_spec_round_trips_through_to_dict_from_dict() -> None:
    original = _make_spec(
        selected_tools=["a", "b"],
        trigger_source=BackgroundTaskTriggerSource.USER,
        timeout_seconds=None,
    )

    restored = BackgroundTaskSpec.from_dict(original.to_dict())

    assert restored == original


def test_background_task_new_initialises_pending_state() -> None:
    task = BackgroundTask.new(_make_spec())

    assert task.status is BackgroundTaskStatus.PENDING
    assert task.attempt_index == 0
    assert task.task_id.startswith("bg_")
    assert task.started_at is None
    assert task.finished_at is None


def test_background_task_status_terminal_set() -> None:
    terminal = BackgroundTaskStatus.terminal()

    assert BackgroundTaskStatus.SUCCEEDED in terminal
    assert BackgroundTaskStatus.FAILED in terminal
    assert BackgroundTaskStatus.CANCELLED in terminal
    assert BackgroundTaskStatus.PENDING not in terminal
    assert BackgroundTaskStatus.RUNNING not in terminal
    assert BackgroundTaskStatus.CANCELLING not in terminal
    assert BackgroundTaskStatus.SUCCEEDED.is_terminal is True
    assert BackgroundTaskStatus.RUNNING.is_terminal is False


# ----------------------------------------------------------------------
# Task persistence
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get_task_round_trip(store: BackgroundTaskStore) -> None:
    task = BackgroundTask.new(_make_spec())

    await store.create_task(task)
    fetched = await store.get_task(task.task_id)

    assert fetched is not None
    assert fetched.task_id == task.task_id
    assert fetched.spec == task.spec
    assert fetched.status is BackgroundTaskStatus.PENDING
    assert fetched.attempt_index == 0
    assert fetched.result_payload == {}


@pytest.mark.asyncio
async def test_get_task_returns_none_for_unknown_id(store: BackgroundTaskStore) -> None:
    assert await store.get_task("bg_missing") is None


@pytest.mark.asyncio
async def test_update_task_persists_mutable_fields(store: BackgroundTaskStore) -> None:
    task = BackgroundTask.new(_make_spec())
    await store.create_task(task)

    task.status = BackgroundTaskStatus.RUNNING
    task.orchestration_id = "orch-1"
    task.started_at = 1_700_000_000.0
    await store.update_task(task)

    task.status = BackgroundTaskStatus.SUCCEEDED
    task.summary = "done"
    task.result_payload = {"answer": "42"}
    task.finished_at = 1_700_000_500.0
    await store.update_task(task)

    fetched = await store.get_task(task.task_id)

    assert fetched is not None
    assert fetched.status is BackgroundTaskStatus.SUCCEEDED
    assert fetched.orchestration_id == "orch-1"
    assert fetched.summary == "done"
    assert fetched.result_payload == {"answer": "42"}
    assert fetched.started_at == 1_700_000_000.0
    assert fetched.finished_at == 1_700_000_500.0
    assert fetched.updated_at >= task.started_at  # bumped by update_task


@pytest.mark.asyncio
async def test_delete_task_removes_task_and_events(store: BackgroundTaskStore) -> None:
    task = BackgroundTask.new(_make_spec())
    await store.create_task(task)
    await store.append_event(
        BackgroundTaskEvent.transition(
            task_id=task.task_id,
            attempt_index=0,
            from_status=None,
            to_status=BackgroundTaskStatus.PENDING,
        )
    )

    removed = await store.delete_task(task.task_id)

    assert removed is True
    assert await store.get_task(task.task_id) is None
    assert await store.list_events(task.task_id) == []
    # Idempotent: second delete returns False instead of raising.
    assert await store.delete_task(task.task_id) is False


@pytest.mark.asyncio
async def test_clear_all_removes_tasks_events_and_completion_intents(
    store: BackgroundTaskStore,
) -> None:
    task = BackgroundTask.new(_make_spec(goal="private task payload"))
    await store.create_task(task)
    task.status = BackgroundTaskStatus.SUCCEEDED
    task.summary = "private completion summary"
    task.result_payload = {"private": "result"}
    await store.persist_terminal_transition(
        task,
        BackgroundTaskEvent.transition(
            task_id=task.task_id,
            attempt_index=task.attempt_index,
            from_status=BackgroundTaskStatus.PENDING,
            to_status=BackgroundTaskStatus.SUCCEEDED,
            message="private terminal event",
        ),
    )

    removed = await store.clear_all()

    assert removed == {
        "background_tasks": 1,
        "background_task_events": 1,
        "background_task_completion_intents": 1,
    }
    assert await store.get_task(task.task_id) is None
    assert await store.list_events(task.task_id) == []
    assert await store.count_pending_completion_intents() == 0


# ----------------------------------------------------------------------
# Queries
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tasks_filters_by_user_and_session(store: BackgroundTaskStore) -> None:
    alice_s1 = BackgroundTask.new(_make_spec(user_id="alice", session_id="s-1"))
    alice_s2 = BackgroundTask.new(_make_spec(user_id="alice", session_id="s-2"))
    bob_s1 = BackgroundTask.new(_make_spec(user_id="bob", session_id="s-1"))

    for task in (alice_s1, alice_s2, bob_s1):
        await store.create_task(task)

    alice_all = await store.list_tasks(user_id="alice")
    alice_s1_only = await store.list_tasks(user_id="alice", session_id="s-1")
    bob_all = await store.list_tasks(user_id="bob")

    alice_ids = {task.task_id for task in alice_all}
    assert alice_ids == {alice_s1.task_id, alice_s2.task_id}
    assert [task.task_id for task in alice_s1_only] == [alice_s1.task_id]
    assert [task.task_id for task in bob_all] == [bob_s1.task_id]


@pytest.mark.asyncio
async def test_list_tasks_filters_by_status(store: BackgroundTaskStore) -> None:
    pending = BackgroundTask.new(_make_spec(origin_turn_id="t-pending"))
    running = BackgroundTask.new(_make_spec(origin_turn_id="t-running"))
    succeeded = BackgroundTask.new(_make_spec(origin_turn_id="t-ok"))
    running.status = BackgroundTaskStatus.RUNNING
    succeeded.status = BackgroundTaskStatus.SUCCEEDED
    for task in (pending, running, succeeded):
        await store.create_task(task)

    active = await store.list_tasks(
        statuses=[BackgroundTaskStatus.PENDING, BackgroundTaskStatus.RUNNING]
    )

    assert {task.task_id for task in active} == {pending.task_id, running.task_id}


@pytest.mark.asyncio
async def test_list_pending_returns_fifo_order(store: BackgroundTaskStore) -> None:
    first = BackgroundTask.new(_make_spec(origin_turn_id="t-a"))
    second = BackgroundTask.new(_make_spec(origin_turn_id="t-b"))
    third = BackgroundTask.new(_make_spec(origin_turn_id="t-c"))
    # Force deterministic created_at ordering (BackgroundTask.new stamps time()
    # but the resolution may be too coarse on fast runs).
    first.created_at = 10.0
    second.created_at = 20.0
    third.created_at = 30.0
    for task in (third, first, second):  # insert out of order on purpose
        await store.create_task(task)

    pending = await store.list_pending()

    assert [task.task_id for task in pending] == [
        first.task_id,
        second.task_id,
        third.task_id,
    ]


@pytest.mark.asyncio
async def test_list_pending_excludes_non_pending_tasks(
    store: BackgroundTaskStore,
) -> None:
    running = BackgroundTask.new(_make_spec())
    running.status = BackgroundTaskStatus.RUNNING
    await store.create_task(running)

    assert await store.list_pending() == []


# ----------------------------------------------------------------------
# Restart recovery (decision 5: mark stale running → failed)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recover_stale_running_marks_running_and_cancelling_as_failed(
    store: BackgroundTaskStore,
) -> None:
    running = BackgroundTask.new(_make_spec(origin_turn_id="t-running"))
    running.status = BackgroundTaskStatus.RUNNING
    running.started_at = 100.0
    cancelling = BackgroundTask.new(_make_spec(origin_turn_id="t-cancelling"))
    cancelling.status = BackgroundTaskStatus.CANCELLING
    cancelling.started_at = 100.0
    pending = BackgroundTask.new(_make_spec(origin_turn_id="t-pending"))
    succeeded = BackgroundTask.new(_make_spec(origin_turn_id="t-ok"))
    succeeded.status = BackgroundTaskStatus.SUCCEEDED
    for task in (running, cancelling, pending, succeeded):
        await store.create_task(task)

    recovered = await store.recover_stale_running()

    recovered_ids = {task.task_id for task in recovered}
    assert recovered_ids == {running.task_id, cancelling.task_id}

    for task in recovered:
        assert task.status is BackgroundTaskStatus.FAILED
        assert task.error == "backend_restart"
        assert task.finished_at is not None

    fetched_pending = await store.get_task(pending.task_id)
    fetched_succeeded = await store.get_task(succeeded.task_id)
    assert fetched_pending is not None and fetched_pending.status is BackgroundTaskStatus.PENDING
    assert fetched_succeeded is not None and fetched_succeeded.status is BackgroundTaskStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_recover_stale_running_is_idempotent(store: BackgroundTaskStore) -> None:
    running = BackgroundTask.new(_make_spec())
    running.status = BackgroundTaskStatus.RUNNING
    await store.create_task(running)

    first = await store.recover_stale_running()
    second = await store.recover_stale_running()

    assert len(first) == 1
    assert second == []


# ----------------------------------------------------------------------
# Event log (append-only, creation order)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_event_and_list_events_preserves_insertion_order(
    store: BackgroundTaskStore,
) -> None:
    task = BackgroundTask.new(_make_spec())
    await store.create_task(task)
    events = [
        BackgroundTaskEvent.transition(
            task_id=task.task_id,
            attempt_index=0,
            from_status=None,
            to_status=BackgroundTaskStatus.PENDING,
            message="enqueued",
        ),
        BackgroundTaskEvent.transition(
            task_id=task.task_id,
            attempt_index=0,
            from_status=BackgroundTaskStatus.PENDING,
            to_status=BackgroundTaskStatus.RUNNING,
            message="slot acquired",
        ),
        BackgroundTaskEvent.progress(
            task_id=task.task_id,
            attempt_index=0,
            message="tool_call:web_search",
            payload={"query": "transformer distillation"},
        ),
    ]
    # Stamp creation times in ascending order to be robust against clock
    # resolution on fast runs.
    for index, event in enumerate(events):
        event.created_at = 10.0 + index
        await store.append_event(event)

    fetched = await store.list_events(task.task_id)

    assert [event.event_id for event in fetched] == [event.event_id for event in events]
    assert fetched[2].event_type == "progress"
    assert fetched[2].payload == {"query": "transformer distillation"}
    assert fetched[0].to_status is BackgroundTaskStatus.PENDING
    assert fetched[1].from_status is BackgroundTaskStatus.PENDING
    assert fetched[1].to_status is BackgroundTaskStatus.RUNNING


@pytest.mark.asyncio
async def test_list_events_scopes_to_single_task(store: BackgroundTaskStore) -> None:
    task_a = BackgroundTask.new(_make_spec(origin_turn_id="t-a"))
    task_b = BackgroundTask.new(_make_spec(origin_turn_id="t-b"))
    await store.create_task(task_a)
    await store.create_task(task_b)
    await store.append_event(
        BackgroundTaskEvent.transition(
            task_id=task_a.task_id,
            attempt_index=0,
            from_status=None,
            to_status=BackgroundTaskStatus.PENDING,
        )
    )
    await store.append_event(
        BackgroundTaskEvent.transition(
            task_id=task_b.task_id,
            attempt_index=0,
            from_status=None,
            to_status=BackgroundTaskStatus.PENDING,
        )
    )

    events_a = await store.list_events(task_a.task_id)
    events_b = await store.list_events(task_b.task_id)

    assert len(events_a) == 1
    assert len(events_b) == 1
    assert events_a[0].task_id == task_a.task_id
    assert events_b[0].task_id == task_b.task_id


# ----------------------------------------------------------------------
# Retention GC
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_expired_removes_old_terminal_tasks_and_events(
    store: BackgroundTaskStore,
) -> None:
    old_success = BackgroundTask.new(_make_spec(origin_turn_id="t-old"))
    old_success.status = BackgroundTaskStatus.SUCCEEDED
    old_success.finished_at = 100.0
    old_success.updated_at = 100.0
    await store.create_task(old_success)
    await store.append_event(
        BackgroundTaskEvent.transition(
            task_id=old_success.task_id,
            attempt_index=0,
            from_status=BackgroundTaskStatus.RUNNING,
            to_status=BackgroundTaskStatus.SUCCEEDED,
        )
    )

    recent_success = BackgroundTask.new(_make_spec(origin_turn_id="t-recent"))
    recent_success.status = BackgroundTaskStatus.SUCCEEDED
    recent_success.finished_at = 10_000.0
    recent_success.updated_at = 10_000.0
    await store.create_task(recent_success)

    # now = 10_500, retention = 1000s  => cutoff = 9_500 => only the
    # 100.0 row is expired. recent_success (10_000) is preserved.
    deleted = await store.purge_expired(retention_seconds=1000.0, now=10_500.0)
    assert deleted == 1

    assert await store.get_task(old_success.task_id) is None
    assert await store.get_task(recent_success.task_id) is not None
    assert await store.list_events(old_success.task_id) == []


@pytest.mark.asyncio
async def test_purge_expired_never_touches_active_tasks(
    store: BackgroundTaskStore,
) -> None:
    running = BackgroundTask.new(_make_spec(origin_turn_id="t-run"))
    running.status = BackgroundTaskStatus.RUNNING
    running.updated_at = 0.0
    await store.create_task(running)

    pending = BackgroundTask.new(_make_spec(origin_turn_id="t-pend"))
    pending.status = BackgroundTaskStatus.PENDING
    pending.updated_at = 0.0
    await store.create_task(pending)

    deleted = await store.purge_expired(retention_seconds=1.0, now=10_000.0)

    assert deleted == 0
    assert await store.get_task(running.task_id) is not None
    assert await store.get_task(pending.task_id) is not None


@pytest.mark.asyncio
async def test_purge_expired_noop_when_retention_zero(
    store: BackgroundTaskStore,
) -> None:
    finished = BackgroundTask.new(_make_spec(origin_turn_id="t-zero"))
    finished.status = BackgroundTaskStatus.FAILED
    finished.finished_at = 1.0
    finished.updated_at = 1.0
    await store.create_task(finished)

    deleted = await store.purge_expired(retention_seconds=0.0, now=10_000.0)

    assert deleted == 0
    assert await store.get_task(finished.task_id) is not None
