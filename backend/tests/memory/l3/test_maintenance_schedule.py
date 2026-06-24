"""Tests for the independent L3 maintenance schedule."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.config.memory_models import MemoryHistoryBehavior
from magi.scheduler.contracts import ScheduledTargetType


def _build_config(
    *,
    l3_enabled: bool = True,
    maintenance_enabled: bool = True,
    interval_seconds: float = 86_400.0,
    retention_days: int = 90,
    l3_retention_days: int = 180,
    history_behavior: MemoryHistoryBehavior = MemoryHistoryBehavior.ARCHIVE,
) -> Any:
    l3_cfg = SimpleNamespace(
        enabled=l3_enabled,
        retention_days=l3_retention_days,
        maintenance_enabled=maintenance_enabled,
        maintenance_interval_seconds=interval_seconds,
    )
    memory_cfg = SimpleNamespace(
        retention_days=retention_days,
        history_behavior=history_behavior,
        l3=l3_cfg,
    )
    return SimpleNamespace(agent=SimpleNamespace(memory=memory_cfg))


def test_scheduled_target_type_includes_memory_l3_maintenance() -> None:
    assert ScheduledTargetType.MEMORY_L3_MAINTENANCE == "memory_l3_maintenance"
    assert (
        ScheduledTargetType("memory_l3_maintenance")
        is ScheduledTargetType.MEMORY_L3_MAINTENANCE
    )


@pytest.mark.asyncio
async def test_l3_maintenance_contrib_registers_handler_and_schedule() -> None:
    from magi.memory.l3.maintenance_schedule import (
        L3MaintenanceScheduleContrib,
        SCHEDULE_ID_L3_MAINTENANCE,
        TARGET_KEY_L3_MAINTENANCE,
        handle_l3_maintenance,
    )

    registered_handlers: dict[ScheduledTargetType, Any] = {}
    scheduled_intervals: list[dict[str, Any]] = []

    class FakeScheduler:
        def register_handler(self, target_type: ScheduledTargetType, handler: Any) -> None:
            registered_handlers[target_type] = handler

        async def schedule_interval(self, **kwargs: Any) -> None:
            scheduled_intervals.append(dict(kwargs))

        async def unschedule(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("register_schedules should not unschedule")

    with patch(
        "magi.memory.l3.maintenance_schedule.get_config",
        return_value=_build_config(interval_seconds=55_555.0),
    ):
        await L3MaintenanceScheduleContrib().register_schedules(FakeScheduler())  # type: ignore[arg-type]

    assert registered_handlers[ScheduledTargetType.MEMORY_L3_MAINTENANCE] is handle_l3_maintenance
    assert scheduled_intervals == [
        {
            "schedule_id": SCHEDULE_ID_L3_MAINTENANCE,
            "target_type": ScheduledTargetType.MEMORY_L3_MAINTENANCE,
            "target_key": TARGET_KEY_L3_MAINTENANCE,
            "seconds": 55_555.0,
            "target_payload": {},
        }
    ]


@pytest.mark.asyncio
async def test_handle_l3_maintenance_runs_l3_cleanup_with_l3_retention() -> None:
    from magi.memory.l3.maintenance_schedule import handle_l3_maintenance

    unified = MagicMock()
    unified.l3 = MagicMock()
    unified.cleanup_l3_data = AsyncMock(
        return_value={
            "archived_summaries": 4,
            "deleted_summaries": 5,
        }
    )

    with (
        patch(
            "magi.memory.l3.maintenance_schedule.get_config",
            return_value=_build_config(retention_days=21, l3_retention_days=180),
        ),
        patch("magi.memory.l3.maintenance_schedule.get_unified_memory", return_value=unified),
    ):
        result = await handle_l3_maintenance(MagicMock())

    assert result.success is True
    assert result.message == "l3_maintenance_ok"
    assert result.stats == {
        "archived_summaries": 4,
        "deleted_summaries": 5,
    }
    unified.cleanup_l3_data.assert_awaited_once_with(
        older_than_days=180,
        history_behavior="archive",
    )


@pytest.mark.asyncio
async def test_handle_l3_maintenance_skips_when_disabled() -> None:
    from magi.memory.l3.maintenance_schedule import handle_l3_maintenance

    with patch(
        "magi.memory.l3.maintenance_schedule.get_config",
        return_value=_build_config(maintenance_enabled=False),
    ):
        result = await handle_l3_maintenance(MagicMock())

    assert result.success is True
    assert result.message == "l3_maintenance_disabled_skip"
