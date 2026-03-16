"""Global scheduler runtime helpers."""
from __future__ import annotations

from ..core.logger import get_logger
from .service import SchedulerService

_scheduler_service: SchedulerService | None = None

logger = get_logger(__name__)


def set_scheduler_runtime(service: SchedulerService | None, *_ignored: object) -> None:
    """Set global scheduler runtime references."""

    global _scheduler_service
    _scheduler_service = service


def get_scheduler_service() -> SchedulerService | None:
    """Return the active scheduler service when initialized."""

    return _scheduler_service


def request_scheduler_refresh() -> None:
    """Deprecated no-op kept until timeline-owned refresh is introduced."""

    logger.debug("Scheduler refresh shim called without engine-owned behavior")
