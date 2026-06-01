"""Scheduler integration for populating L2 episode representative_asset_ref."""

from __future__ import annotations

from typing import Protocol

from ..core.logger import get_logger
from ..scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from .selector import MediaSelector

logger = get_logger("magi.media.scheduler")

SCHEDULE_ID_TIMELINE_REPRESENTATIVE_ASSET = "timeline_representative_asset"
TARGET_KEY_TIMELINE_REPRESENTATIVE_ASSET = "timeline_representative_asset"
INTERVAL_SECONDS_TIMELINE_REPRESENTATIVE_ASSET = 4 * 60 * 60  # 4 hours


class _L2EpisodeStoreProtocol(Protocol):
    async def list_episodes(self, **kwargs) -> list[dict]: ...
    async def update_episode(self, *, episode_id: str, **fields) -> bool: ...


class RepresentativeAssetPopulateSchedulerContrib:
    """Populate representative_asset_ref for active episodes that lack one.

    Does NOT overwrite an existing ref — the act of having a ref means
    either the populate job already picked one or a Plan-3-era user
    explicitly chose. Both should be respected.
    """

    def __init__(
        self,
        *,
        l2_store: _L2EpisodeStoreProtocol,
        selector: MediaSelector,
        batch_limit: int = 200,
    ) -> None:
        self._l2_store = l2_store
        self._selector = selector
        self._batch_limit = batch_limit

    async def register_schedules(self, scheduler) -> None:
        scheduler.register_handler(
            ScheduledTargetType.TIMELINE_REPRESENTATIVE_ASSET,
            self._handle_populate,
        )
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_TIMELINE_REPRESENTATIVE_ASSET,
            target_type=ScheduledTargetType.TIMELINE_REPRESENTATIVE_ASSET,
            target_key=TARGET_KEY_TIMELINE_REPRESENTATIVE_ASSET,
            seconds=float(INTERVAL_SECONDS_TIMELINE_REPRESENTATIVE_ASSET),
            target_payload={},
        )

    async def unregister_schedules(self, scheduler) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_TIMELINE_REPRESENTATIVE_ASSET,
            target_type=ScheduledTargetType.TIMELINE_REPRESENTATIVE_ASSET,
            target_key=TARGET_KEY_TIMELINE_REPRESENTATIVE_ASSET,
        )

    async def _handle_populate(
        self, context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        episodes = await self._l2_store.list_episodes(
            statuses=["active", "candidate"], limit=self._batch_limit,
        )

        populated = 0
        skipped_already_set = 0
        for ep in episodes:
            existing = ep.get("representative_asset_ref")
            if existing:
                skipped_already_set += 1
                continue
            ts = float(ep.get("time_start") or 0.0)
            te = float(ep.get("time_end") or ts)
            ref = await self._selector.pick_representative(
                start=ts, end=te, hint="hero",
            )
            if not ref:
                continue
            await self._l2_store.update_episode(
                episode_id=ep["episode_id"], representative_asset_ref=ref,
            )
            populated += 1

        return ScheduledExecutionResult(
            success=True,
            message=f"populated {populated} refs ({skipped_already_set} already set)",
            stats={"populated": populated, "skipped": skipped_already_set},
        )
