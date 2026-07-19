"""Outbox-drain scheduler handler. Registered on SchedulerService under
ScheduledTargetType.OUTREACH_OUTBOX_DRAIN by OutreachModule."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from ..agent.trace import now_wall_ms
from ..core.logger import get_logger
from ..scheduler.contracts import ScheduledExecutionResult

logger = get_logger(__name__)

OUTBOX_DRAIN_SCHEDULE_ID = "outreach-outbox-drain"
OUTBOX_DRAIN_TARGET_KEY = "outreach_outbox"
OUTBOX_DRAIN_INTERVAL_SECONDS = 900.0  # 15 min


def build_outbox_drain_handler(
    service: Any,
    completion_producer: Any,
    *,
    now_ms: Callable[[], int] = now_wall_ms,
) -> Callable[[Any], Awaitable[ScheduledExecutionResult]]:
    drain_lock = asyncio.Lock()

    async def _handle(_ctx: Any) -> ScheduledExecutionResult:
        async with drain_lock:
            failures: list[str] = []
            recovered_completions = 0
            try:
                recovered_completions = await completion_producer.drain_pending()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "outreach: background completion drain failed",
                    exc_info=True,
                )
                failures.append(f"background_completion: {exc}")

            try:
                await service.drain_due(now_ms=now_ms())
            except Exception as exc:  # noqa: BLE001
                logger.warning("outreach: outbox drain failed", exc_info=True)
                failures.append(f"outbox: {exc}")

            return ScheduledExecutionResult(
                success=not failures,
                message=(
                    "; ".join(failures)
                    if failures
                    else "outreach pending work drained"
                ),
                stats={"background_completions": recovered_completions},
            )

    return _handle
