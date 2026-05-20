"""Scheduler integration for the location source pollers."""

from __future__ import annotations

from ..core.logger import get_logger
from ..scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from .sources.ipgeo import IPGeoLocationSource
from .sources.wifi import WiFiLocationSource

logger = get_logger("magi.location.scheduler")

SCHEDULE_ID_IPGEO_POLL = "location_ipgeo_poll"
TARGET_KEY_IPGEO_POLL = "location_ipgeo_poll"
# IP rarely changes city in under 4h even with VPN toggling. More frequent
# polling would just burn the ipapi.co free-tier rate limit.
INTERVAL_SECONDS_IPGEO_POLL = 4 * 60 * 60

SCHEDULE_ID_WIFI_POLL = "location_wifi_poll"
TARGET_KEY_WIFI_POLL = "location_wifi_poll"
# Active interval: 10 minutes. Backoff kicks in when consecutive scans
# yield nothing (no adapter, permission denied, etc.) — falling back to a
# 6h heartbeat so we don't burn CPU on machines that can never scan.
INTERVAL_SECONDS_WIFI_POLL_ACTIVE = 10 * 60
INTERVAL_SECONDS_WIFI_POLL_BACKOFF = 6 * 60 * 60
WIFI_BACKOFF_FAILURE_THRESHOLD = 5


class IPGeoPollSchedulerContrib:
    """Periodically poll ipapi.co and persist a fresh ipgeo sample."""

    def __init__(self, *, ipgeo_source: IPGeoLocationSource) -> None:
        self._source = ipgeo_source

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


class WiFiPollSchedulerContrib:
    """Periodically scan WiFi APs and store a fix.

    Implements an adaptive interval: after N consecutive empty scans we
    increase the schedule period from 10min to 6h, on the assumption that
    we're on a machine that can't scan (no WiFi adapter, no permission).
    A successful scan resets the counter.

    NOTE: The scheduler service in this codebase doesn't currently expose
    a per-tick reschedule API, so the backoff state is tracked in-process
    and the *next-fire decision* is left to the scheduler's fixed interval.
    What we DO is short-circuit the work — when in backoff we skip the
    actual scan and just return success-with-skip until the failure
    counter ages out. (A future scheduler enhancement could honor a
    dynamic interval returned from the handler.)
    """

    def __init__(self, *, wifi_source: WiFiLocationSource) -> None:
        self._source = wifi_source
        self._consecutive_failures = 0
        self._skip_until: float = 0.0  # unix sec; skip work until this time

    async def register_schedules(self, scheduler) -> None:
        scheduler.register_handler(
            ScheduledTargetType.LOCATION_WIFI_POLL,
            self._handle_poll,
        )
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_WIFI_POLL,
            target_type=ScheduledTargetType.LOCATION_WIFI_POLL,
            target_key=TARGET_KEY_WIFI_POLL,
            seconds=float(INTERVAL_SECONDS_WIFI_POLL_ACTIVE),
            target_payload={},
        )

    async def unregister_schedules(self, scheduler) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_WIFI_POLL,
            target_type=ScheduledTargetType.LOCATION_WIFI_POLL,
            target_key=TARGET_KEY_WIFI_POLL,
        )

    async def _handle_poll(
        self, context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        import time as _time

        triggered_at = float(getattr(context, "triggered_at", 0.0) or _time.time())
        if triggered_at < self._skip_until:
            return ScheduledExecutionResult(
                success=True,
                message="wifi poll skipped (in backoff after %d consecutive empty scans)"
                % self._consecutive_failures,
                stats={"skipped": "true"},
            )

        try:
            sample = await self._source.poll_and_persist()
        except Exception as exc:
            logger.warning("wifi poll handler crashed", error=str(exc))
            sample = None

        if sample is None:
            self._consecutive_failures += 1
            if self._consecutive_failures >= WIFI_BACKOFF_FAILURE_THRESHOLD:
                self._skip_until = triggered_at + INTERVAL_SECONDS_WIFI_POLL_BACKOFF
                logger.info(
                    "wifi poll: %d consecutive empty scans, backing off until %d",
                    self._consecutive_failures, int(self._skip_until),
                )
            return ScheduledExecutionResult(
                success=False,
                message=f"wifi scan empty (consecutive_failures={self._consecutive_failures})",
                stats={"consecutive_failures": str(self._consecutive_failures)},
            )

        # Success — reset backoff state.
        self._consecutive_failures = 0
        self._skip_until = 0.0
        return ScheduledExecutionResult(
            success=True,
            message=f"wifi sample stored: {sample.city or '-'} (accuracy={sample.accuracy_m:.0f}m)",
            stats={
                "city": sample.city or "",
                "accuracy_m": str(sample.accuracy_m or 0),
                "ap_count": str((sample.metadata or {}).get("ap_count") or 0),
            },
        )
