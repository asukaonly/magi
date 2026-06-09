"""Outbox-drain scheduler handler. Registered on SchedulerService under
ScheduledTargetType.OUTREACH_OUTBOX_DRAIN by OutreachModule."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from ..agent.trace import now_wall_ms
from ..core.logger import get_logger
from ..scheduler.contracts import ScheduledExecutionResult

logger = get_logger(__name__)

OUTBOX_DRAIN_SCHEDULE_ID = "outreach-outbox-drain"
OUTBOX_DRAIN_TARGET_KEY = "outreach_outbox"
OUTBOX_DRAIN_INTERVAL_SECONDS = 900.0  # 15 min


def build_outbox_drain_handler(
    service: Any, *, now_ms: Callable[[], int] = now_wall_ms
) -> Callable[[Any], Awaitable[ScheduledExecutionResult]]:
    async def _handle(_ctx: Any) -> ScheduledExecutionResult:
        try:
            await service.drain_due(now_ms=now_ms())
            return ScheduledExecutionResult(success=True, message="outreach outbox drained")
        except Exception as exc:  # noqa: BLE001
            logger.warning("outreach: outbox drain failed", exc_info=True)
            return ScheduledExecutionResult(success=False, message=str(exc))

    return _handle
