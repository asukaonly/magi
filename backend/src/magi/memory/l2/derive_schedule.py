"""Scheduler integration for periodic L2 derived-data generation.

Runs interest aggregation and shadow-conflict-notification materialization on
an independent cadence (default 6 h) completely separate from the L2 ops
maintenance task (entity/graph hygiene, embedding cleanup, promotion-counter
prune).  This separation lets business-derived data refresh more frequently or
less frequently than housekeeping without coupling the two.
"""

from __future__ import annotations

from ...config import get_config
from ...core.logger import get_logger
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from ...scheduler.service import SchedulerService
from ..provider import get_unified_memory
from .assertions.conflict_notifications import materialize_shadow_conflict_notifications
from .assertions.interest_aggregation import aggregate_interests

logger = get_logger(__name__)

SCHEDULE_ID_L2_DERIVE = "memory-l2-derive:global"
TARGET_KEY_L2_DERIVE = "memory_l2_derive"


async def handle_l2_derive(
    context: ScheduledExecutionContext,
) -> ScheduledExecutionResult:
    """Run L2 derived-data steps; no-ops when L2 is off or derive task is disabled."""
    _ = context
    memory_cfg = get_config().agent.memory
    if not memory_cfg.l2.enabled:
        return ScheduledExecutionResult(success=True, message="l2_disabled_skip", stats={})
    if not memory_cfg.l2.derive_schedule_enabled:
        return ScheduledExecutionResult(success=True, message="l2_derive_disabled_skip", stats={})

    try:
        unified = get_unified_memory()
    except RuntimeError:
        logger.debug("L2 derive skipped: unified memory binding unavailable")
        return ScheduledExecutionResult(success=True, message="unified_memory_unavailable_skip", stats={})

    if unified.l2_entity_catalog is None:
        return ScheduledExecutionResult(success=True, message="l2_catalog_uninitialized_skip", stats={})

    l2_cfg = memory_cfg.l2
    catalog = unified.l2_entity_catalog
    db_path = str(catalog.db_path)

    # Prefer the cognition store already wired into the pipeline when available;
    # fall back to constructing one from the shared db_path (initialize() is idempotent).
    cognition_store = getattr(getattr(unified, "l2_pipeline", None), "_cognition_store", None)
    if cognition_store is None:
        from .store import L2CognitionStore
        cognition_store = L2CognitionStore(db_path=db_path)
        await cognition_store.initialize()

    # Interest aggregation: surface INTERESTED_IN edges as inferred preference_profile assertions.
    interest_topics_aggregated = 0
    if l2_cfg.interest_aggregation_enabled:
        try:
            agg_stats = await aggregate_interests(
                cognition_store,
                entity_id="user:self",
                min_observations=int(l2_cfg.interest_observation_threshold),
            )
            interest_topics_aggregated = agg_stats.get("topics_aggregated", 0)
        except Exception as exc:
            logger.warning("L2 interest aggregation failed", error=str(exc))

        if interest_topics_aggregated > 0:
            try:
                await cognition_store.refresh_entity_snapshot(entity_id="user:self", entity_type="user")
            except Exception:
                logger.warning("interest aggregation: snapshot refresh failed", exc_info=True)

    # Shadow-conflict notifications: surface assertion conflicts to the user.
    shadow_notifications_emitted = 0
    if l2_cfg.shadow_conflict_notification_enabled:
        try:
            from magi.notifications.service import NotificationService
            from magi.notifications.store import get_notification_store
            _notif_service = NotificationService(store=get_notification_store())
            shadow_stats = await materialize_shadow_conflict_notifications(
                cognition_store,
                _notif_service,
                user_id="default_user",
                entity_id="user:self",
                entity_type="user",
            )
            shadow_notifications_emitted = shadow_stats.get("notifications_emitted", 0)
        except Exception as exc:
            logger.warning("L2 shadow conflict notification scan failed", error=str(exc))

    return ScheduledExecutionResult(
        success=True,
        message="derive_ok",
        stats={
            "interest_topics_aggregated": interest_topics_aggregated,
            "shadow_notifications_emitted": shadow_notifications_emitted,
        },
    )


class L2DeriveScheduleContrib:
    """Registers MEMORY_L2_DERIVE handler and optional interval schedule."""

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        scheduler.register_handler(ScheduledTargetType.MEMORY_L2_DERIVE, handle_l2_derive)
        l2_cfg = get_config().agent.memory.l2
        # The schedule is always written so runtime toggling of l2.enabled /
        # derive_schedule_enabled takes effect without a restart. The handler is
        # responsible for skipping work when the layer is off.
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_L2_DERIVE,
            target_type=ScheduledTargetType.MEMORY_L2_DERIVE,
            target_key=TARGET_KEY_L2_DERIVE,
            seconds=float(l2_cfg.derive_schedule_interval_seconds),
            target_payload={},
        )
        logger.info(
            "L2 derive schedule registered",
            interval_seconds=l2_cfg.derive_schedule_interval_seconds,
        )

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_L2_DERIVE,
            target_type=ScheduledTargetType.MEMORY_L2_DERIVE,
            target_key=TARGET_KEY_L2_DERIVE,
        )
