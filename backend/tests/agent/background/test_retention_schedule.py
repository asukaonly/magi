from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from magi.config.models import AppConfig
from magi.scheduler.contracts import ScheduledTargetType


def test_scheduled_target_type_includes_background_task_retention() -> None:
    assert ScheduledTargetType.BACKGROUND_TASK_RETENTION == "background_task_retention"
    assert (
        ScheduledTargetType("background_task_retention")
        is ScheduledTargetType.BACKGROUND_TASK_RETENTION
    )


@pytest.mark.asyncio
async def test_background_task_retention_contrib_registers_handler_and_schedule() -> None:
    from magi.agent.background.retention import (
        BACKGROUND_TASK_RETENTION_INTERVAL_SECONDS,
        BackgroundTaskRetentionScheduleContrib,
        SCHEDULE_ID_BACKGROUND_TASK_RETENTION,
        TARGET_KEY_BACKGROUND_TASK_RETENTION,
    )

    registered_handlers: dict[ScheduledTargetType, Any] = {}
    scheduled_intervals: list[dict[str, Any]] = []

    class FakeScheduler:
        def register_handler(self, target_type: ScheduledTargetType, handler: Any) -> None:
            registered_handlers[target_type] = handler

        async def schedule_interval(self, **kwargs: Any) -> None:
            scheduled_intervals.append(dict(kwargs))

    contrib = BackgroundTaskRetentionScheduleContrib(
        store=SimpleNamespace(purge_expired=AsyncMock()),
        get_config_func=AppConfig,
    )

    await contrib.register_schedules(FakeScheduler())  # type: ignore[arg-type]

    assert ScheduledTargetType.BACKGROUND_TASK_RETENTION in registered_handlers
    assert scheduled_intervals == [
        {
            "schedule_id": SCHEDULE_ID_BACKGROUND_TASK_RETENTION,
            "target_type": ScheduledTargetType.BACKGROUND_TASK_RETENTION,
            "target_key": TARGET_KEY_BACKGROUND_TASK_RETENTION,
            "seconds": BACKGROUND_TASK_RETENTION_INTERVAL_SECONDS,
            "target_payload": {},
        }
    ]


@pytest.mark.asyncio
async def test_background_task_retention_handler_purges_terminal_history() -> None:
    from magi.agent.background.retention import BackgroundTaskRetentionScheduleContrib

    config = AppConfig()
    config.agent.background_tasks.history_retention_days = 11
    store = SimpleNamespace(purge_expired=AsyncMock(return_value=5))
    contrib = BackgroundTaskRetentionScheduleContrib(
        store=store,
        get_config_func=lambda: config,
    )
    context = SimpleNamespace(triggered_at=1234.0)

    result = await contrib.handle(context)  # type: ignore[arg-type]

    assert result.success is True
    assert result.message == "background_task_retention_ok"
    assert result.stats == {"background_tasks_deleted": 5}
    store.purge_expired.assert_awaited_once_with(
        retention_seconds=11 * 86_400.0,
        now=1234.0,
    )
