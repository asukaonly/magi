from __future__ import annotations

import sqlite3

import pytest

from magi.control.run_plan import RunPlanError, RunPlanVersionConflict, TodoStatus
from magi.control.session_store import ControlSessionStore
from magi.core.container import get_container
from magi.db.migrations.runtime_trace.versions.v3_run_plans import SCHEMA_SQL


@pytest.mark.asyncio
async def test_run_plan_mutations_are_versioned_and_runtime_assigns_ids() -> None:
    store = ControlSessionStore()
    await store.initialize()

    created = await store.mutate_run_plan(
        "session-1",
        run_id="run-1",
        plan_id=None,
        expected_version=0,
        required=True,
        item_mutations=[{"content": "Inspect the failure", "status": "in_progress"}],
    )

    assert created.version == 1
    assert created.required is True
    assert created.items[0].id
    assert created.items[0].status is TodoStatus.IN_PROGRESS

    with pytest.raises(RunPlanVersionConflict, match="stale plan version"):
        await store.mutate_run_plan(
            "session-1",
            run_id="run-1",
            plan_id=created.plan_id,
            expected_version=0,
            item_mutations=[],
        )

    updated = await store.mutate_run_plan(
        "session-1",
        run_id="run-1",
        plan_id=created.plan_id,
        expected_version=1,
        item_mutations=[
            {
                "id": created.items[0].id,
                "status": "completed",
                "evidence_refs": ["evidence-1"],
            }
        ],
    )

    assert updated.version == 2
    assert updated.status.value == "completed"
    assert updated.items[0].evidence_refs == ("evidence-1",)


@pytest.mark.asyncio
async def test_run_plan_rejects_invalid_terminal_state() -> None:
    store = ControlSessionStore()
    await store.initialize()

    with pytest.raises(RunPlanError, match="evidence_ref"):
        await store.mutate_run_plan(
            "session-1",
            run_id="run-1",
            plan_id=None,
            expected_version=0,
            required=True,
            item_mutations=[{"content": "Claim success", "status": "completed"}],
        )

    with pytest.raises(RunPlanError, match="only one todo"):
        await store.mutate_run_plan(
            "session-1",
            run_id="run-1",
            plan_id=None,
            expected_version=0,
            item_mutations=[
                {"content": "One", "status": "in_progress"},
                {"content": "Two", "status": "in_progress"},
            ],
        )


@pytest.mark.asyncio
async def test_run_plan_rehydrates_after_restart(tmp_path) -> None:
    db_path = tmp_path / "runtime_trace.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA_SQL)

    first = ControlSessionStore(db_path=db_path)
    await first.initialize()
    created = await first.mutate_run_plan(
        "session-1",
        run_id="run-1",
        plan_id=None,
        expected_version=0,
        required=True,
        item_mutations=[{"content": "Persist me"}],
    )
    await first.shutdown()

    second = ControlSessionStore(db_path=db_path)
    await second.initialize()

    restored = second.current_run_plan("session-1", run_id="run-1")
    assert restored is not None
    assert restored.plan_id == created.plan_id
    assert restored.version == 1
    assert restored.items[0].content == "Persist me"


@pytest.mark.asyncio
async def test_full_clear_removes_durable_run_plans(tmp_path) -> None:
    db_path = tmp_path / "runtime_trace.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA_SQL)
    store = ControlSessionStore(db_path=db_path)
    await store.initialize()
    await store.mutate_run_plan(
        "session-1",
        run_id="run-1",
        plan_id=None,
        expected_version=0,
        item_mutations=[{"content": "Delete me"}],
    )

    async with store.user_content_clear_boundary():
        assert store.current_run_plan("session-1") is None

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM run_plans").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_run_cancel_marks_owned_plan_and_items_cancelled() -> None:
    from magi.chat.task_agent.session_control import _cancel_owned_run_plan

    store = ControlSessionStore()
    await store.initialize()
    created = await store.mutate_run_plan(
        "session-1",
        run_id="run-1",
        plan_id=None,
        expected_version=0,
        required=True,
        item_mutations=[{"content": "Still running", "status": "in_progress"}],
    )
    provider = get_container().control_session_store
    provider.override(store)
    try:
        await _cancel_owned_run_plan(
            session_id="session-1",
            run_id="run-1",
            user_id="user-1",
            turn_id="turn-1",
        )
    finally:
        provider.reset_override()

    cancelled = store.current_run_plan("session-1", run_id="run-1")
    assert cancelled is not None
    assert cancelled.version == created.version + 1
    assert cancelled.status.value == "cancelled"
    assert cancelled.items[0].status is TodoStatus.CANCELLED
