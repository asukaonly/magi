from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import time

import pytest

from magi.memory.l0.working_memory import L0WorkingMemoryStore
from magi.memory.l0.working import checkpoint as checkpoint_lifecycle
from magi.memory.l0.working import sessions as session_lifecycle


@pytest.mark.asyncio
async def test_idle_expiry_never_removes_active_execution_state(tmp_path) -> None:
    store = L0WorkingMemoryStore(
        checkpoint_db_path=str(tmp_path / "memory.db"),
        session_timeout_seconds=1,
    )
    await store.initialize()
    await store.start_session(session_id="session-active")
    store.upsert_execution_run_sync(
        session_id="session-active",
        run_id="run-1",
        status="running",
        revision=0,
        root_user_message="finish the active task",
    )
    store._sessions["session-active"]["last_active_at"] = time.time() - 60

    assert await store.expire_idle_sessions() == []
    assert store.get_execution_state_sync("session-active")["run"]["run_id"] == "run-1"
    await store.shutdown()


@pytest.mark.asyncio
async def test_capacity_eviction_never_removes_active_execution_state(tmp_path) -> None:
    store = L0WorkingMemoryStore(
        checkpoint_db_path=str(tmp_path / "memory.db"),
        max_concurrent_sessions=1,
    )
    await store.initialize()
    await store.start_session(session_id="session-active")
    store.upsert_execution_run_sync(
        session_id="session-active",
        run_id="run-1",
        status="running",
        revision=0,
    )

    with pytest.raises(RuntimeError, match="active execution runs"):
        await store.start_session(session_id="session-new")
    assert store.get_execution_state_sync("session-active")["run"]["run_id"] == "run-1"
    await store.shutdown()


def test_synchronous_admission_never_overflows_capacity(tmp_path) -> None:
    store = L0WorkingMemoryStore(
        checkpoint_db_path=str(tmp_path / "memory.db"),
        max_concurrent_sessions=1,
        restore_on_restart=False,
    )
    store.push_goal_sync(
        session_id="session-1",
        goal_id="goal-1",
        goal_type="task",
        description="first session",
    )

    with pytest.raises(RuntimeError, match="configured capacity"):
        store.push_goal_sync(
            session_id="session-2",
            goal_id="goal-2",
            goal_type="task",
            description="second session",
        )
    assert set(store._sessions) == {"session-1"}


@pytest.mark.asyncio
async def test_expiry_failure_keeps_live_session_state(tmp_path, monkeypatch) -> None:
    store = L0WorkingMemoryStore(
        checkpoint_db_path=str(tmp_path / "memory.db"),
        session_timeout_seconds=1,
    )
    await store.initialize()
    await store.start_session(session_id="session-1")
    store._sessions["session-1"]["last_active_at"] = time.time() - 60

    @asynccontextmanager
    async def _broken_connection(*args, **kwargs):
        raise RuntimeError("database unavailable")
        yield

    monkeypatch.setattr(
        session_lifecycle,
        "sqlite_connection_async",
        _broken_connection,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await store.expire_idle_sessions()
    assert "session-1" in store._sessions
    monkeypatch.undo()
    await store.shutdown()


@pytest.mark.asyncio
async def test_clear_failure_keeps_live_session_state(tmp_path, monkeypatch) -> None:
    store = L0WorkingMemoryStore(checkpoint_db_path=str(tmp_path / "memory.db"))
    await store.initialize()
    await store.start_session(session_id="session-1")

    @asynccontextmanager
    async def _broken_connection(*args, **kwargs):
        raise RuntimeError("database unavailable")
        yield

    monkeypatch.setattr(
        checkpoint_lifecycle,
        "sqlite_connection_async",
        _broken_connection,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await store.clear()
    assert "session-1" in store._sessions
    monkeypatch.undo()
    await store.shutdown()


@pytest.mark.asyncio
async def test_restore_discards_expired_work_but_recovers_active_execution(tmp_path) -> None:
    checkpoint_path = tmp_path / "memory.db"
    store = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        checkpoint_interval_seconds=9999,
        session_timeout_seconds=1,
    )
    await store.initialize()
    await store.start_session(session_id="session-disposable")
    store._sessions["session-disposable"]["last_active_at"] = time.time() - 60
    await store.checkpoint_session("session-disposable")

    await store.start_session(session_id="session-active")
    store.upsert_execution_run_sync(
        session_id="session-active",
        run_id="run-1",
        status="running",
        revision=0,
        root_user_message="recover me",
    )
    store._sessions["session-active"]["status"] = "expired"
    store._sessions["session-active"]["last_active_at"] = time.time() - 60
    await store.checkpoint_session("session-active")

    restored = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        checkpoint_interval_seconds=9999,
        session_timeout_seconds=1,
    )
    await restored.initialize()

    assert (await restored.get_workbench("session-disposable"))["session"] is None
    active = await restored.get_workbench("session-active")
    assert active["session"]["status"] == "active"
    assert restored.get_execution_state_sync("session-active")["run"]["run_id"] == "run-1"
    await store.shutdown()
    await restored.shutdown()


@pytest.mark.asyncio
async def test_restore_enforces_capacity_for_disposable_sessions(tmp_path) -> None:
    checkpoint_path = tmp_path / "memory.db"
    store = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        checkpoint_interval_seconds=9999,
        max_concurrent_sessions=3,
    )
    await store.initialize()
    for index in range(3):
        session = await store.start_session(session_id=f"session-{index}")
        session["last_active_at"] = time.time() + index
        await store.checkpoint_session(f"session-{index}")

    restored = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        checkpoint_interval_seconds=9999,
        max_concurrent_sessions=1,
    )
    await restored.initialize()

    assert set(restored._sessions) == {"session-2"}
    await store.shutdown()
    await restored.shutdown()


@pytest.mark.asyncio
async def test_configured_checkpoint_interval_persists_dirty_workbench(tmp_path) -> None:
    checkpoint_path = tmp_path / "memory.db"
    store = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        checkpoint_interval_seconds=1,
        session_timeout_seconds=60,
    )
    await store.initialize()
    await store.push_goal(
        session_id="session-1",
        goal_id="goal-1",
        goal_type="task",
        description="persist automatically",
        status="in_progress",
    )

    async def _wait_for_checkpoint() -> None:
        while store._sessions["session-1"]["last_checkpoint_at"] is None:
            await asyncio.sleep(0.05)

    await asyncio.wait_for(_wait_for_checkpoint(), timeout=5)

    restored = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        checkpoint_interval_seconds=9999,
        session_timeout_seconds=60,
    )
    await restored.initialize()

    assert (await restored.get_workbench("session-1"))["goal_stack"][0][
        "goal_id"
    ] == "goal-1"
    await store.shutdown()
    await restored.shutdown()


@pytest.mark.asyncio
async def test_checkpoint_repeats_when_state_changes_during_save(
    tmp_path,
    monkeypatch,
) -> None:
    checkpoint_path = tmp_path / "memory.db"
    store = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        checkpoint_interval_seconds=1,
    )
    await store.initialize()
    original_checkpoint = store.checkpoint_session
    first_checkpoint_started = asyncio.Event()
    allow_first_checkpoint = asyncio.Event()
    second_checkpoint_succeeded = asyncio.Event()
    checkpoint_count = 0

    async def _controlled_checkpoint(session_id: str) -> None:
        nonlocal checkpoint_count
        checkpoint_count += 1
        if checkpoint_count == 1:
            first_checkpoint_started.set()
            await allow_first_checkpoint.wait()
        await original_checkpoint(session_id)
        if checkpoint_count == 2:
            second_checkpoint_succeeded.set()

    monkeypatch.setattr(store, "checkpoint_session", _controlled_checkpoint)
    await store.push_goal(
        session_id="session-1",
        goal_id="goal-1",
        goal_type="task",
        description="first state",
    )
    await asyncio.wait_for(first_checkpoint_started.wait(), timeout=5)
    await store.push_goal(
        session_id="session-1",
        goal_id="goal-2",
        goal_type="task",
        description="changed during save",
    )
    allow_first_checkpoint.set()
    await asyncio.wait_for(second_checkpoint_succeeded.wait(), timeout=5)

    assert checkpoint_count == 2
    restored = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        checkpoint_interval_seconds=9999,
    )
    await restored.initialize()
    assert {
        goal["goal_id"]
        for goal in (await restored.get_workbench("session-1"))["goal_stack"]
    } == {"goal-1", "goal-2"}
    await store.shutdown()
    await restored.shutdown()


@pytest.mark.asyncio
async def test_scheduled_checkpoint_retries_after_transient_failure(
    tmp_path,
    monkeypatch,
) -> None:
    checkpoint_path = tmp_path / "memory.db"
    store = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        checkpoint_interval_seconds=1,
    )
    await store.initialize()
    original_checkpoint = store.checkpoint_session
    checkpoint_succeeded = asyncio.Event()
    checkpoint_count = 0

    async def _flaky_checkpoint(session_id: str) -> None:
        nonlocal checkpoint_count
        checkpoint_count += 1
        if checkpoint_count == 1:
            raise RuntimeError("temporary failure")
        await original_checkpoint(session_id)
        checkpoint_succeeded.set()

    monkeypatch.setattr(store, "checkpoint_session", _flaky_checkpoint)
    await store.push_goal(
        session_id="session-1",
        goal_id="goal-1",
        goal_type="task",
        description="retry persistence",
    )
    await asyncio.wait_for(checkpoint_succeeded.wait(), timeout=5)

    assert checkpoint_count == 2
    restored = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        checkpoint_interval_seconds=9999,
    )
    await restored.initialize()
    assert (await restored.get_workbench("session-1"))["goal_stack"][0][
        "goal_id"
    ] == "goal-1"
    await store.shutdown()
    await restored.shutdown()
