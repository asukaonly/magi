"""Scheduler integration for periodic L3 digest generation."""

from __future__ import annotations

import time

from ...config import get_config
from ...core.logger import get_logger
from ...core.runtime_bindings import require_unified_memory
from ...personality.current_state import get_current_personality
from ...personality.loader import get_personality_loader
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from ...scheduler.service import SchedulerService

logger = get_logger(__name__)

SCHEDULE_ID_L3_DIGEST = "memory:l3:digest"
TARGET_KEY_L3_DIGEST = "l3_digest"

# Summary categories to generate per digest cycle.
_DIGEST_CATEGORIES = ("day",)
_DIGEST_DAY_SECONDS = 24 * 60 * 60


def _build_persona_context() -> dict[str, str] | None:
    """Load active personality and return a digest-compatible context dict."""
    try:
        name = get_current_personality()
        if not name or name == "default":
            return None
        loader = get_personality_loader()
        config = loader.load(name)
        persona = config.persona_entity
        return {
            "name": persona.basic_profile.name,
            "tone": persona.core_identity.language_fingerprint,
            "background": persona.core_identity.inner_narrative,
            "keywords": persona.core_identity.attention_bias,
        }
    except Exception as exc:
        logger.debug("Could not load personality for digest: %s", exc)
        return None


async def handle_l3_digest(
    context: ScheduledExecutionContext,
) -> ScheduledExecutionResult:
    """Generate temporal digests for the most recent completed day."""
    memory_cfg = get_config().agent.memory
    if not memory_cfg.l3.enabled or not memory_cfg.l3.digest_enabled:
        return ScheduledExecutionResult(success=True, message="l3_digest_disabled_skip", stats={})

    try:
        unified = require_unified_memory()
    except RuntimeError:
        logger.debug("L3 digest skipped: unified memory binding unavailable")
        return ScheduledExecutionResult(success=True, message="unified_memory_unavailable_skip", stats={})

    l1 = getattr(unified, "l1", None)
    l3 = getattr(unified, "l3", None)
    if l1 is None or l3 is None:
        return ScheduledExecutionResult(success=True, message="l1_or_l3_unavailable_skip", stats={})

    persona_context = _build_persona_context()
    now = time.time()
    generated = 0
    errors = 0

    for category in _DIGEST_CATEGORIES:
        period_end = now
        period_start = now - _DIGEST_DAY_SECONDS
        try:
            summary = await l3.generate_temporal_summary(
                l1_store=l1,
                summary_category=category,
                period_start=period_start,
                period_end=period_end,
                persona_context=persona_context,
            )
            if summary is not None:
                generated += 1
                logger.info(
                    "L3 digest generated",
                    category=category,
                    summary_id=summary.get("summary_id"),
                )
        except Exception as exc:
            errors += 1
            logger.error("L3 digest generation failed", category=category, error=str(exc))

    return ScheduledExecutionResult(
        success=errors == 0,
        message="digest_ok" if errors == 0 else "digest_partial",
        stats={"generated": generated, "errors": errors},
    )


class L3DigestScheduleContrib:
    """Registers MEMORY_L3_DIGEST handler and periodic interval schedule."""

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        scheduler.register_handler(ScheduledTargetType.MEMORY_L3_DIGEST, handle_l3_digest)
        l3_cfg = get_config().agent.memory.l3
        if l3_cfg.digest_enabled:
            await scheduler.schedule_interval(
                schedule_id=SCHEDULE_ID_L3_DIGEST,
                target_type=ScheduledTargetType.MEMORY_L3_DIGEST,
                target_key=TARGET_KEY_L3_DIGEST,
                seconds=float(l3_cfg.digest_interval_hours * 3600),
                target_payload={},
            )
            logger.info(
                "L3 digest schedule registered",
                interval_hours=l3_cfg.digest_interval_hours,
            )
        else:
            await scheduler.unschedule(
                SCHEDULE_ID_L3_DIGEST,
                target_type=ScheduledTargetType.MEMORY_L3_DIGEST,
                target_key=TARGET_KEY_L3_DIGEST,
            )
            logger.info("L3 digest schedule disabled by config")

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_L3_DIGEST,
            target_type=ScheduledTargetType.MEMORY_L3_DIGEST,
            target_key=TARGET_KEY_L3_DIGEST,
        )
