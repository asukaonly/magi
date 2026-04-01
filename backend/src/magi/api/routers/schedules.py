"""Scheduler management API router."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ...core.runtime_bindings import require_scheduler_service
from ...scheduler import (
    ScheduleDefinition,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)

schedules_router = APIRouter()


class TriggerRequest(BaseModel):
    trigger_type: str = Field(..., description="once | interval | cron")
    config: dict[str, Any] = Field(default_factory=dict)


class ScheduleCreateRequest(BaseModel):
    schedule_id: str = Field(..., min_length=1, max_length=256)
    target_type: str = Field(..., description="Scheduled target type")
    target_key: str = Field(..., min_length=1)
    trigger: TriggerRequest
    target_payload: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScheduleUpdateRequest(BaseModel):
    trigger: Optional[TriggerRequest] = None
    target_payload: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None
    metadata: Optional[dict[str, Any]] = None


def _serialize_schedule(s: ScheduleDefinition) -> dict[str, Any]:
    return {
        "schedule_id": s.schedule_id,
        "target_type": s.target_type.value,
        "target_key": s.target_key,
        "trigger": {
            "trigger_type": s.trigger.trigger_type.value,
            "config": s.trigger.config,
        },
        "target_payload": s.target_payload,
        "enabled": s.enabled,
        "metadata": s.metadata,
        "job_id": s.job_id,
    }


def _resolve_target_type(raw: str) -> ScheduledTargetType:
    try:
        return ScheduledTargetType(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown target type: {raw}. Valid: {[t.value for t in ScheduledTargetType]}",
        )


def _resolve_trigger_type(raw: str) -> TriggerType:
    try:
        return TriggerType(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown trigger type: {raw}. Valid: {[t.value for t in TriggerType]}",
        )


@schedules_router.get("/")
async def list_schedules(enabled_only: bool = False):
    """List all schedules."""
    service = require_scheduler_service()
    schedules = await service.repository.list_schedules(enabled_only=enabled_only)
    return {"schedules": [_serialize_schedule(s) for s in schedules]}


@schedules_router.get("/{schedule_id}")
async def get_schedule(schedule_id: str):
    """Get a single schedule by id."""
    service = require_scheduler_service()
    schedule = await service.repository.get_schedule(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    state = await service.repository.get_target_state(schedule.target_type, schedule.target_key)
    return {
        "schedule": _serialize_schedule(schedule),
        "target_state": asdict(state),
    }


@schedules_router.post("/", status_code=status.HTTP_201_CREATED)
async def create_schedule(body: ScheduleCreateRequest):
    """Create or replace a schedule."""
    target_type = _resolve_target_type(body.target_type)
    trigger_type = _resolve_trigger_type(body.trigger.trigger_type)
    definition = ScheduleDefinition(
        schedule_id=body.schedule_id,
        target_type=target_type,
        target_key=body.target_key,
        trigger=TriggerDefinition(trigger_type=trigger_type, config=body.trigger.config),
        target_payload=body.target_payload,
        enabled=body.enabled,
        metadata=body.metadata,
    )
    service = require_scheduler_service()
    result = await service.schedule(definition)
    return {"schedule": _serialize_schedule(result)}


@schedules_router.patch("/{schedule_id}")
async def update_schedule(schedule_id: str, body: ScheduleUpdateRequest):
    """Partially update an existing schedule."""
    service = require_scheduler_service()
    existing = await service.repository.get_schedule(schedule_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")

    trigger = existing.trigger
    if body.trigger is not None:
        trigger = TriggerDefinition(
            trigger_type=_resolve_trigger_type(body.trigger.trigger_type),
            config=body.trigger.config,
        )

    updated = ScheduleDefinition(
        schedule_id=existing.schedule_id,
        target_type=existing.target_type,
        target_key=existing.target_key,
        trigger=trigger,
        target_payload=body.target_payload if body.target_payload is not None else existing.target_payload,
        enabled=body.enabled if body.enabled is not None else existing.enabled,
        metadata=body.metadata if body.metadata is not None else existing.metadata,
        job_id=existing.job_id,
    )
    result = await service.schedule(updated)
    return {"schedule": _serialize_schedule(result)}


@schedules_router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(schedule_id: str):
    """Delete a schedule and remove its APScheduler job."""
    service = require_scheduler_service()
    existing = await service.repository.get_schedule(schedule_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    await service.unschedule(
        schedule_id,
        target_type=existing.target_type,
        target_key=existing.target_key,
    )


@schedules_router.post("/{schedule_id}/trigger")
async def trigger_schedule(schedule_id: str):
    """Manually trigger a schedule to run immediately."""
    service = require_scheduler_service()
    existing = await service.repository.get_schedule(schedule_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    try:
        result = await service.execute_schedule(schedule_id, manual=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    return {
        "success": result.success,
        "message": result.message,
        "stats": result.stats,
    }


@schedules_router.get("/{schedule_id}/executions")
async def list_executions(schedule_id: str, limit: int = 20):
    """List recent execution records for a schedule."""
    service = require_scheduler_service()
    executions = await service.repository.list_executions(schedule_id=schedule_id, limit=min(limit, 100))
    return {"executions": executions}


@schedules_router.get("/executions/recent")
async def list_recent_executions(limit: int = 20):
    """List recent execution records across all schedules."""
    service = require_scheduler_service()
    executions = await service.repository.list_executions(limit=min(limit, 100))
    return {"executions": executions}
