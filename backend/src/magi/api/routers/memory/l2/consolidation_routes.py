"""Experience processing state and coalesced retry requests."""

from typing import Any

from fastapi import HTTPException

from magi.config import get_config
from magi.memory.l2.consolidation_schedule import (
    TARGET_KEY_L2_CONSOLIDATE,
    request_l2_consolidation,
)
from magi.scheduler.contracts import ScheduledTargetType
from ..dependencies import _resolve_scheduler_service, _resolve_unified_memory
from ..router import memory_router


@memory_router.get("/l2/consolidation")
async def get_consolidation_status() -> dict[str, Any]:
    config = get_config().agent.memory.l2
    unified = _resolve_unified_memory()
    scheduler = _resolve_scheduler_service()
    if not config.enabled or not config.consolidation_enabled:
        return {"state": "disabled", "reason_code": "disabled", "stats": {}, "pending_events": 0}
    if unified is None or unified.l2 is None or scheduler is None:
        return {
            "state": "unavailable",
            "reason_code": "unavailable",
            "stats": {},
            "pending_events": 0,
        }
    target = await scheduler.get_target_state(
        ScheduledTargetType.MEMORY_L2_CONSOLIDATE, TARGET_KEY_L2_CONSOLIDATE
    )
    backlog = await unified.l2.get_projection_backlog_stats()
    pending = sum(int(backlog.get(key, 0)) for key in ("pending", "claimed"))
    requested = await scheduler.get_schedule("memory-l2-consolidate:requested")
    stats = dict(target.stats or {}) if target else {}
    if target and target.running:
        state = reason = "running"
    elif requested is not None and requested.enabled:
        state = reason = "queued"
    elif target and target.last_error:
        state = "failed"
        reason = (
            "partial_failure" if target.last_error == "consolidation_partial_failure" else "failed"
        )
    elif pending:
        state, reason = "waiting", "processing_events"
    elif not target or target.last_run_at is None:
        state, reason = "waiting", "not_run"
    elif stats.get("experience_deferred", 0):
        state, reason = "waiting", "model_budget"
    elif stats.get("experience_candidates", 0) or stats.get("experiences_promoted", 0):
        state, reason = "ready", "ready"
    else:
        state, reason = "insufficient_evidence", "insufficient_evidence"
    return {
        "state": state,
        "reason_code": reason,
        "pending_events": pending,
        "last_run_at": target.last_run_at if target else None,
        "last_success_at": target.last_success_at if target else None,
        "model_selection": (
            "disabled"
            if not config.experience_seed_llm_selection_enabled
            else "enabled"
            if vars(unified).get("scenario_llm_pool") is not None
            else "unavailable"
        ),
        "stats": {
            key: stats[key]
            for key in (
                "experience_candidates",
                "experiences_promoted",
                "experience_deferred",
                "experience_rejected",
                "episodic_summaries_generated",
                "experience_summaries_generated",
                "duration_seconds",
                "selector_diagnostics",
            )
            if key in stats
        },
    }


@memory_router.post("/l2/consolidation")
async def request_consolidation() -> dict[str, bool]:
    scheduler = _resolve_scheduler_service()
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Memory scheduler is unavailable")
    return {"scheduled": await request_l2_consolidation(scheduler, reason="user_requested")}
