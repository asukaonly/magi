"""Scheduler integration for periodic L2 entity maintenance."""

from __future__ import annotations

from dataclasses import asdict

from ...config import get_config
from ...core.logger import get_logger
from ...core.runtime_bindings import require_unified_memory
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from ...scheduler.service import SchedulerService
from ..embedding.sqlite_vec_index import SqliteVecIndex
from .entity_maintenance import (
    L2EntityMaintenance,
    SCHEDULE_ID_L2_MAINTENANCE,
    TARGET_KEY_L2_MAINTENANCE,
)

logger = get_logger(__name__)


async def handle_l2_entity_maintenance(
    context: ScheduledExecutionContext,
) -> ScheduledExecutionResult:
    """Run L2 catalog/graph maintenance; no-ops when L2 is off or memory is unavailable."""
    _ = context
    memory_cfg = get_config().agent.memory
    if not memory_cfg.l2.enabled:
        return ScheduledExecutionResult(success=True, message="l2_disabled_skip", stats={})

    try:
        unified = require_unified_memory()
    except RuntimeError:
        logger.debug("L2 maintenance skipped: unified memory binding unavailable")
        return ScheduledExecutionResult(success=True, message="unified_memory_unavailable_skip", stats={})

    if unified.l2_entity_catalog is None:
        return ScheduledExecutionResult(success=True, message="l2_catalog_uninitialized_skip", stats={})

    l2_cfg = memory_cfg.l2
    catalog = unified.l2_entity_catalog
    db_path = str(catalog.db_path)
    embedding_service = getattr(catalog, "_embedding_service", None)
    edge_vector_index: SqliteVecIndex | None = None
    if embedding_service is not None:
        edge_vector_index = SqliteVecIndex(
            db_path=db_path,
            registry_table="l2_edge_vectors",
            entity_column="entity_id",
            vec_table_prefix="l2_edge_vec",
        )
    maint = L2EntityMaintenance(
        db_path=db_path,
        embedding_service=embedding_service,
        edge_vector_index=edge_vector_index,
    )
    try:
        stats = await maint.run(min_mentions_to_keep=int(l2_cfg.maintenance_min_mentions))
    except Exception as exc:
        logger.error("L2 entity maintenance run failed", error=str(exc))
        return ScheduledExecutionResult(
            success=False,
            message="maintenance_failed",
            stats={"error": str(exc)},
        )

    return ScheduledExecutionResult(
        success=True,
        message="maintenance_ok",
        stats=asdict(stats),
    )


class L2MaintenanceScheduleContrib:
    """Registers MEMORY_L2_MAINTENANCE handler and optional interval schedule."""

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        scheduler.register_handler(ScheduledTargetType.MEMORY_L2_MAINTENANCE, handle_l2_entity_maintenance)
        l2_cfg = get_config().agent.memory.l2
        if l2_cfg.maintenance_enabled:
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
        else:
            await scheduler.unschedule(
                SCHEDULE_ID_L2_MAINTENANCE,
                target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
                target_key=TARGET_KEY_L2_MAINTENANCE,
            )
            logger.info("L2 maintenance schedule disabled by config")

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_L2_MAINTENANCE,
            target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key=TARGET_KEY_L2_MAINTENANCE,
        )
