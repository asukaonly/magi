from __future__ import annotations

import time
from importlib import import_module
from pathlib import Path

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.scheduler.contracts import ScheduledExecutionResult, ScheduledTargetType
from magi.scheduler.repository import ScheduleRepository


scheduler_initial = import_module("magi.db.migrations.scheduler.versions.0001_initial")


async def _make_repo(tmp_path: Path) -> tuple[ScheduleRepository, Path]:
    db_path = tmp_path / "scheduler.db"
    async with sqlite_connection_async(db_path) as db:
        await db.executescript(scheduler_initial.SCHEMA_SQL)
    return ScheduleRepository(db_path), db_path


@pytest.mark.asyncio
async def test_list_executions_filtered_by_window(tmp_path: Path) -> None:
    repo, _ = await _make_repo(tmp_path)
    now = time.time()

    eid1 = await repo.create_execution_record(
        schedule_id="s1",
        target_type=ScheduledTargetType.USER_AGENT_TASK,
        target_key="s1",
        manual=False,
        started_at=now - 3600,
    )
    await repo.complete_execution_success(
        eid1,
        result=ScheduledExecutionResult(success=True, message="ok"),
        scheduler_job_id=None,
        finished_at=now - 3500,
    )

    eid2 = await repo.create_execution_record(
        schedule_id="s2",
        target_type=ScheduledTargetType.MEMORY_L3_SUMMARY,
        target_key="s2",
        manual=False,
        started_at=now - 10,
    )
    await repo.complete_execution_failure(
        eid2,
        error="boom",
        scheduler_job_id=None,
        finished_at=now - 5,
    )

    # Window of 5 minutes should only see eid2
    rows = await repo.list_executions_filtered(
        since=now - 300, until=now + 1, limit=100,
    )
    ids = [row["execution_id"] for row in rows]
    assert ids == [eid2]

    # Filter by target_type
    rows = await repo.list_executions_filtered(
        since=now - 86400, target_types=["user_agent_task"], limit=100,
    )
    assert [row["execution_id"] for row in rows] == [eid1]

    # Filter by status (raw repo-status values: 'success' / 'failed')
    rows = await repo.list_executions_filtered(
        since=now - 86400, statuses=["failed"], limit=100,
    )
    assert [row["execution_id"] for row in rows] == [eid2]

    rows = await repo.list_executions_filtered(
        since=now - 86400, statuses=["success"], limit=100,
    )
    assert [row["execution_id"] for row in rows] == [eid1]
