"""Scheduler task management REST endpoints."""

from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from ...core.runtime_bindings import require_scheduler_service
from ...scheduler.contracts import (
    ScheduleDefinition,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)
from ...scheduler.repository import ScheduleRepository
from ...utils.runtime import get_runtime_paths

schedules_router = APIRouter()


class ScheduleTriggerBody(BaseModel):
    trigger_type: TriggerType
    config: dict[str, Any] = Field(default_factory=dict)


class ScheduleUpdateBody(BaseModel):
    trigger: Optional[ScheduleTriggerBody] = None
    target_payload: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None
    metadata: Optional[dict[str, Any]] = None


class ScheduleCreateBody(BaseModel):
    schedule_id: str = Field(min_length=1, max_length=300)
    target_type: ScheduledTargetType
    target_key: str = Field(min_length=1, max_length=300)
    trigger: ScheduleTriggerBody
    target_payload: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActivityCancelBody(BaseModel):
    reason: str = Field(default="cancelled_by_user", max_length=200)


def _repository() -> ScheduleRepository:
    runtime_paths = get_runtime_paths()
    scheduler_db_path = getattr(
        runtime_paths,
        "scheduler_db_path",
        Path(runtime_paths.base_dir) / "runtime" / "scheduler.db",
    )
    return ScheduleRepository(scheduler_db_path)


def _serialize_state(state) -> dict[str, Any]:
    return {
        "target_type": state.target_type.value,
        "target_key": state.target_key,
        "running": state.running,
        "last_run_at": state.last_run_at,
        "last_success_at": state.last_success_at,
        "last_error": state.last_error,
        "last_cursor": state.last_cursor,
        "watermark_ts": state.watermark_ts,
        "next_run_at": state.next_run_at,
        "scheduler_job_id": state.scheduler_job_id,
        "updated_at": state.updated_at,
        "stats": state.stats,
    }


def _serialize_schedule(schedule: ScheduleDefinition, state=None) -> dict[str, Any]:
    metadata = dict(schedule.metadata or {})
    editable = schedule.target_type is not ScheduledTargetType.SENSOR_SYNC
    if schedule.target_type is ScheduledTargetType.SENSOR_SYNC:
        owner_kind = "sensor_settings"
    elif schedule.target_type is ScheduledTargetType.USER_AGENT_TASK:
        owner_kind = "agent_created"
    else:
        owner_kind = "system"
    payload = dict(schedule.target_payload or {})
    source_name = payload.get("source_type") or metadata.get("source_type")
    settings_link = (
        {"section": "timeline", "source_name": source_name}
        if schedule.target_type is ScheduledTargetType.SENSOR_SYNC and source_name
        else None
    )
    return {
        "schedule_id": schedule.schedule_id,
        "target_type": schedule.target_type.value,
        "target_key": schedule.target_key,
        "trigger": {
            "trigger_type": schedule.trigger.trigger_type.value,
            "config": schedule.trigger.config,
        },
        "target_payload": payload,
        "enabled": schedule.enabled,
        "metadata": metadata,
        "job_id": schedule.job_id,
        "editable": editable,
        "owner_kind": owner_kind,
        "settings_link": settings_link,
        "target_state": _serialize_state(state) if state is not None else None,
    }


def _schedule_title(schedule: ScheduleDefinition) -> str:
    metadata = schedule.metadata or {}
    payload = schedule.target_payload or {}
    for key in ("display_name", "title", "source_type", "plugin_id"):
        value = metadata.get(key) or payload.get(key)
        if value:
            return str(value)
    return schedule.schedule_id


@schedules_router.get("")
async def list_schedules(
    enabled_only: bool = Query(default=False),
) -> dict[str, Any]:
    repository = _repository()
    await repository.initialize()
    schedules = await repository.list_schedules(enabled_only=enabled_only)
    items = []
    for schedule in schedules:
        state = await repository.get_schedule_runtime_state(schedule)
        items.append(_serialize_schedule(schedule, state))
    return {"schedules": items}


@schedules_router.post("", status_code=status.HTTP_201_CREATED)
async def create_schedule(body: ScheduleCreateBody) -> dict[str, Any]:
    schedule = ScheduleDefinition(
        schedule_id=body.schedule_id,
        target_type=body.target_type,
        target_key=body.target_key,
        trigger=TriggerDefinition(body.trigger.trigger_type, dict(body.trigger.config)),
        target_payload=dict(body.target_payload),
        enabled=body.enabled,
        metadata=dict(body.metadata),
        job_id=body.schedule_id,
    )
    repository = _repository()
    await repository.initialize()
    try:
        scheduler_service = require_scheduler_service()
    except RuntimeError:
        await repository.upsert_schedule(schedule)
        saved = await repository.get_schedule(schedule.schedule_id)
    else:
        saved = await scheduler_service.schedule(schedule)
    state = await repository.get_schedule_runtime_state(saved or schedule)
    return {"schedule": _serialize_schedule(saved or schedule, state)}


@schedules_router.get("/activity")
async def list_schedule_activity(
    limit: int = Query(default=100, ge=1, le=300),
) -> dict[str, Any]:
    repository = _repository()
    await repository.initialize()
    schedules = await repository.list_schedules(enabled_only=True)
    activities: list[dict[str, Any]] = []
    schedule_by_id = {schedule.schedule_id: schedule for schedule in schedules}

    for job in await repository.list_outstanding_sensor_sync_jobs(limit=limit):
        schedule = schedule_by_id.get(str(job["schedule_id"]))
        title = _schedule_title(schedule) if schedule is not None else str(job["source_type"])
        queued = str(job["status"]) == "queued"
        activities.append(
            {
                "activity_id": f"sensor_job:{job['job_id']}",
                "schedule_id": job["schedule_id"],
                "title": title,
                "target_type": job["target_type"],
                "target_key": job["target_key"],
                "status": job["status"],
                "planned_at": job["created_at"],
                "started_at": job["started_at"],
                "duration_ms": None,
                "cancellable": queued,
                "cancel_kind": "sensor_sync_job" if queued else None,
                "error": job["error"],
            }
        )

    for schedule in schedules:
        state = await repository.get_schedule_runtime_state(schedule)
        if state.running and schedule.target_type is not ScheduledTargetType.SENSOR_SYNC:
            activities.append(
                {
                    "activity_id": f"target:{schedule.target_type.value}:{schedule.target_key}",
                    "schedule_id": schedule.schedule_id,
                    "title": _schedule_title(schedule),
                    "target_type": schedule.target_type.value,
                    "target_key": schedule.target_key,
                    "status": "running",
                    "planned_at": None,
                    "started_at": state.last_run_at,
                    "duration_ms": (
                        max(0.0, (time.time() - state.last_run_at) * 1000.0)
                        if state.last_run_at
                        else None
                    ),
                    "cancellable": False,
                    "cancel_kind": None,
                    "error": state.last_error,
                }
            )
        if state.next_run_at is not None and not state.running:
            activities.append(
                {
                    "activity_id": f"upcoming:{schedule.schedule_id}",
                    "schedule_id": schedule.schedule_id,
                    "title": _schedule_title(schedule),
                    "target_type": schedule.target_type.value,
                    "target_key": schedule.target_key,
                    "status": "upcoming",
                    "planned_at": state.next_run_at,
                    "started_at": None,
                    "duration_ms": None,
                    "cancellable": False,
                    "cancel_kind": None,
                    "error": state.last_error,
                }
            )

    activities.sort(key=lambda item: (item["status"] != "running", item.get("planned_at") or 0))
    return {"activities": activities[:limit]}


@schedules_router.patch("/{schedule_id}")
async def update_schedule(schedule_id: str, body: ScheduleUpdateBody) -> dict[str, Any]:
    repository = _repository()
    await repository.initialize()
    existing = await repository.get_schedule(schedule_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    if existing.target_type is ScheduledTargetType.SENSOR_SYNC:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sensor schedules must be updated from sensor settings",
        )

    next_schedule = ScheduleDefinition(
        schedule_id=existing.schedule_id,
        target_type=existing.target_type,
        target_key=existing.target_key,
        trigger=(
            TriggerDefinition(body.trigger.trigger_type, dict(body.trigger.config))
            if body.trigger is not None
            else existing.trigger
        ),
        target_payload=(
            dict(body.target_payload)
            if body.target_payload is not None
            else dict(existing.target_payload)
        ),
        enabled=body.enabled if body.enabled is not None else existing.enabled,
        metadata=dict(body.metadata) if body.metadata is not None else dict(existing.metadata),
        job_id=existing.job_id,
    )
    try:
        scheduler_service = require_scheduler_service()
    except RuntimeError:
        await repository.upsert_schedule(next_schedule)
        saved = await repository.get_schedule(schedule_id)
    else:
        saved = await scheduler_service.schedule(next_schedule)
    state = await repository.get_schedule_runtime_state(saved or next_schedule)
    return {"schedule": _serialize_schedule(saved or next_schedule, state)}


@schedules_router.get("/{schedule_id}")
async def get_schedule(schedule_id: str) -> dict[str, Any]:
    repository = _repository()
    await repository.initialize()
    schedule = await repository.get_schedule(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    state = await repository.get_schedule_runtime_state(schedule)
    return {"schedule": _serialize_schedule(schedule, state)}


@schedules_router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(schedule_id: str) -> Response:
    repository = _repository()
    await repository.initialize()
    existing = await repository.get_schedule(schedule_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    try:
        scheduler_service = require_scheduler_service()
    except RuntimeError:
        await repository.clear_target_schedule_binding(existing.target_type, existing.target_key)
        await repository.delete_schedule(schedule_id)
    else:
        await scheduler_service.unschedule(
            schedule_id,
            target_type=existing.target_type,
            target_key=existing.target_key,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@schedules_router.post("/{schedule_id}/run")
async def run_schedule_now(schedule_id: str) -> dict[str, Any]:
    repository = _repository()
    await repository.initialize()
    existing = await repository.get_schedule(schedule_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    try:
        scheduler_service = require_scheduler_service()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler service is not available",
        ) from exc

    result = await scheduler_service.execute_schedule(schedule_id, manual=True)
    if not result.success:
        if result.message == "schedule_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
        if result.message == "target_busy":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Schedule target is busy")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.message)

    saved = await repository.get_schedule(schedule_id)
    state = await repository.get_schedule_runtime_state(saved or existing)
    return {
        "schedule": _serialize_schedule(saved or existing, state),
        "result": asdict(result),
    }


@schedules_router.post("/activity/{activity_id}/cancel")
async def cancel_schedule_activity(
    activity_id: str,
    body: Optional[ActivityCancelBody] = None,
) -> dict[str, Any]:
    repository = _repository()
    await repository.initialize()
    reason = (body.reason if body is not None else "cancelled_by_user") or "cancelled_by_user"
    if not activity_id.startswith("sensor_job:"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Activity is not cancellable",
        )
    job_id = activity_id.split(":", 1)[1]
    job = await repository.cancel_queued_sensor_sync_job(job_id, reason=reason)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Activity is not cancellable",
        )
    return {
        "activity": {
            "activity_id": activity_id,
            "status": job["status"],
            "job_id": job["job_id"],
        }
    }


__all__ = ["schedules_router"]
