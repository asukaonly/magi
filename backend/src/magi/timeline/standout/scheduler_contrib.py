"""Scheduler integration for standout episode rescoring."""

from __future__ import annotations

from typing import Protocol

from ...core.logger import get_logger
from ...media.source_registry import MediaSourceRegistry
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from .scoring import StandoutSignals, compute_standout_score

logger = get_logger("magi.timeline.standout.scheduler")


class _L2EpisodeStoreProtocol(Protocol):
    async def list_episodes(self, **kwargs) -> list[dict]: ...
    async def update_episode(self, *, episode_id: str, **fields) -> bool: ...


class StandoutScoringSchedulerContrib:
    """Periodic rescore of all active episodes.

    Picks signals lazily from existing data:
      - has_photos: MediaSourceRegistry.collect_assets within the episode window
      - state_shift_count: not yet wired; defaults to 0 in Plan 2 (Plan 3 frontend
        won't notice; later we can plug in state-marker data from L3)
      - first_seen_entities: an entity is "first seen" if no earlier episode shares it

    First-seen detection is per-batch: we compare the current episode's entities
    against the union of all entities from episodes with smaller time_start
    within the same batch. Good enough for scoring; precise dedup against the
    full historical store is a future refinement.
    """

    def __init__(
        self,
        *,
        l2_store: _L2EpisodeStoreProtocol,
        media_registry: MediaSourceRegistry,
        batch_limit: int = 500,
    ) -> None:
        self._l2_store = l2_store
        self._media_registry = media_registry
        self._batch_limit = batch_limit

    async def register_schedules(self, scheduler) -> None:
        await scheduler.register_handler(
            ScheduledTargetType.TIMELINE_STANDOUT_RESCORE,
            self._handle_rescore,
        )

    async def unregister_schedules(self, scheduler) -> None:
        unregister = getattr(scheduler, "unregister_handler", None)
        if unregister:
            await unregister(ScheduledTargetType.TIMELINE_STANDOUT_RESCORE)

    async def _handle_rescore(
        self, context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        episodes = await self._l2_store.list_episodes(
            statuses=["active"], limit=self._batch_limit,
        )

        # Order ascending by time_start for first-entity detection
        episodes_sorted = sorted(episodes, key=lambda e: float(e.get("time_start") or 0.0))
        seen_entities: set[str] = set()
        scored = 0
        promoted = 0

        for ep in episodes_sorted:
            ep_entities = [str(e) for e in (ep.get("primary_entity_ids") or []) if e]
            first_seen = [e for e in ep_entities if e not in seen_entities]
            seen_entities.update(ep_entities)

            # has_photos check via media registry
            ts = float(ep.get("time_start") or 0.0)
            te = float(ep.get("time_end") or ts)
            try:
                assets = await self._media_registry.collect_assets(start=ts, end=te)
            except Exception:
                assets = []
            has_photos = bool(assets)

            signals = StandoutSignals(
                has_photos=has_photos,
                state_shift_count=0,  # Plan 3+ when L3 markers wire in
                first_seen_entities=first_seen,
            )
            score, reason, is_standout = compute_standout_score(episode=ep, signals=signals)

            await self._l2_store.update_episode(
                episode_id=ep["episode_id"],
                magi_standout=is_standout,
                standout_score=score,
                standout_reason=reason,
            )
            scored += 1
            if is_standout:
                promoted += 1

        return ScheduledExecutionResult(
            success=True,
            message=f"scored {scored} episodes, promoted {promoted} to standout",
            stats={"scored": scored, "promoted": promoted},
        )
