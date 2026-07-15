"""Scheduler integration for periodic L4 procedural-memory maintenance.

Runs every 5 minutes (configurable) and performs four sub-jobs in one tick:
- Decay open circuit breakers to half-open after breaker_open_timeout_seconds.
- Close half-open breakers idle for breaker_halfopen_idle_seconds.
- Warn on skills with stuck pending_trace_count (> threshold * 2).
- Soft-delete skills with last_used_at older than inactive_skill_retention_days
  AND total_attempts < inactive_skill_min_attempts.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from ...config import get_config
from ...core.logger import get_logger
from ...core.sqlite import sqlite_connection_async
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from ...scheduler.service import SchedulerService
from ..provider import get_unified_memory

logger = get_logger(__name__)


SCHEDULE_ID_L4_MAINTENANCE = "memory_l4_maintenance"
TARGET_KEY_L4_MAINTENANCE = "memory_l4_maintenance"
DEFAULT_MAINTENANCE_INTERVAL_SECONDS = 300.0


@dataclass(slots=True)
class _MaintenanceStats:
    breakers_decayed_to_halfopen: int = 0
    breakers_closed_from_halfopen: int = 0
    skills_soft_deleted: int = 0
    pending_warnings: int = 0


async def handle_l4_maintenance(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
    _ = context
    cfg = get_config().agent.memory.l4
    if not cfg.maintenance_enabled:
        return ScheduledExecutionResult(success=True, message="l4_maintenance_disabled_skip", stats={})

    try:
        unified = get_unified_memory()
    except RuntimeError:
        return ScheduledExecutionResult(success=True, message="unified_memory_unavailable_skip", stats={})

    async with unified.memory_operation_guard():
        if unified.l4 is None:
            return ScheduledExecutionResult(
                success=True,
                message="l4_uninitialized_skip",
                stats={},
            )

        db_path = str(unified.l4.db_path)
        stats = _MaintenanceStats()
        now = time.time()

        try:
            async with sqlite_connection_async(db_path) as db:
                await _decay_breakers(db, now=now, cfg=cfg, stats=stats)
                await _check_pending_traces(db, cfg=cfg, stats=stats)
                await _soft_delete_inactive(db, now=now, cfg=cfg, stats=stats)
                await db.commit()
        except Exception as exc:
            logger.error("L4 maintenance failed", error=str(exc))
            return ScheduledExecutionResult(
                success=False,
                message="l4_maintenance_failed",
                stats={"error": str(exc)},
            )

        return ScheduledExecutionResult(
            success=True,
            message="l4_maintenance_ok",
            stats={
                "breakers_decayed_to_halfopen": stats.breakers_decayed_to_halfopen,
                "breakers_closed_from_halfopen": stats.breakers_closed_from_halfopen,
                "skills_soft_deleted": stats.skills_soft_deleted,
                "pending_warnings": stats.pending_warnings,
            },
        )


async def _decay_breakers(db, *, now, cfg, stats) -> None:
    open_cutoff = now - float(cfg.breaker_open_timeout_seconds)
    cur = await db.execute(
        """
        UPDATE procedural_skills
        SET circuit_breaker_state = 'half_open',
            updated_at = ?
        WHERE circuit_breaker_state = 'open'
          AND circuit_breaker_opened_at IS NOT NULL
          AND circuit_breaker_opened_at <= ?
          AND deleted_at IS NULL
        """,
        (now, open_cutoff),
    )
    stats.breakers_decayed_to_halfopen = cur.rowcount or 0

    halfopen_idle_cutoff = now - float(cfg.breaker_halfopen_idle_seconds)
    cur = await db.execute(
        """
        UPDATE procedural_skills
        SET circuit_breaker_state = 'closed',
            circuit_breaker_opened_at = NULL,
            updated_at = ?
        WHERE circuit_breaker_state = 'half_open'
          AND last_used_at IS NOT NULL
          AND last_used_at <= ?
          AND deleted_at IS NULL
        """,
        (now, halfopen_idle_cutoff),
    )
    stats.breakers_closed_from_halfopen = cur.rowcount or 0


async def _check_pending_traces(db, *, cfg, stats) -> None:
    threshold = int(cfg.strategy_extraction_threshold) * 2
    async with db.execute(
        """
        SELECT skill_id, skill_name, pending_trace_count
        FROM procedural_skills
        WHERE pending_trace_count > ? AND deleted_at IS NULL
        """,
        (threshold,),
    ) as cur:
        rows = await cur.fetchall()
    for row in rows:
        skill_id, skill_name, pending = row[0], row[1], row[2]
        logger.warning(
            "L4 skill pending_trace_count is stuck above threshold",
            skill_id=skill_id,
            skill_name=skill_name,
            pending_trace_count=pending,
            threshold=threshold,
        )
        stats.pending_warnings += 1


async def _soft_delete_inactive(db, *, now, cfg, stats) -> None:
    inactive_cutoff = now - float(cfg.inactive_skill_retention_days) * 86400.0
    min_attempts = int(cfg.inactive_skill_min_attempts)
    cur = await db.execute(
        """
        UPDATE procedural_skills
        SET deleted_at = ?, updated_at = ?
        WHERE deleted_at IS NULL
          AND last_used_at IS NOT NULL
          AND last_used_at <= ?
          AND total_attempts < ?
        """,
        (now, now, inactive_cutoff, min_attempts),
    )
    stats.skills_soft_deleted = cur.rowcount or 0


class L4MaintenanceScheduleContrib:
    """Registers MEMORY_L4_MAINTENANCE handler and a single interval schedule."""

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        scheduler.register_handler(ScheduledTargetType.MEMORY_L4_MAINTENANCE, handle_l4_maintenance)
        cfg = get_config().agent.memory.l4
        if cfg.maintenance_enabled:
            await scheduler.schedule_interval(
                schedule_id=SCHEDULE_ID_L4_MAINTENANCE,
                target_type=ScheduledTargetType.MEMORY_L4_MAINTENANCE,
                target_key=TARGET_KEY_L4_MAINTENANCE,
                seconds=DEFAULT_MAINTENANCE_INTERVAL_SECONDS,
                target_payload={},
            )
            logger.info(
                "L4 maintenance schedule registered",
                interval_seconds=DEFAULT_MAINTENANCE_INTERVAL_SECONDS,
            )
        else:
            await scheduler.unschedule(
                SCHEDULE_ID_L4_MAINTENANCE,
                target_type=ScheduledTargetType.MEMORY_L4_MAINTENANCE,
                target_key=TARGET_KEY_L4_MAINTENANCE,
            )
            logger.info("L4 maintenance schedule disabled by config")

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_L4_MAINTENANCE,
            target_type=ScheduledTargetType.MEMORY_L4_MAINTENANCE,
            target_key=TARGET_KEY_L4_MAINTENANCE,
        )
