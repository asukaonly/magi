"""Tests for L3 temporal summary scheduler registration."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from magi.memory.l3 import summary_schedule
from magi.scheduler.contracts import ScheduledTargetType


class _FakeScheduler:
    def __init__(self) -> None:
        self.handlers: dict[ScheduledTargetType, Any] = {}
        self.intervals: list[dict[str, Any]] = []
        self.unscheduled: list[dict[str, Any]] = []

    def register_handler(self, target_type: ScheduledTargetType, handler: Any) -> None:
        self.handlers[target_type] = handler

    async def schedule_interval(self, **kwargs: Any) -> None:
        self.intervals.append(dict(kwargs))

    async def unschedule(self, schedule_id: str, **kwargs: Any) -> None:
        self.unscheduled.append({"schedule_id": schedule_id, **kwargs})


def _config_with_l3_enabled(enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(
        agent=SimpleNamespace(
            memory=SimpleNamespace(
                l3=SimpleNamespace(enabled=enabled),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_l3_summary_schedule_registers_month_period(monkeypatch: pytest.MonkeyPatch) -> None:
    scheduler = _FakeScheduler()
    contrib = summary_schedule.L3SummaryScheduleContrib()
    monkeypatch.setattr(summary_schedule, "get_config", lambda: _config_with_l3_enabled(True))

    async def _skip_activity_schedules(_scheduler: _FakeScheduler) -> None:
        return None

    monkeypatch.setattr(contrib, "_register_activity_schedules", _skip_activity_schedules)

    await contrib.register_schedules(scheduler)  # type: ignore[arg-type]

    assert scheduler.handlers[ScheduledTargetType.MEMORY_L3_SUMMARY] is summary_schedule.handle_l3_summary
    schedules_by_id = {item["schedule_id"]: item for item in scheduler.intervals}
    assert set(schedules_by_id) == {
        "memory-l3-summary:hour",
        "memory-l3-summary:day",
        "memory-l3-summary:week",
        "memory-l3-summary:month",
    }
    month = schedules_by_id["memory-l3-summary:month"]
    assert month["target_type"] is ScheduledTargetType.MEMORY_L3_SUMMARY
    assert month["target_key"] == summary_schedule.TARGET_KEY_L3_SUMMARY
    assert month["seconds"] == 30 * 24 * 60 * 60
    assert month["target_payload"] == {"period_type": "month"}
    assert {
        item["target_payload"]["period_type"]: item["seconds"]
        for item in scheduler.intervals
    } == {"hour": 3600, "day": 86400, "week": 604800, "month": 2592000}


@pytest.mark.asyncio
async def test_l3_summary_schedule_writes_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Schedules are always written so runtime toggling of l3.enabled takes effect.

    Disabled-state skipping is the handler's responsibility, verified separately.
    """
    scheduler = _FakeScheduler()
    contrib = summary_schedule.L3SummaryScheduleContrib()
    monkeypatch.setattr(summary_schedule, "get_config", lambda: _config_with_l3_enabled(False))

    async def _skip_activity_schedules(_scheduler: _FakeScheduler) -> None:
        return None

    monkeypatch.setattr(contrib, "_register_activity_schedules", _skip_activity_schedules)

    await contrib.register_schedules(scheduler)  # type: ignore[arg-type]

    schedule_ids = {item["schedule_id"] for item in scheduler.intervals}
    assert schedule_ids == {
        "memory-l3-summary:hour",
        "memory-l3-summary:day",
        "memory-l3-summary:week",
        "memory-l3-summary:month",
    }
    assert scheduler.unscheduled == []


@pytest.mark.asyncio
async def test_handle_l3_summary_skips_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(summary_schedule, "get_config", lambda: _config_with_l3_enabled(False))

    schedule = SimpleNamespace(target_payload={"period_type": "hour"})
    context = SimpleNamespace(schedule=schedule)
    result = await summary_schedule.handle_l3_summary(context)  # type: ignore[arg-type]

    assert result.success is True
    assert result.message == "l3_disabled_skip"


@pytest.mark.asyncio
async def test_l3_summary_schedule_unregisters_month_period() -> None:
    scheduler = _FakeScheduler()
    contrib = summary_schedule.L3SummaryScheduleContrib()
    contrib._activity_schedule_ids = ["memory-l3-activity:chrome_history:month"]

    await contrib.unregister_schedules(scheduler)  # type: ignore[arg-type]

    unscheduled_ids = [item["schedule_id"] for item in scheduler.unscheduled]
    assert "memory-l3-summary:month" in unscheduled_ids
    assert "memory-l3-activity:chrome_history:month" in unscheduled_ids
    assert contrib._activity_schedule_ids == []
