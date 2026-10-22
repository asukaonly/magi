"""Lifecycle-bound scheduler service provider."""
from typing import TYPE_CHECKING, cast
from magi.core.container import require_binding
if TYPE_CHECKING:
    from .service import SchedulerService


def require_scheduler_service() -> "SchedulerService":
    return cast("SchedulerService", require_binding("scheduler_service"))
