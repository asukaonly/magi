"""Scheduler integration for periodic L2 entity maintenance."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ...config import get_config
from ...core.logger import get_logger
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from ...scheduler.service import SchedulerService
from ..provider import get_unified_memory
from .entities.maintenance import (
    L2EntityMaintenance,
    L2MaintenanceLifecycle,
    SCHEDULE_ID_L2_MAINTENANCE,
    TARGET_KEY_L2_MAINTENANCE,
)

logger = get_logger(__name__)


def _lifecycle_from_config(l2_cfg: Any) -> L2MaintenanceLifecycle:
    """Map the ``agent.memory.l2.lifecycle`` settings onto the daemon dataclass."""
    lc = l2_cfg.lifecycle
    return L2MaintenanceLifecycle(
        fast_decay_ttl_seconds=lc.fast_decay_ttl_seconds,
        session_decay_ttl_seconds=lc.session_decay_ttl_seconds,
        archive_confidence_threshold=lc.archive_confidence_threshold,
        archive_staleness_seconds=lc.archive_staleness_seconds,
        archive_single_observation_staleness_seconds=lc.archive_single_observation_staleness_seconds,
        purge_terminal_edge_staleness_seconds=lc.purge_terminal_edge_staleness_seconds,
        reconcile_stale_threshold_seconds=lc.reconcile_stale_threshold_seconds,
        reconcile_batch_size=lc.reconcile_batch_size,
        reconcile_max_total=lc.reconcile_max_total,
    )


async def handle_l2_entity_maintenance(
    context: ScheduledExecutionContext,
) -> ScheduledExecutionResult:
    """Run L2 catalog/graph cleanup; no-ops when L2 is off or memory is unavailable."""
    _ = context
    memory_cfg = get_config().agent.memory
    if not memory_cfg.l2.enabled:
        return ScheduledExecutionResult(success=True, message="l2_disabled_skip", stats={})
    if not memory_cfg.l2.maintenance_enabled:
        return ScheduledExecutionResult(success=True, message="l2_maintenance_disabled_skip", stats={})

    try:
        unified = get_unified_memory()
    except RuntimeError:
        logger.debug("L2 maintenance skipped: unified memory binding unavailable")
        return ScheduledExecutionResult(success=True, message="unified_memory_unavailable_skip", stats={})

    async with unified.memory_operation_guard():
        if unified.l2_entity_catalog is None:
            return ScheduledExecutionResult(
                success=True,
                message="l2_catalog_uninitialized_skip",
                stats={},
            )

        l2_cfg = memory_cfg.l2
        catalog = unified.l2_entity_catalog
        db_path = str(catalog.db_path)
        # Maintenance still needs the embedding infra for `_clean_non_active_edge_embeddings`
        # (pruning vectors of de-activated edges). Embedding *pending* edges is no longer
        # maintenance's job — that moved to the dedicated EdgeEmbeddingDrainer (#86).
        embedding_service = catalog.embedding_service
        edge_vector_index = catalog.edge_vector_index
        maint = L2EntityMaintenance(
            db_path=db_path,
            embedding_service=embedding_service,
            edge_vector_index=edge_vector_index,
            cognition_store=getattr(
                getattr(unified, "l2_pipeline", None),
                "_cognition_store",
                None,
            ),
            lifecycle=_lifecycle_from_config(l2_cfg),
        )
        try:
            stats = await maint.run(
                min_mentions_to_keep=int(l2_cfg.maintenance_min_mentions),
                consolidate_episodes=False,
            )
        except Exception as exc:
            logger.error("L2 entity maintenance run failed", error=str(exc))
            return ScheduledExecutionResult(
                success=False,
                message="maintenance_failed",
                stats={"error": str(exc)},
            )

        # P2 frequency gate: prune stale non-promoted promotion-counter keys (one-off noise that
        # never crossed threshold); promoted keys are kept. Bounds the counter table over time.
        pruned = 0
        counter = getattr(unified, "l2_promotion_counter", None)
        if counter is not None:
            try:
                pruned = await counter.prune_stale(
                    retention_seconds=l2_cfg.lifecycle.promotion_counter_retention_seconds
                )
            except Exception as exc:
                logger.warning("L2 promotion-counter prune failed", error=str(exc))

        return ScheduledExecutionResult(
            success=True,
            message="maintenance_ok",
            stats={
                **asdict(stats),
                "promotion_counter_pruned": pruned,
            },
        )


class L2MaintenanceScheduleContrib:
    """Registers MEMORY_L2_MAINTENANCE handler and optional interval schedule."""

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        scheduler.register_handler(ScheduledTargetType.MEMORY_L2_MAINTENANCE, handle_l2_entity_maintenance)
        l2_cfg = get_config().agent.memory.l2
        # The schedule is always written so runtime toggling of l2.enabled /
        # maintenance_enabled takes effect without a restart. The handler is
        # responsible for skipping work when the layer is off.
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_L2_MAINTENANCE,
            target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key=TARGET_KEY_L2_MAINTENANCE,
            seconds=float(l2_cfg.maintenance_interval_seconds),
            target_payload={},
        )
        logger.info(
            "L2 maintenance schedule registered",
            interval_seconds=l2_cfg.maintenance_interval_seconds,
        )

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_L2_MAINTENANCE,
            target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key=TARGET_KEY_L2_MAINTENANCE,
        )
