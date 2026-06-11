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
    l4 = mock_cfg.return_value.agent.memory.l4
    l4.maintenance_enabled = enabled
    l4.breaker_open_timeout_seconds = 600
    l4.breaker_halfopen_idle_seconds = 1800
    l4.inactive_skill_retention_days = 30
    l4.inactive_skill_min_attempts = 5
    l4.strategy_extraction_threshold = 5
    return l4


@pytest.mark.asyncio
async def test_handler_skips_when_disabled(tmp_db):
    with patch("magi.memory.l4.maintenance_schedule.get_config") as mock_cfg:
        _apply_cfg(mock_cfg, enabled=False)
        result = await handle_l4_maintenance(_ctx())
    assert result.success is True
    assert "disabled" in result.message


@pytest.mark.asyncio
async def test_decay_open_breaker_to_halfopen_after_timeout(tmp_db):
    now = time.time()
    await _seed_skill(tmp_db, "sk-1", "open-old", breaker_state="open", breaker_opened_at=now - 700)
    await _seed_skill(tmp_db, "sk-2", "open-new", breaker_state="open", breaker_opened_at=now - 60)

    fake_unified = MagicMock()
    fake_unified.l4 = MagicMock(db_path=tmp_db)

    with patch("magi.memory.l4.maintenance_schedule.get_config") as mock_cfg, patch(
        "magi.memory.l4.maintenance_schedule.get_unified_memory", return_value=fake_unified
    ):
        _apply_cfg(mock_cfg)
        result = await handle_l4_maintenance(_ctx())

    assert result.success is True
    conn = sqlite3.connect(tmp_db)
    rows = dict(
        conn.execute("SELECT skill_name, circuit_breaker_state FROM procedural_skills").fetchall()
    )
    conn.close()
    assert rows["open-old"] == "half_open"
    assert rows["open-new"] == "open"


@pytest.mark.asyncio
async def test_close_halfopen_when_idle(tmp_db):
    now = time.time()
    await _seed_skill(
        tmp_db,
        "sk-1",
        "halfopen-idle",
        breaker_state="half_open",
        breaker_opened_at=now - 4000,
        last_used_at=now - 4000,
    )

    fake_unified = MagicMock()
    fake_unified.l4 = MagicMock(db_path=tmp_db)

    with patch("magi.memory.l4.maintenance_schedule.get_config") as mock_cfg, patch(
        "magi.memory.l4.maintenance_schedule.get_unified_memory", return_value=fake_unified
    ):
        _apply_cfg(mock_cfg)
        result = await handle_l4_maintenance(_ctx())

    assert result.success is True
    conn = sqlite3.connect(tmp_db)
    state = conn.execute("SELECT circuit_breaker_state FROM procedural_skills").fetchone()[0]
    conn.close()
    assert state == "closed"


@pytest.mark.asyncio
async def test_soft_delete_inactive_skills(tmp_db):
    now = time.time()
    age_old = now - (40 * 86400)
    age_recent = now - (5 * 86400)
    await _seed_skill(tmp_db, "sk-old", "old-low", total_attempts=2, last_used_at=age_old)
    await _seed_skill(tmp_db, "sk-active", "active", total_attempts=50, last_used_at=age_old)
    await _seed_skill(tmp_db, "sk-recent", "recent", total_attempts=2, last_used_at=age_recent)

    fake_unified = MagicMock()
    fake_unified.l4 = MagicMock(db_path=tmp_db)

    with patch("magi.memory.l4.maintenance_schedule.get_config") as mock_cfg, patch(
        "magi.memory.l4.maintenance_schedule.get_unified_memory", return_value=fake_unified
    ):
        _apply_cfg(mock_cfg)
        result = await handle_l4_maintenance(_ctx())

    assert result.success is True
    conn = sqlite3.connect(tmp_db)
    rows = {
        name: deleted_at
        for name, deleted_at in conn.execute(
            "SELECT skill_name, deleted_at FROM procedural_skills"
        ).fetchall()
    }
    conn.close()
    assert rows["old-low"] is not None
    assert rows["active"] is None
    assert rows["recent"] is None


@pytest.mark.asyncio
async def test_pending_trace_health_warns(tmp_db):
    await _seed_skill(tmp_db, "sk-stuck", "stuck", pending_trace_count=20)

    fake_unified = MagicMock()
    fake_unified.l4 = MagicMock(db_path=tmp_db)

    with patch("magi.memory.l4.maintenance_schedule.get_config") as mock_cfg, patch(
        "magi.memory.l4.maintenance_schedule.get_unified_memory", return_value=fake_unified
    ):
        _apply_cfg(mock_cfg)
        result = await handle_l4_maintenance(_ctx())

    assert result.success is True
    assert result.stats.get("pending_warnings") == 1


@pytest.mark.asyncio
async def test_register_schedules(tmp_db):
    scheduler = MagicMock()
    scheduler.register_handler = MagicMock()
    scheduler.schedule_interval = AsyncMock()
    scheduler.unschedule = AsyncMock()

    contrib = L4MaintenanceScheduleContrib()

    with patch("magi.memory.l4.maintenance_schedule.get_config") as mock_cfg:
        _apply_cfg(mock_cfg)
        await contrib.register_schedules(scheduler)

    scheduler.register_handler.assert_called_once()
    scheduler.schedule_interval.assert_awaited_once()
    args = scheduler.schedule_interval.await_args.kwargs
    assert args["target_type"] == ScheduledTargetType.MEMORY_L4_MAINTENANCE


@pytest.mark.asyncio
async def test_register_schedules_disabled_unschedules(tmp_db):
    scheduler = MagicMock()
    scheduler.register_handler = MagicMock()
    scheduler.schedule_interval = AsyncMock()
    scheduler.unschedule = AsyncMock()

    contrib = L4MaintenanceScheduleContrib()
    with patch("magi.memory.l4.maintenance_schedule.get_config") as mock_cfg:
        _apply_cfg(mock_cfg, enabled=False)
        await contrib.register_schedules(scheduler)

    scheduler.unschedule.assert_awaited_once()
    scheduler.schedule_interval.assert_not_awaited()
