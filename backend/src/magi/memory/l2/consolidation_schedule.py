"""Scheduler integration for periodic L2 episode/experience consolidation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time
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

logger = get_logger(__name__)

SCHEDULE_ID_L2_CONSOLIDATE = "memory-l2-consolidate:global"
TARGET_KEY_L2_CONSOLIDATE = "memory_l2_consolidate"


@dataclass(slots=True)
class _L2ConsolidationStores:
    unified: Any
    cognition_store: Any
    l1_store: Any | None
    l3_store: Any | None
    scenario_llm_pool: Any | None = None


@dataclass(slots=True)
class _EpisodicSummaryStats:
    generated: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _ExperienceConsolidationStats:
    candidates: int = 0
    promoted: int = 0
    duplicates: int = 0
    rejected: int = 0
    summaries_generated: int = 0
    summary_errors: list[str] = field(default_factory=list)
    deferred: int = 0
    selector_diagnostics: dict[str, int] = field(default_factory=dict)


async def handle_l2_consolidation(
    context: ScheduledExecutionContext,
) -> ScheduledExecutionResult:
    """Promote/merge episodes, promote experiences, and generate missing summaries."""
    _ = context
    skip_result = _l2_consolidation_skip_result()
    if skip_result is not None:
        return skip_result

    stores_or_skip = _resolve_l2_consolidation_stores()
    if isinstance(stores_or_skip, ScheduledExecutionResult):
        return stores_or_skip
    stores = stores_or_skip

    started = time.monotonic()
    async with stores.unified.memory_operation_guard():
        episode_result = await _run_episode_consolidation(stores.cognition_store)
        if isinstance(episode_result, ScheduledExecutionResult):
            return episode_result

        episodic_summary_stats = await _generate_episodic_summaries(
            stores=stores,
            promoted_episode_ids=list(getattr(episode_result, "promoted_episode_ids", []) or []),
        )
        experience_stats = await _promote_experiences_and_summaries(stores)
        result = _l2_consolidation_success_result(
            episode_stats=episode_result,
            episodic_summary_stats=episodic_summary_stats,
            experience_stats=experience_stats,
        )
        result.stats["duration_seconds"] = round(time.monotonic() - started, 3)
        return result


def _l2_consolidation_skip_result() -> ScheduledExecutionResult | None:
    memory_cfg = get_config().agent.memory
    if not memory_cfg.l2.enabled:
        return ScheduledExecutionResult(success=True, message="l2_disabled_skip", stats={})
    if not memory_cfg.l2.consolidation_enabled:
        return ScheduledExecutionResult(
            success=True,
            message="l2_consolidation_disabled_skip",
            stats={},
        )
    return None


def _resolve_l2_consolidation_stores() -> _L2ConsolidationStores | ScheduledExecutionResult:
    try:
        unified = get_unified_memory()
    except RuntimeError:
        logger.debug("L2 consolidation skipped: unified memory binding unavailable")
        return ScheduledExecutionResult(
            success=True,
            message="unified_memory_unavailable_skip",
            stats={},
        )

    cognition_store = getattr(
        getattr(unified, "l2_pipeline", None),
        "_cognition_store",
        None,
    )
    if cognition_store is None:
        cognition_store = getattr(unified, "l2", None)
    if cognition_store is None:
        return ScheduledExecutionResult(
            success=True,
            message="l2_store_uninitialized_skip",
            stats={},
        )
    return _L2ConsolidationStores(
        unified=unified,
        cognition_store=cognition_store,
        l1_store=getattr(unified, "l1", None),
        l3_store=getattr(unified, "l3", None),
        scenario_llm_pool=vars(unified).get("scenario_llm_pool"),
    )


async def _run_episode_consolidation(
    cognition_store: Any,
) -> Any | ScheduledExecutionResult:
    try:
        from .episode_formation import consolidate_episodes

        return await consolidate_episodes(cognition_store)
    except Exception as exc:
        logger.error("L2 episode consolidation failed", error=str(exc))
        return ScheduledExecutionResult(
            success=False,
            message="consolidation_failed",
            stats={"error": str(exc)},
        )


async def _generate_episodic_summaries(
    *,
    stores: _L2ConsolidationStores,
    promoted_episode_ids: list[str],
) -> _EpisodicSummaryStats:
    stats = _EpisodicSummaryStats()
    if not promoted_episode_ids or stores.l1_store is None or stores.l3_store is None:
        return stats
    try:
        summary_result = await stores.l3_store.generate_missing_episodic_summaries(
            l1_store=stores.l1_store,
            l2_store=stores.cognition_store,
            episode_ids=promoted_episode_ids,
        )
        stats.generated = int(summary_result.get("generated") or 0)
        stats.errors = list(summary_result.get("errors") or [])
    except Exception as exc:
        logger.warning("L2 episodic summary generation failed", error=str(exc))
        stats.errors.append(str(exc))
    return stats


async def _promote_experiences_and_summaries(
    stores: _L2ConsolidationStores,
) -> _ExperienceConsolidationStats:
    stats = _ExperienceConsolidationStats()
    try:
        from .experiences.promotion import promote_experiences_from_episodes
        from .experiences.seed_selection_llm import build_experience_seed_selector
        from .experiences.summary_generation import generate_missing_experience_summaries

        l2_cfg = get_config().agent.memory.l2
        selector = build_experience_seed_selector(
            scenario_llm_pool=stores.scenario_llm_pool,
            enabled=bool(l2_cfg.experience_seed_llm_selection_enabled),
            timeout_seconds=float(l2_cfg.experience_seed_llm_timeout_seconds),
            diagnostics=stats.selector_diagnostics,
        )
        promotion_kwargs: dict[str, Any] = {}
        if selector is not None:
            promotion_kwargs["selector"] = selector
        experience_stats = await promote_experiences_from_episodes(
            stores.cognition_store,
            max_selector_calls=int(l2_cfg.experience_seed_llm_selection_max_per_run),
            **promotion_kwargs,
        )
        stats.candidates = int(experience_stats.candidates)
        stats.promoted = int(experience_stats.promoted)
        stats.duplicates = int(experience_stats.skipped_duplicates)
        stats.rejected = int(experience_stats.rejected)
        stats.deferred = int(getattr(experience_stats, "deferred", 0))

        if stores.l1_store is not None and stores.l3_store is not None:
            summary_result = await generate_missing_experience_summaries(
                l1_store=stores.l1_store,
                l2_store=stores.cognition_store,
                l3_store=stores.l3_store,
                experience_ids=experience_stats.promoted_experience_ids,
            )
            stats.summaries_generated = int(summary_result.get("generated") or 0)
            stats.summary_errors = list(summary_result.get("errors") or [])
    except Exception as exc:
        logger.warning("L2 experience promotion failed", error=str(exc))
        stats.summary_errors.append(str(exc))
    return stats


def _l2_consolidation_success_result(
    *,
    episode_stats: Any,
    episodic_summary_stats: _EpisodicSummaryStats,
    experience_stats: _ExperienceConsolidationStats,
) -> ScheduledExecutionResult:
    errors = (
        list(getattr(episode_stats, "errors", []) or [])
        + episodic_summary_stats.errors
        + experience_stats.summary_errors
    )
    selector_errors = int(experience_stats.selector_diagnostics.get("failures", 0))
    return ScheduledExecutionResult(
        success=not errors and not selector_errors,
        message="consolidation_partial_failure"
        if errors or selector_errors
        else "consolidation_ok",
        stats={
            **asdict(episode_stats),
            "episodes_promoted": int(episode_stats.promoted),
            "episodes_merged": int(episode_stats.merged),
            "episodes_invalidated": int(episode_stats.invalidated),
            "episodic_summaries_generated": episodic_summary_stats.generated,
            "episodic_summary_errors": episodic_summary_stats.errors,
            "experience_candidates": experience_stats.candidates,
            "experiences_promoted": experience_stats.promoted,
            "experience_duplicates": experience_stats.duplicates,
            "experience_rejected": experience_stats.rejected,
            "experience_deferred": experience_stats.deferred,
            "selector_diagnostics": experience_stats.selector_diagnostics,
            "experience_summaries_generated": experience_stats.summaries_generated,
            "experience_summary_errors": experience_stats.summary_errors,
        },
    )


async def request_l2_consolidation(scheduler: SchedulerService, *, reason: str) -> bool:
    """Coalesce import/manual requests into one bounded scheduled run."""
    if _l2_consolidation_skip_result() is not None:
        return False
    await scheduler.schedule_once_earliest(
        schedule_id="memory-l2-consolidate:requested",
        target_type=ScheduledTargetType.MEMORY_L2_CONSOLIDATE,
        target_key=TARGET_KEY_L2_CONSOLIDATE,
        run_at=time.time() + 30.0,
        target_payload={"reason": reason},
    )
    return True


class L2ConsolidationScheduleContrib:
    """Registers MEMORY_L2_CONSOLIDATE handler and interval schedule."""

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        scheduler.register_handler(
            ScheduledTargetType.MEMORY_L2_CONSOLIDATE, handle_l2_consolidation
        )
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
