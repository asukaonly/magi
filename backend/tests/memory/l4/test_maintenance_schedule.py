from __future__ import annotations

import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l4.maintenance_schedule import (
    L4MaintenanceScheduleContrib,
    handle_l4_maintenance,
)
from magi.memory.l4.storage.schema import ensure_procedural_memory_schema
from magi.scheduler.contracts import (
    ScheduleDefinition,
    ScheduledExecutionContext,
    ScheduledTargetState,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)


@pytest.fixture
async def tmp_db(ensure_memory_schema):
    tmp = tempfile.TemporaryDirectory()
    db_path = str(Path(tmp.name) / "l4.db")
    # ensure_procedural_memory_schema is an alembic-managed no-op now; the
    # memory_shared chain owns the procedural_skills schema.
    ensure_memory_schema("memory_shared", db_path)
    async with sqlite_connection_async(db_path) as db:
        await ensure_procedural_memory_schema(db)
        await db.commit()
    yield db_path
    tmp.cleanup()


async def _seed_skill(
    db_path,
    skill_id,
    name,
    *,
    breaker_state="closed",
    breaker_opened_at=None,
    last_used_at=None,
    total_attempts=1,
    pending_trace_count=0,
    deleted_at=None,
):
    async with sqlite_connection_async(db_path) as db:
        await db.execute(
            """
            INSERT INTO procedural_skills(
                skill_id, skill_name, skill_category, skill_type,
                created_at, updated_at, last_used_at,
                circuit_breaker_state, circuit_breaker_opened_at,
                total_attempts, success_count, failure_count,
                pending_trace_count, deleted_at, source_event_ids
            ) VALUES (?, ?, 'tool', 'external_tool', 1.0, 1.0, ?,
                      ?, ?, ?, 0, 0, ?, ?, '[]')
            """,
            (
                skill_id,
                name,
                last_used_at,
                breaker_state,
                breaker_opened_at,
                total_attempts,
                pending_trace_count,
                deleted_at,
            ),
        )
        await db.commit()


def _ctx():
    schedule = ScheduleDefinition(
        schedule_id="x",
        target_type=ScheduledTargetType.MEMORY_L4_MAINTENANCE,
        target_key="x",
        trigger=TriggerDefinition(trigger_type=TriggerType.INTERVAL, config={"seconds": 300.0}),
        target_payload={},
    )
    return ScheduledExecutionContext(
        schedule=schedule,
        target_state=ScheduledTargetState(
            target_type=ScheduledTargetType.MEMORY_L4_MAINTENANCE,
            target_key="x",
        ),
        runtime_dir=Path("."),
        triggered_at=time.time(),
    )


def _apply_cfg(mock_cfg, *, enabled=True):
    from magi.config.memory_models import MemoryL4Settings

    l4 = MemoryL4Settings(maintenance_enabled=enabled)
    mock_cfg.return_value.agent.memory.l4 = l4
    return l4


@pytest.mark.asyncio
async def test_disabled_maintenance_never_resolves_memory_or_opens_database():
    with patch("magi.memory.l4.maintenance_schedule.get_config") as config, patch(
        "magi.memory.l4.maintenance_schedule.get_unified_memory"
    ) as memory, patch("magi.memory.l4.maintenance_schedule.sqlite_connection_async") as connect:
        _apply_cfg(config, enabled=False)
        result = await handle_l4_maintenance(_ctx())
    assert result.success is True
    assert result.message == "l4_maintenance_disabled_skip"
    assert result.stats == {}
    memory.assert_not_called()
    connect.assert_not_called()


@pytest.mark.asyncio
async def test_default_breaker_timeout_changes_only_due_persisted_skills(tmp_db, monkeypatch):
    from types import SimpleNamespace

    now = 1700000000.0
    monkeypatch.setattr(
        "magi.memory.l4.maintenance_schedule.time", SimpleNamespace(time=lambda: now)
    )
    for name, age in [("past-deadline", 601), ("at-deadline", 600), ("recent", 599)]:
        await _seed_skill(tmp_db, name, name, breaker_state="open", breaker_opened_at=now - age)
    unified = MagicMock()
    unified.l4 = MagicMock(db_path=tmp_db)
    with patch("magi.memory.l4.maintenance_schedule.get_config") as cfg, patch(
        "magi.memory.l4.maintenance_schedule.get_unified_memory", return_value=unified
    ):
        _apply_cfg(cfg)
        result = await handle_l4_maintenance(_ctx())
    assert result.success
    assert result.stats["breakers_decayed_to_halfopen"] == 2
    with sqlite3.connect(tmp_db) as connection:
        assert dict(
            connection.execute("SELECT skill_id,circuit_breaker_state FROM procedural_skills")
        ) == {"past-deadline": "half_open", "at-deadline": "half_open", "recent": "open"}


@pytest.mark.asyncio
async def test_maintenance_uses_idle_deadline_and_reports_only_active_trace_warnings(
    tmp_db, monkeypatch
):
    from types import SimpleNamespace

    now = 1700000000.0
    monkeypatch.setattr(
        "magi.memory.l4.maintenance_schedule.time", SimpleNamespace(time=lambda: now)
    )
    for name, idle_seconds, pending in [
        ("past-deadline", 1801, 9),
        ("at-deadline", 1800, 10),
        ("recently-used", 1799, 11),
    ]:
        await _seed_skill(
            tmp_db,
            name,
            name,
            breaker_state="half_open",
            breaker_opened_at=now - 4000,
            last_used_at=now - idle_seconds,
            pending_trace_count=pending,
        )
    await _seed_skill(
        tmp_db,
        "deleted",
        "deleted",
        breaker_state="half_open",
        breaker_opened_at=now - 4000,
        last_used_at=now - 4000,
        pending_trace_count=30,
        deleted_at=now - 100,
    )
    unified = MagicMock()
    unified.l4 = MagicMock(db_path=tmp_db)
    with patch("magi.memory.l4.maintenance_schedule.get_config") as config, patch(
        "magi.memory.l4.maintenance_schedule.get_unified_memory", return_value=unified
    ):
        _apply_cfg(config)
        result = await handle_l4_maintenance(_ctx())
    assert result.success is True
    assert result.stats == {
        "breakers_decayed_to_halfopen": 0,
        "breakers_closed_from_halfopen": 2,
        "skills_soft_deleted": 0,
        "pending_warnings": 1,
    }
    with sqlite3.connect(tmp_db) as db:
        rows = {
            name: (state, opened)
            for name, state, opened in db.execute(
                "SELECT skill_name, circuit_breaker_state, circuit_breaker_opened_at FROM procedural_skills"
            )
        }
    assert rows == {
        "past-deadline": ("closed", None),
        "at-deadline": ("closed", None),
        "recently-used": ("half_open", now - 4000),
        "deleted": ("half_open", now - 4000),
    }


@pytest.mark.asyncio
async def test_default_retention_requires_both_old_age_and_low_activity(tmp_db, monkeypatch):
    from types import SimpleNamespace

    now = 1700000000.0
    monkeypatch.setattr(
        "magi.memory.l4.maintenance_schedule.time", SimpleNamespace(time=lambda: now)
    )
    cutoff = 30 * 86400
    for name, age, attempts in [
        ("past-deadline", cutoff + 1, 4),
        ("at-deadline", cutoff, 4),
        ("recent", cutoff - 1, 4),
        ("enough-activity", cutoff + 1, 5),
    ]:
        await _seed_skill(tmp_db, name, name, total_attempts=attempts, last_used_at=now - age)
    unified = MagicMock()
    unified.l4 = MagicMock(db_path=tmp_db)
    with patch("magi.memory.l4.maintenance_schedule.get_config") as cfg, patch(
        "magi.memory.l4.maintenance_schedule.get_unified_memory", return_value=unified
    ):
        _apply_cfg(cfg)
        result = await handle_l4_maintenance(_ctx())
    assert result.success
    assert result.stats["skills_soft_deleted"] == 2
    with sqlite3.connect(tmp_db) as connection:
        assert dict(connection.execute("SELECT skill_id,deleted_at FROM procedural_skills")) == {
            "past-deadline": now,
            "at-deadline": now,
            "recent": None,
            "enough-activity": None,
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_maintenance_registration_owns_exact_handler_schedule_and_interval(enabled):
    scheduler = MagicMock(schedule_interval=AsyncMock(), unschedule=AsyncMock())
    with patch("magi.memory.l4.maintenance_schedule.get_config") as config:
        _apply_cfg(config, enabled=enabled)
        await L4MaintenanceScheduleContrib().register_schedules(scheduler)
    scheduler.register_handler.assert_called_once_with(
        ScheduledTargetType.MEMORY_L4_MAINTENANCE, handle_l4_maintenance
    )
    if enabled:
        scheduler.schedule_interval.assert_awaited_once_with(
            schedule_id="memory_l4_maintenance",
            target_type=ScheduledTargetType.MEMORY_L4_MAINTENANCE,
            target_key="memory_l4_maintenance",
            seconds=300.0,
            target_payload={},
        )
        scheduler.unschedule.assert_not_awaited()
    else:
        scheduler.unschedule.assert_awaited_once_with(
            "memory_l4_maintenance",
            target_type=ScheduledTargetType.MEMORY_L4_MAINTENANCE,
            target_key="memory_l4_maintenance",
        )
        scheduler.schedule_interval.assert_not_awaited()
