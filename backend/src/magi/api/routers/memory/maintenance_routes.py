"""Read-only product projection of memory maintenance availability."""

from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import BaseModel

from ....config import get_config
from ....memory.l1.maintenance_schedule import SCHEDULE_ID_L1_MAINTENANCE
from ....memory.l2.maintenance_schedule import SCHEDULE_ID_L2_MAINTENANCE
from ....memory.l2.consolidation_schedule import SCHEDULE_ID_L2_CONSOLIDATE
from ....memory.l2.derive_schedule import SCHEDULE_ID_L2_DERIVE, SCHEDULE_ID_L2_CORRECTION_DERIVE
from ....memory.l3.maintenance_schedule import SCHEDULE_ID_L3_MAINTENANCE
from ....memory.l3.summary_schedule import (
    SCHEDULE_ID_L3_HOUR,
    SCHEDULE_ID_L3_DAY,
    SCHEDULE_ID_L3_WEEK,
    SCHEDULE_ID_L3_MONTH,
    SCHEDULE_ID_L3_ACTIVITY_PREFIX,
)
from ....memory.l4.maintenance_schedule import SCHEDULE_ID_L4_MAINTENANCE
from .dependencies import _resolve_scheduler_service, _resolve_unified_memory
from .router import memory_router


class MemoryMaintenanceTask(BaseModel):
    id: Literal["events", "structure", "chapter", "summary", "skills"]
    status: Literal["enabled", "disabled", "paused", "partial", "unavailable"]
    schedule_count: int
    enabled_count: int
    last_run_at: float | None = None
    last_result: str | None = None


class MemoryMaintenanceResponse(BaseModel):
    tasks: list[MemoryMaintenanceTask]


@memory_router.get("/maintenance/tasks", response_model=MemoryMaintenanceResponse)
async def get_memory_maintenance_tasks() -> MemoryMaintenanceResponse:
    """Combine live layer gates, runtime availability, and durable execution history."""
    cfg = get_config().agent.memory
    unified = _resolve_unified_memory()
    scheduler = _resolve_scheduler_service()
    schedules = await scheduler.repository.list_schedules(enabled_only=False) if scheduler else []
    by_id = {schedule.schedule_id: schedule for schedule in schedules}
    summary_ids = [
        SCHEDULE_ID_L3_HOUR,
        SCHEDULE_ID_L3_DAY,
        SCHEDULE_ID_L3_WEEK,
        SCHEDULE_ID_L3_MONTH,
    ]
    summary_ids.extend(sid for sid in by_id if sid.startswith(SCHEDULE_ID_L3_ACTIVITY_PREFIX))
    groups = {
        "events": [
            (("l1",), cfg.l1.enabled and cfg.l1.maintenance_enabled, [SCHEDULE_ID_L1_MAINTENANCE])
        ],
        "structure": [
            (
                ("l2_entity_catalog",),
                cfg.l2.enabled and cfg.l2.maintenance_enabled,
                [SCHEDULE_ID_L2_MAINTENANCE],
            ),
            (
                ("l1", "l2_entity_catalog"),
                cfg.l2.enabled and cfg.l2.derive_schedule_enabled,
                [SCHEDULE_ID_L2_DERIVE],
            ),
            (("l2",), cfg.l2.enabled, [SCHEDULE_ID_L2_CORRECTION_DERIVE]),
        ],
        "chapter": [
            (("l2",), cfg.l2.enabled and cfg.l2.consolidation_enabled, [SCHEDULE_ID_L2_CONSOLIDATE])
        ],
        "summary": [
            (("l1", "l3"), cfg.l3.enabled, summary_ids),
            (("l3",), cfg.l3.enabled and cfg.l3.maintenance_enabled, [SCHEDULE_ID_L3_MAINTENANCE]),
        ],
        "skills": [
            (("l4",), cfg.l4.enabled and cfg.l4.maintenance_enabled, [SCHEDULE_ID_L4_MAINTENANCE])
        ],
    }
    task_ids = {sid for parts in groups.values() for _, _, ids in parts for sid in ids}
    executions = (
        await asyncio.gather(
            *(
                scheduler.repository.list_executions(schedule_id=sid, limit=1)
                for sid in sorted(task_ids)
            )
        )
        if scheduler
        else []
    )
    latest_by_id = dict(zip(sorted(task_ids), executions))
    tasks = []
    for task_id, parts in groups.items():
        states = []
        history = []
        for required_stores, configured, schedule_ids in parts:
            for schedule_id in schedule_ids:
                history.extend(latest_by_id.get(schedule_id, []))
                schedule = by_id.get(schedule_id)
                if not configured:
                    states.append("disabled")
                elif (
                    scheduler is None
                    or any(getattr(unified, store, None) is None for store in required_stores)
                    or schedule is None
                ):
                    states.append("unavailable")
                else:
                    states.append(scheduler.get_schedule_availability(schedule))
        latest = max(
            history,
            key=lambda row: row.get("started_at") or row.get("created_at") or 0,
            default=None,
        )
        last_result = latest.get("status") if latest else None
        if last_result == "success" and str(latest.get("result_message") or "").endswith("_skip"):
            last_result = "skipped"
        enabled_count = states.count("enabled")
        if enabled_count:
            status = "enabled" if enabled_count == len(states) else "partial"
        else:
            status = next(state for state in ("unavailable", "paused", "disabled") if state in states)
        tasks.append(
            MemoryMaintenanceTask(
                id=task_id,
                status=status,
                schedule_count=len(states),
                enabled_count=enabled_count,
                last_run_at=latest.get("started_at") if latest else None,
                last_result=last_result,
            )
        )
    return MemoryMaintenanceResponse(tasks=tasks)
