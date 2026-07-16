"""Scheduler integration for L2 derived data and correction follow-ups.

Runs interest aggregation and shadow-conflict-notification materialization on
an independent cadence (default 6 h) completely separate from the L2 ops
maintenance task (entity/graph hygiene, embedding cleanup, promotion-counter
prune).  This separation lets business-derived data refresh more frequently or
less frequently than housekeeping without coupling the two. Durable correction
jobs share the scheduler target family but use a separate bounded queue cadence.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ...config import get_config
from ...core.logger import get_logger
from ...identity.defaults import CANONICAL_LOCAL_USER
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from ...scheduler.service import SchedulerService
from ..provider import get_unified_memory
from .assertions.derived_rules import (
    build_graph_derived_rules_from_profiles,
    evaluate_graph_derived_assertion_rule,
)
from .assertions.conflict_notifications import materialize_shadow_conflict_notifications
from .assertions.interest_aggregation import aggregate_interests
from .corrections.repository import (
    DEFAULT_DERIVATION_MAX_ATTEMPTS,
    DEFAULT_DERIVATION_STALE_RUNNING_SECONDS,
)
from .extraction_profiles import build_extraction_profile_registry

logger = get_logger(__name__)

SCHEDULE_ID_L2_DERIVE = "memory-l2-derive:global"
TARGET_KEY_L2_DERIVE = "memory_l2_derive"
SCHEDULE_ID_L2_CORRECTION_DERIVE = "memory-l2-correction-derive:global"
SCHEDULE_ID_L2_CORRECTION_RETRY = "memory-l2-correction-derive:retry"
TARGET_KEY_L2_CORRECTION_DERIVE = "memory_l2_correction_derive"
CORRECTION_DERIVATION_SWEEP_INTERVAL_SECONDS = (
    DEFAULT_DERIVATION_STALE_RUNNING_SECONDS
)
CORRECTION_DERIVATION_BATCH_SIZE = 25
CORRECTION_DERIVATION_RETRY_SCHEDULE_DELAY_SECONDS = 1.0
PortraitRefreshScheduler = Callable[[Any, str], Awaitable[None]]


@dataclass(frozen=True)
class L2DeriveContext:
    l2_cfg: Any
    unified: Any
    l1_store: Any
    cognition_store: Any
    user_id: str
    user_entity_id: str


def _canonical_user_entity_id() -> str:
    return f"user:{CANONICAL_LOCAL_USER}"


async def handle_l2_derive(
    context: ScheduledExecutionContext,
    *,
    portrait_refresh_scheduler: PortraitRefreshScheduler | None = None,
) -> ScheduledExecutionResult:
    """Run L2 derived-data steps; no-ops when L2 is off or derive task is disabled."""
    _ = context
    memory_cfg = get_config().agent.memory
    skip_result = _l2_derive_skip_result(memory_cfg)
    if skip_result is not None:
        return skip_result

    derive_context = await _build_l2_derive_context(memory_cfg.l2)
    if isinstance(derive_context, ScheduledExecutionResult):
        return derive_context

    async with derive_context.unified.memory_operation_guard():
        interest_topics_aggregated = await _run_interest_aggregation(derive_context)
        plugin_derived_assertions_written = await _run_plugin_derived_rules(derive_context)
        shadow_notifications_emitted = await _run_shadow_conflict_notifications(derive_context)
        if interest_topics_aggregated > 0 or plugin_derived_assertions_written > 0:
            await _schedule_portrait_refresh(derive_context, portrait_refresh_scheduler)

        return ScheduledExecutionResult(
            success=True,
            message="derive_ok",
            stats={
                "interest_topics_aggregated": interest_topics_aggregated,
                "plugin_derived_assertions_written": plugin_derived_assertions_written,
                "shadow_notifications_emitted": shadow_notifications_emitted,
            },
        )


async def handle_memory_correction_derivations(
    context: ScheduledExecutionContext,
    *,
    scheduler: SchedulerService | None = None,
) -> ScheduledExecutionResult:
    """Process a bounded correction batch and schedule the next due retry."""
    _ = context
    if not get_config().agent.memory.l2.enabled:
        return ScheduledExecutionResult(success=True, message="l2_disabled_skip", stats={})

    try:
        unified = get_unified_memory()
    except RuntimeError:
        logger.debug("Memory correction derivation skipped: unified memory unavailable")
        return ScheduledExecutionResult(
            success=True,
            message="unified_memory_unavailable_skip",
            stats={},
        )

    cognition_store = _existing_cognition_store(unified)
    if cognition_store is None:
        return ScheduledExecutionResult(
            success=True,
            message="l2_store_uninitialized_skip",
            stats={},
        )

    async with unified.memory_operation_guard():
        try:
            stats = await cognition_store.process_memory_correction_jobs(
                l3_store=getattr(unified, "l3", None),
                limit=CORRECTION_DERIVATION_BATCH_SIZE,
                recover_stale_after_seconds=DEFAULT_DERIVATION_STALE_RUNNING_SECONDS,
                max_attempts=DEFAULT_DERIVATION_MAX_ATTEMPTS,
            )
            next_wakeup_at = await cognition_store.next_memory_correction_job_wakeup_at(
                stale_after_seconds=DEFAULT_DERIVATION_STALE_RUNNING_SECONDS,
                max_attempts=DEFAULT_DERIVATION_MAX_ATTEMPTS,
            )
        except Exception as exc:
            logger.error("Memory correction derivation run failed", error=str(exc))
            return ScheduledExecutionResult(
                success=False,
                message="correction_derivation_failed",
                stats={"error": str(exc)},
            )
        retry_scheduled = False
        now = time.time()
        if (
            scheduler is not None
            and next_wakeup_at is not None
        ):
            retry_scheduled = await _schedule_correction_retry(
                scheduler,
                run_at=max(
                    float(next_wakeup_at),
                    now + CORRECTION_DERIVATION_RETRY_SCHEDULE_DELAY_SECONDS,
                ),
            )

        return ScheduledExecutionResult(
            success=True,
            message="correction_derivation_ok",
            stats={
                **stats,
                "next_wakeup_at": next_wakeup_at,
                "retry_scheduled": retry_scheduled,
            },
        )


def _existing_cognition_store(unified: Any) -> Any | None:
    cognition_store = getattr(getattr(unified, "l2_pipeline", None), "_cognition_store", None)
    if cognition_store is not None:
        return cognition_store
    return getattr(unified, "l2", None)


async def _schedule_correction_retry(
    scheduler: SchedulerService,
    *,
    run_at: float,
) -> bool:
    try:
        await scheduler.schedule_once_earliest(
            schedule_id=SCHEDULE_ID_L2_CORRECTION_RETRY,
            target_type=ScheduledTargetType.MEMORY_L2_DERIVE,
            target_key=TARGET_KEY_L2_CORRECTION_DERIVE,
            run_at=run_at,
            target_payload={"corrections_only": True},
        )
    except Exception as exc:
        logger.warning(
            "Memory correction retry scheduling failed",
            error=str(exc),
        )
        return False
    return True


def _l2_derive_skip_result(memory_cfg: Any) -> ScheduledExecutionResult | None:
    if not memory_cfg.l2.enabled:
        return ScheduledExecutionResult(success=True, message="l2_disabled_skip", stats={})
    if not memory_cfg.l2.derive_schedule_enabled:
        return ScheduledExecutionResult(
            success=True,
            message="l2_derive_disabled_skip",
            stats={},
        )
    return None


async def _build_l2_derive_context(
    l2_cfg: Any,
) -> L2DeriveContext | ScheduledExecutionResult:
    try:
        unified = get_unified_memory()
    except RuntimeError:
        logger.debug("L2 derive skipped: unified memory binding unavailable")
        return ScheduledExecutionResult(
            success=True,
            message="unified_memory_unavailable_skip",
            stats={},
        )

    if unified.l1 is None:
        return ScheduledExecutionResult(
            success=True,
            message="l1_store_uninitialized_skip",
            stats={},
        )
    if unified.l2_entity_catalog is None:
        return ScheduledExecutionResult(
            success=True,
            message="l2_catalog_uninitialized_skip",
            stats={},
        )

    cognition_store = await _resolve_cognition_store(unified)
    return L2DeriveContext(
        l2_cfg=l2_cfg,
        unified=unified,
        l1_store=unified.l1,
        cognition_store=cognition_store,
        user_id=str(CANONICAL_LOCAL_USER),
        user_entity_id=_canonical_user_entity_id(),
    )


async def _resolve_cognition_store(unified: Any) -> Any:
    cognition_store = getattr(getattr(unified, "l2_pipeline", None), "_cognition_store", None)
    if cognition_store is not None:
        return cognition_store

    from .store import L2CognitionStore

    cognition_store = L2CognitionStore(db_path=str(unified.l2_entity_catalog.db_path))
    await cognition_store.initialize()
    return cognition_store


async def _run_interest_aggregation(context: L2DeriveContext) -> int:
    if not context.l2_cfg.interest_aggregation_enabled:
        return 0
    try:
        agg_stats = await aggregate_interests(
            context.cognition_store,
            l1_store=context.l1_store,
            entity_id=context.user_entity_id,
            min_observations=int(context.l2_cfg.interest_observation_threshold),
        )
        topics_aggregated = agg_stats.get("topics_aggregated", 0)
    except Exception as exc:
        logger.warning("L2 interest aggregation failed", error=str(exc))
        return 0

    if topics_aggregated > 0:
        await _refresh_user_snapshot(
            context,
            warning_message="interest aggregation: snapshot refresh failed",
        )
    return topics_aggregated


async def _run_plugin_derived_rules(context: L2DeriveContext) -> int:
    profile_provider = getattr(
        getattr(context.unified, "l2_pipeline", None),
        "_extraction_profile_provider",
        None,
    )
    if not callable(profile_provider):
        return 0

    try:
        profiles = build_extraction_profile_registry(list(profile_provider()))
        plugin_rules = build_graph_derived_rules_from_profiles(profiles)
        assertions_written = 0
        for rule in plugin_rules:
            rule_stats = await evaluate_graph_derived_assertion_rule(
                context.cognition_store,
                rule,
                l1_store=context.l1_store,
                entity_id=context.user_entity_id,
                entity_type="user",
            )
            assertions_written += rule_stats.get("assertions_written", 0)
    except Exception as exc:
        logger.warning("L2 plugin derived assertion rules failed", error=str(exc))
        return 0

    if assertions_written > 0:
        await _refresh_user_snapshot(
            context,
            warning_message="plugin derived assertions: snapshot refresh failed",
        )
    return assertions_written


async def _run_shadow_conflict_notifications(context: L2DeriveContext) -> int:
    if not context.l2_cfg.shadow_conflict_notification_enabled:
        return 0
    try:
        from magi.notifications.service import NotificationService
        from magi.notifications.store import get_notification_store

        notification_service = NotificationService(store=get_notification_store())
        shadow_stats = await materialize_shadow_conflict_notifications(
            context.cognition_store,
            notification_service,
            user_id=context.user_id,
            entity_id=context.user_entity_id,
            entity_type="user",
        )
        return shadow_stats.get("notifications_emitted", 0)
    except Exception as exc:
        logger.warning("L2 shadow conflict notification scan failed", error=str(exc))
        return 0


async def _schedule_portrait_refresh(
    context: L2DeriveContext,
    portrait_refresh_scheduler: PortraitRefreshScheduler | None,
) -> None:
    if portrait_refresh_scheduler is None:
        return
    try:
        await portrait_refresh_scheduler(
            context.unified,
            context.user_id,
        )
    except Exception as exc:
        logger.warning("L2 derived portrait refresh scheduling failed", error=str(exc))


async def _refresh_user_snapshot(
    context: L2DeriveContext,
    *,
    warning_message: str,
) -> None:
    try:
        await context.cognition_store.refresh_entity_snapshot(
            entity_id=context.user_entity_id,
            entity_type="user",
        )
    except Exception:
        logger.warning(warning_message, exc_info=True)


class L2DeriveScheduleContrib:
    """Registers periodic L2 derivation and durable correction follow-ups."""

    def __init__(
        self,
        *,
        portrait_refresh_scheduler: PortraitRefreshScheduler | None = None,
    ) -> None:
        self._portrait_refresh_scheduler = portrait_refresh_scheduler
        self._correction_store: Any | None = None

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        async def handler(context: ScheduledExecutionContext) -> ScheduledExecutionResult:
            if bool(context.schedule.target_payload.get("corrections_only")):
                return await handle_memory_correction_derivations(
                    context,
                    scheduler=scheduler,
                )
            return await handle_l2_derive(
                context,
                portrait_refresh_scheduler=self._portrait_refresh_scheduler,
            )

        scheduler.register_handler(ScheduledTargetType.MEMORY_L2_DERIVE, handler)
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
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_L2_CORRECTION_DERIVE,
            target_type=ScheduledTargetType.MEMORY_L2_DERIVE,
            target_key=TARGET_KEY_L2_CORRECTION_DERIVE,
            seconds=CORRECTION_DERIVATION_SWEEP_INTERVAL_SECONDS,
            target_payload={"corrections_only": True},
        )
        await self._register_correction_wakeup(scheduler)
        logger.info(
            "L2 derive schedule registered",
            interval_seconds=l2_cfg.derive_schedule_interval_seconds,
            correction_sweep_interval_seconds=CORRECTION_DERIVATION_SWEEP_INTERVAL_SECONDS,
        )

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        if self._correction_store is not None:
            self._correction_store.set_memory_correction_job_wakeup(None)
            self._correction_store = None
        await scheduler.unschedule(
            SCHEDULE_ID_L2_DERIVE,
            target_type=ScheduledTargetType.MEMORY_L2_DERIVE,
            target_key=TARGET_KEY_L2_DERIVE,
        )
        await scheduler.unschedule(
            SCHEDULE_ID_L2_CORRECTION_DERIVE,
            target_type=ScheduledTargetType.MEMORY_L2_DERIVE,
            target_key=TARGET_KEY_L2_CORRECTION_DERIVE,
        )
        await self._remove_retry_schedules(scheduler)

    async def _register_correction_wakeup(self, scheduler: SchedulerService) -> None:
        try:
            unified = get_unified_memory()
        except RuntimeError:
            logger.debug("Memory correction scheduler wakeup was not bound")
            return
        cognition_store = _existing_cognition_store(unified)
        if cognition_store is None:
            return

        async def wakeup() -> None:
            result = await scheduler.execute_schedule_async(
                SCHEDULE_ID_L2_CORRECTION_DERIVE,
                manual=False,
            )
            if result.message == "target_busy":
                await _schedule_correction_retry(
                    scheduler,
                    run_at=time.time() + CORRECTION_DERIVATION_RETRY_SCHEDULE_DELAY_SECONDS,
                )

        self._correction_store = cognition_store
        cognition_store.set_memory_correction_job_wakeup(wakeup)
        await wakeup()

    @staticmethod
    async def _remove_retry_schedules(scheduler: SchedulerService) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_L2_CORRECTION_RETRY,
            target_type=ScheduledTargetType.MEMORY_L2_DERIVE,
            target_key=TARGET_KEY_L2_CORRECTION_DERIVE,
        )
