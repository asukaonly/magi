"""Scheduler integration for periodic L2 derived-data generation.

Runs interest aggregation and shadow-conflict-notification materialization on
an independent cadence (default 6 h) completely separate from the L2 ops
maintenance task (entity/graph hygiene, embedding cleanup, promotion-counter
prune).  This separation lets business-derived data refresh more frequently or
less frequently than housekeeping without coupling the two.
"""

from __future__ import annotations

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
from .extraction_profiles import build_extraction_profile_registry

logger = get_logger(__name__)

SCHEDULE_ID_L2_DERIVE = "memory-l2-derive:global"
TARGET_KEY_L2_DERIVE = "memory_l2_derive"


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

    interest_topics_aggregated = await _run_interest_aggregation(derive_context)
    plugin_derived_assertions_written = await _run_plugin_derived_rules(derive_context)
    shadow_notifications_emitted = await _run_shadow_conflict_notifications(derive_context)

    return ScheduledExecutionResult(
        success=True,
        message="derive_ok",
        stats={
            "interest_topics_aggregated": interest_topics_aggregated,
            "plugin_derived_assertions_written": plugin_derived_assertions_written,
            "shadow_notifications_emitted": shadow_notifications_emitted,
        },
    )


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
