"""Tests for the independent L1 maintenance schedule."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.config.memory_models import MemoryHistoryBehavior, MemoryL1Settings
from magi.scheduler.contracts import ScheduledTargetType


def _build_config(
    *,
    l1_enabled: bool = True,
    maintenance_enabled: bool = True,
    interval_seconds: float = 43_200.0,
    retention_days: int = 90,
    l1_retention_days: int = 7,
    history_behavior: MemoryHistoryBehavior = MemoryHistoryBehavior.DELETE,
) -> Any:
    l1_cfg = MemoryL1Settings(
        enabled=l1_enabled,
        retention_days=l1_retention_days,
        maintenance_enabled=maintenance_enabled,
        maintenance_interval_seconds=interval_seconds,
    )
    memory_cfg = SimpleNamespace(
        retention_days=retention_days,
        history_behavior=history_behavior,
        l1=l1_cfg,
    )
    return SimpleNamespace(agent=SimpleNamespace(memory=memory_cfg))


def test_scheduled_target_type_includes_memory_l1_maintenance() -> None:
    assert ScheduledTargetType.MEMORY_L1_MAINTENANCE == "memory_l1_maintenance"
    assert ScheduledTargetType("memory_l1_maintenance") is ScheduledTargetType.MEMORY_L1_MAINTENANCE


@pytest.mark.asyncio
async def test_l1_maintenance_contrib_registers_handler_and_schedule() -> None:
    from magi.memory.l1.maintenance_schedule import (
        L1MaintenanceScheduleContrib,
        SCHEDULE_ID_L1_MAINTENANCE,
        TARGET_KEY_L1_MAINTENANCE,
        handle_l1_maintenance,
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
        "magi.memory.l1.maintenance_schedule.get_config",
        return_value=_build_config(interval_seconds=12_345.0),
    ):
        await L1MaintenanceScheduleContrib().register_schedules(FakeScheduler())  # type: ignore[arg-type]

    assert registered_handlers[ScheduledTargetType.MEMORY_L1_MAINTENANCE] is handle_l1_maintenance
    assert scheduled_intervals == [
        {
            "schedule_id": SCHEDULE_ID_L1_MAINTENANCE,
            "target_type": ScheduledTargetType.MEMORY_L1_MAINTENANCE,
            "target_key": TARGET_KEY_L1_MAINTENANCE,
            "seconds": 12_345.0,
            "target_payload": {},
        }
    ]


@pytest.mark.asyncio
async def test_handle_l1_maintenance_runs_l1_cleanup_with_l1_retention() -> None:
    from magi.memory.l1.maintenance_schedule import handle_l1_maintenance

    unified = MagicMock()
    unified.l1 = MagicMock()
    unified.l3 = MagicMock()
    unified.resume_pending_forget_operations = AsyncMock(
        return_value={"found": 0, "completed": 0, "failed": 0}
    )
    unified.cleanup_l1_data = AsyncMock(
        return_value={
            "deleted_events": 2,
            "archived_events": 1,
            "pruned_pinned_payloads": 3,
        }
    )

    with (
        patch(
            "magi.memory.l1.maintenance_schedule.get_config",
            return_value=_build_config(retention_days=90, l1_retention_days=17),
        ),
        patch("magi.memory.l1.maintenance_schedule.get_unified_memory", return_value=unified),
    ):
        result = await handle_l1_maintenance(MagicMock())

    assert result.success is True
    assert result.message == "l1_maintenance_ok"
    assert result.stats == {
        "deleted_events": 2,
        "archived_events": 1,
        "pruned_pinned_payloads": 3,
        "forget_operations_found": 0,
        "forget_operations_completed": 0,
        "forget_operations_failed": 0,
    }
    unified.cleanup_l1_data.assert_awaited_once_with(
        older_than_days=17,
        history_behavior="delete",
    )


@pytest.mark.asyncio
async def test_handle_l1_maintenance_skips_when_disabled() -> None:
    from magi.memory.l1.maintenance_schedule import handle_l1_maintenance

    unified = MagicMock()
    unified.resume_pending_forget_operations = AsyncMock(
        return_value={"found": 0, "completed": 0, "failed": 0}
    )
    with (
        patch(
            "magi.memory.l1.maintenance_schedule.get_config",
            return_value=_build_config(maintenance_enabled=False),
        ),
        patch("magi.memory.l1.maintenance_schedule.get_unified_memory", return_value=unified),
    ):
        result = await handle_l1_maintenance(MagicMock())

    assert result.success is True
    assert result.message == "l1_maintenance_disabled_skip"
