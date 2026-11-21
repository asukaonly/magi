"""Scheduler integration for opt-in location source pollers."""

from __future__ import annotations

from collections.abc import Callable

from ..core.logger import get_logger
from ..scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from .sources.ipgeo import IPGeoLocationSource

logger = get_logger("magi.location.scheduler")

SCHEDULE_ID_IPGEO_POLL = "location_ipgeo_poll"
TARGET_KEY_IPGEO_POLL = "location_ipgeo_poll"
# IP rarely changes city in under 4h even with VPN toggling. More frequent
# polling would just burn the ipapi.co free-tier rate limit.
INTERVAL_SECONDS_IPGEO_POLL = 4 * 60 * 60


class IPGeoPollSchedulerContrib:
    """Periodically poll ipapi.co and persist a fresh ipgeo sample when opted in."""

    def __init__(
        self,
        *,
        ipgeo_source: IPGeoLocationSource,
        is_enabled: Callable[[], bool] = lambda: False,
    ) -> None:
        self._source = ipgeo_source
        self._is_enabled = is_enabled

    async def register_schedules(self, scheduler) -> None:
        scheduler.register_handler(
            ScheduledTargetType.LOCATION_IPGEO_POLL,
            self._handle_poll,
        )
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_IPGEO_POLL,
            target_type=ScheduledTargetType.LOCATION_IPGEO_POLL,
            target_key=TARGET_KEY_IPGEO_POLL,
            seconds=float(INTERVAL_SECONDS_IPGEO_POLL),
            target_payload={},
        )

    async def unregister_schedules(self, scheduler) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_IPGEO_POLL,
            target_type=ScheduledTargetType.LOCATION_IPGEO_POLL,
            target_key=TARGET_KEY_IPGEO_POLL,
        )

    async def _handle_poll(
        self, context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        if not self._is_enabled():
            return ScheduledExecutionResult(
                success=True,
                message="ipgeo poll skipped (ambient_ip_location_enabled is disabled)",
                stats={"skipped": "disabled"},
            )
        try:
            sample = await self._source.poll_and_persist()
        except Exception as exc:
            logger.warning("ipgeo poll handler crashed", error=str(exc))
            return ScheduledExecutionResult(
                success=False, message=f"ipgeo poll failed: {exc}", stats={},
            )

        if sample is None:
            return ScheduledExecutionResult(
                success=False,
                message="ipgeo poll yielded no sample (rate limit or network)",
                stats={},
            )

        return ScheduledExecutionResult(
            success=True,
            message=(
                f"ipgeo sample stored: "
                f"{sample.city or '-'} / {sample.region or '-'} / {sample.country or '-'}"
            ),
            stats={
                "city": sample.city or "",
                "region": sample.region or "",
                "country": sample.country or "",
            },
        )
