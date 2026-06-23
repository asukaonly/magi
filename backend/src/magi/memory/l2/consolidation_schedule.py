"""Scheduler integration for periodic L2 episode/experience consolidation."""

from __future__ import annotations

from dataclasses import asdict

from ...config import get_config
from ...core.logger import get_logger
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from ...scheduler.service import SchedulerService
from ..provider import get_unified_memory

logger = get_logger(__name__)

SCHEDULE_ID_L2_CONSOLIDATE = "memory-l2-consolidate:global"
TARGET_KEY_L2_CONSOLIDATE = "memory_l2_consolidate"


async def handle_l2_consolidation(
    context: ScheduledExecutionContext,
) -> ScheduledExecutionResult:
    """Promote/merge episodes, promote experiences, and generate missing summaries."""
    _ = context
    memory_cfg = get_config().agent.memory
    if not memory_cfg.l2.enabled:
        return ScheduledExecutionResult(success=True, message="l2_disabled_skip", stats={})
    if not memory_cfg.l2.consolidation_enabled:
        return ScheduledExecutionResult(success=True, message="l2_consolidation_disabled_skip", stats={})

    try:
        unified = get_unified_memory()
    except RuntimeError:
        logger.debug("L2 consolidation skipped: unified memory binding unavailable")
        return ScheduledExecutionResult(success=True, message="unified_memory_unavailable_skip", stats={})

    cognition_store = getattr(getattr(unified, "l2_pipeline", None), "_cognition_store", None)
    if cognition_store is None:
        cognition_store = getattr(unified, "l2", None)
    if cognition_store is None:
        return ScheduledExecutionResult(success=True, message="l2_store_uninitialized_skip", stats={})

    try:
        from .episode_formation import consolidate_episodes

        stats = await consolidate_episodes(cognition_store)
    except Exception as exc:
        logger.error("L2 episode consolidation failed", error=str(exc))
        return ScheduledExecutionResult(
            success=False,
            message="consolidation_failed",
            stats={"error": str(exc)},
        )

    episodic_summaries_generated = 0
    episodic_summary_errors: list[str] = []
    promoted_episode_ids = list(getattr(stats, "promoted_episode_ids", []) or [])
    l1_store = getattr(unified, "l1", None)
    l3_store = getattr(unified, "l3", None)
    if promoted_episode_ids and l1_store is not None and l3_store is not None:
        try:
            summary_result = await l3_store.generate_missing_episodic_summaries(
                l1_store=l1_store,
                l2_store=cognition_store,
                episode_ids=promoted_episode_ids,
            )
            episodic_summaries_generated = int(summary_result.get("generated") or 0)
            episodic_summary_errors = list(summary_result.get("errors") or [])
        except Exception as exc:
            logger.warning("L2 episodic summary generation failed", error=str(exc))
            episodic_summary_errors.append(str(exc))

    experience_candidates = 0
    experiences_promoted = 0
    experience_duplicates = 0
    experience_rejected = 0
    experience_summaries_generated = 0
    experience_summary_errors: list[str] = []
    try:
        from .experiences.promotion import promote_experiences_from_episodes
        from .experiences.summary_generation import generate_missing_experience_summaries

        experience_stats = await promote_experiences_from_episodes(cognition_store)
        experience_candidates = int(experience_stats.candidates)
        experiences_promoted = int(experience_stats.promoted)
        experience_duplicates = int(experience_stats.skipped_duplicates)
        experience_rejected = int(experience_stats.rejected)

        if l1_store is not None and l3_store is not None:
            experience_summary_result = await generate_missing_experience_summaries(
                l1_store=l1_store,
                l2_store=cognition_store,
                l3_store=l3_store,
                experience_ids=experience_stats.promoted_experience_ids,
            )
            experience_summaries_generated = int(
                experience_summary_result.get("generated") or 0
            )
            experience_summary_errors = list(experience_summary_result.get("errors") or [])
    except Exception as exc:
        logger.warning("L2 experience promotion failed", error=str(exc))
        experience_summary_errors.append(str(exc))

    return ScheduledExecutionResult(
        success=True,
        message="consolidation_ok",
        stats={
            **asdict(stats),
            "episodes_promoted": int(stats.promoted),
            "episodes_merged": int(stats.merged),
            "episodes_invalidated": int(stats.invalidated),
            "episodic_summaries_generated": episodic_summaries_generated,
            "episodic_summary_errors": episodic_summary_errors,
            "experience_candidates": experience_candidates,
            "experiences_promoted": experiences_promoted,
            "experience_duplicates": experience_duplicates,
            "experience_rejected": experience_rejected,
            "experience_summaries_generated": experience_summaries_generated,
            "experience_summary_errors": experience_summary_errors,
        },
    )


class L2ConsolidationScheduleContrib:
    """Registers MEMORY_L2_CONSOLIDATE handler and interval schedule."""

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        scheduler.register_handler(ScheduledTargetType.MEMORY_L2_CONSOLIDATE, handle_l2_consolidation)
        l2_cfg = get_config().agent.memory.l2
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_L2_CONSOLIDATE,
            target_type=ScheduledTargetType.MEMORY_L2_CONSOLIDATE,
            target_key=TARGET_KEY_L2_CONSOLIDATE,
            seconds=float(l2_cfg.consolidation_interval_seconds),
            target_payload={},
        )
        logger.info(
            "L2 consolidation schedule registered",
            interval_seconds=l2_cfg.consolidation_interval_seconds,
        )

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_L2_CONSOLIDATE,
            target_type=ScheduledTargetType.MEMORY_L2_CONSOLIDATE,
            target_key=TARGET_KEY_L2_CONSOLIDATE,
        )
