"""Global scheduler runtime helpers."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .service import SchedulerService

if TYPE_CHECKING:
    from .bootstrap import SchedulerBootstrap

_scheduler_service: SchedulerService | None = None
_scheduler_bootstrap: "SchedulerBootstrap | None" = None


def set_scheduler_runtime(
    service: SchedulerService | None,
    bootstrap: "SchedulerBootstrap | None",
) -> None:
    """Set global scheduler runtime references."""

    global _scheduler_service, _scheduler_bootstrap
    _scheduler_service = service
    _scheduler_bootstrap = bootstrap


def get_scheduler_service() -> SchedulerService | None:
    """Return the active scheduler service when initialized."""

    return _scheduler_service


def get_scheduler_bootstrap() -> "SchedulerBootstrap | None":
    """Return the active scheduler bootstrap when initialized."""

    return _scheduler_bootstrap


def request_scheduler_refresh() -> None:
    """Request a background refresh of scheduler-managed timeline jobs."""

    if _scheduler_bootstrap is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_scheduler_bootstrap.sync_timeline_sensor_schedules())
