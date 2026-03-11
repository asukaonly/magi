"""Global scheduler runtime helpers."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..core.logger import get_logger
from .service import SchedulerService

if TYPE_CHECKING:
    from .bootstrap import SchedulerBootstrap

_scheduler_service: SchedulerService | None = None
_scheduler_bootstrap: "SchedulerBootstrap | None" = None
_refresh_task: asyncio.Task[None] | None = None
_refresh_pending = False

logger = get_logger(__name__)


def set_scheduler_runtime(
    service: SchedulerService | None,
    bootstrap: "SchedulerBootstrap | None",
) -> None:
    """Set global scheduler runtime references."""

    global _scheduler_service, _scheduler_bootstrap, _refresh_task, _refresh_pending
    _scheduler_service = service
    _scheduler_bootstrap = bootstrap
    if service is None or bootstrap is None:
        if _refresh_task is not None and not _refresh_task.done():
            _refresh_task.cancel()
        _refresh_task = None
        _refresh_pending = False


def get_scheduler_service() -> SchedulerService | None:
    """Return the active scheduler service when initialized."""

    return _scheduler_service


def get_scheduler_bootstrap() -> "SchedulerBootstrap | None":
    """Return the active scheduler bootstrap when initialized."""

    return _scheduler_bootstrap


def request_scheduler_refresh() -> None:
    """Request a background refresh of scheduler-managed timeline jobs."""

    global _refresh_pending, _refresh_task
    if _scheduler_bootstrap is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _refresh_pending = True
    if _refresh_task is not None and not _refresh_task.done():
        return
    _refresh_task = loop.create_task(_run_scheduler_refresh())


async def _run_scheduler_refresh() -> None:
    global _refresh_pending, _refresh_task
    try:
        while _refresh_pending and _scheduler_bootstrap is not None:
            _refresh_pending = False
            try:
                await _scheduler_bootstrap.sync_timeline_sensor_schedules()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Scheduler refresh failed", error=str(exc))
    finally:
        _refresh_task = None
