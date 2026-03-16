"""Global scheduler runtime helpers."""
from __future__ import annotations

from .service import SchedulerService

_scheduler_service: SchedulerService | None = None


def set_scheduler_runtime(service: SchedulerService | None, *_ignored: object) -> None:
    """Set global scheduler runtime references."""

    global _scheduler_service
    _scheduler_service = service


def get_scheduler_service() -> SchedulerService | None:
    """Return the active scheduler service when initialized."""

    return _scheduler_service
