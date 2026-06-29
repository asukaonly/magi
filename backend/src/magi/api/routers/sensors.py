"""Sensor operations API router."""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from datetime import date, datetime, time as datetime_time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ...config import get_config
from ...core.runtime_bindings import require_runtime_command_queue
from ...events.contracts import SensorStateFlushCommand, SensorSyncCommand
from ... import i18n as core_i18n
from ...memory.provider import get_unified_memory
from ...plugins.provider import resolve_plugin_manager, resolve_sensor_registry
from ...utils.runtime import get_runtime_paths
from .sensor_status_projection import (
    _derive_sensor_status,
    _get_nested_value,
    build_sensor_source_status_payload,
)

sensors_router = APIRouter()

logger = logging.getLogger(__name__)

__all__ = ["_derive_sensor_status", "sensors_router"]

class SensorSourceAuthorizationRequest(BaseModel):
    field_values: dict[str, Any] = Field(default_factory=dict)


@sensors_router.get("/status")
async def get_sensor_source_status():
    get_config()
    runtime_paths = get_runtime_paths()
    try:
        manager = resolve_plugin_manager()
    except RuntimeError:
        return []
    sensor_registry = resolve_sensor_registry()
    return await build_sensor_source_status_payload(
        runtime_paths=runtime_paths,
        manager=manager,
        sensor_registry=sensor_registry,
    )

@sensors_router.post("/{source_name}/sync")
async def trigger_sensor_source_sync(source_name: str):
    _ = get_config()
    sensor_registry = resolve_sensor_registry()
    resolved = sensor_registry.resolve_source_sensor(source_name)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t("sensors.errors.source_not_found", fallback="Sensor source not found"),
        )
    _, _, sensor, _ = resolved
    if not bool(getattr(sensor, "supports_pull_sync", False)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t(
                "sensors.errors.pull_sync_unsupported",
                fallback="Sensor source does not support pull sync: {source_name}",
                source_name=source_name,
            ),
        )
    try:
        runtime_command_queue = require_runtime_command_queue()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=core_i18n.t("sensors.errors.scheduler_unavailable", fallback="Scheduler unavailable"),
        ) from exc
    command_id = await runtime_command_queue.enqueue_sensor_sync(
        SensorSyncCommand(
            source="api.sensors",
            source_name=source_name,
        )
    )
    return {"queued": True, "source_name": source_name, "command_id": command_id}


@sensors_router.post("/{source_name}/flush-state")
async def trigger_sensor_state_flush(source_name: str):
    _ = get_config()
    sensor_registry = resolve_sensor_registry()
    resolved = sensor_registry.resolve_source_sensor(source_name)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t("sensors.errors.source_not_found", fallback="Sensor source not found"),
        )
    _, _, sensor, _ = resolved
    if not bool(getattr(sensor, "supports_state_flush", False)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t(
                "sensors.errors.state_flush_unsupported",
                fallback="Sensor source does not support state flush: {source_name}",
                source_name=source_name,
            ),
        )
    try:
        runtime_command_queue = require_runtime_command_queue()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=core_i18n.t("sensors.errors.scheduler_unavailable", fallback="Scheduler unavailable"),
        ) from exc
    command_id = await runtime_command_queue.enqueue_sensor_state_flush(
        SensorStateFlushCommand(
            source="api.sensors",
            source_name=source_name,
        )
    )
    return {"queued": True, "source_name": source_name, "command_id": command_id}


@sensors_router.post("/{source_name}/authorize")
async def authorize_sensor_source(source_name: str, request: SensorSourceAuthorizationRequest):
    _ = get_config()
    sensor_registry = resolve_sensor_registry()
    resolved = sensor_registry.resolve_source_sensor(source_name)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t("sensors.errors.source_not_found", fallback="Sensor source not found"),
        )

    _, _, sensor, _ = resolved
    authorize = getattr(sensor, "request_activation_authorization", None)
    if not callable(authorize):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t(
                "sensors.errors.authorization_unsupported",
                fallback="Sensor source does not support authorization",
            ),
        )

    result = authorize(dict(request.field_values))
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=core_i18n.t(
                "sensors.errors.authorization_invalid_response",
                fallback="Sensor source authorization returned an invalid response",
            ),
        )
    return result


def _resolve_day_range(day_value: str | None) -> tuple[date, float, float]:
    """Parse an optional ``YYYY-MM-DD`` string into a server-local day range."""
    normalized = str(day_value or "").strip()
    if not normalized:
        target_day = date.today()
    else:
        try:
            target_day = date.fromisoformat(normalized)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=core_i18n.t(
                    "sensors.errors.invalid_date",
                    fallback="Invalid date value: {value}",
                    value=normalized,
                ),
            ) from exc
    start_time = datetime.combine(target_day, datetime_time.min).timestamp()
    end_time = datetime.combine(target_day, datetime_time.max).timestamp()
    return target_day, start_time, end_time


@sensors_router.get("/today-summary")
async def get_sensor_today_summary(
    day: str | None = Query(default=None, description="Optional ISO date (YYYY-MM-DD); defaults to server-local today."),
):
    """Return per-source L1 event counts for the requested day.

    Powers the chat shell's "today context strip". Joins the day's L1 event
    count grouped by ``source`` with sensor contribution metadata so the UI
    can render human-friendly labels without a second round trip.
    """
    target_day, start_time, end_time = _resolve_day_range(day)

    try:
        unified_memory = get_unified_memory()
    except RuntimeError:
        unified_memory = None

    counts_by_source: dict[str, int] = {}
    last_event_by_source: dict[str, float | None] = {}
    if unified_memory is not None and unified_memory.l1:
        rows = await unified_memory.l1.summarize_event_sources(
            start_time=start_time,
            end_time=end_time,
        )
        for row in rows:
            source_name = str(row.get("source") or "").strip()
            if not source_name:
                continue
            counts_by_source[source_name] = int(row.get("event_count") or 0)
            max_ts = row.get("max_timestamp")
            last_event_by_source[source_name] = float(max_ts) if max_ts is not None else None

    sensor_metadata: dict[str, dict[str, Any]] = {}
    try:
        manager = resolve_plugin_manager()
    except RuntimeError:
        manager = None
    if manager is not None:
        sensor_registry = resolve_sensor_registry()
        packages = {state.manifest.plugin_id: state for state in manager.list_packages()}
        for item in sensor_registry.list_contributions():
            source_name = str(item.metadata.get("source_type") or item.contribution_id.split(".")[-1])
            current_settings = (
                packages.get(item.plugin_id).current_settings
                if packages.get(item.plugin_id) is not None
                else {}
            )
            enabled = bool(
                _get_nested_value(
                    current_settings,
                    f"sensors.{source_name}.enabled",
                    item.metadata.get("default_settings", {}).get("enabled", True),
                )
            )
            sensor_metadata[source_name] = {
                "plugin_id": item.plugin_id,
                "display_name": item.display_name,
                "enabled": enabled,
            }

    sources: list[dict[str, Any]] = []
    seen_source_names: set[str] = set()
    for source_name, count in counts_by_source.items():
        meta = sensor_metadata.get(source_name, {})
        sources.append(
            {
                "source_name": source_name,
                "plugin_id": meta.get("plugin_id"),
                "display_name": meta.get("display_name") or source_name,
                "enabled": bool(meta.get("enabled", True)),
                "count": count,
                "last_event_at": last_event_by_source.get(source_name),
            }
        )
        seen_source_names.add(source_name)

    # Surface enabled sensors with zero events so the UI can decide whether to
    # show a quiet placeholder rather than hide the sensor entirely.
    for source_name, meta in sensor_metadata.items():
        if source_name in seen_source_names:
            continue
        if not meta.get("enabled", True):
            continue
        sources.append(
            {
                "source_name": source_name,
                "plugin_id": meta.get("plugin_id"),
                "display_name": meta.get("display_name") or source_name,
                "enabled": True,
                "count": 0,
                "last_event_at": None,
            }
        )

    sources.sort(key=lambda entry: (-int(entry["count"]), str(entry["source_name"])))

    return {
        "date": target_day.isoformat(),
        "weekday": target_day.weekday(),
        "sources": sources,
    }


class MemoryReadinessResponse(BaseModel):
    source_name: str
    l1_event_count: int
    l2_ready: bool


@sensors_router.get("/{source_name}/memory-readiness", response_model=MemoryReadinessResponse)
async def get_sensor_memory_readiness(
    source_name: str,
    max_wait_ms: int = Query(
        default=20000,
        ge=0,
        le=60000,
        description="Max time to wait for the L2 projection backlog to drain before reporting not-ready.",
    ),
):
    """Honest readiness: count this source's L1 events, force an L2 flush, then poll
    the projection backlog until it drains (or the bounded wait elapses)."""
    try:
        unified_memory = get_unified_memory()
    except RuntimeError:
        unified_memory = None

    if unified_memory is None or getattr(unified_memory, "l1", None) is None:
        return MemoryReadinessResponse(source_name=source_name, l1_event_count=0, l2_ready=False)

    rows = await unified_memory.l1.summarize_event_sources(source_filters=[source_name])
    l1_count = sum(int((r or {}).get("event_count") or 0) for r in (rows or []))
    if l1_count == 0:
        return MemoryReadinessResponse(source_name=source_name, l1_event_count=0, l2_ready=False)

    # Force staged L2 micro-batches into projection jobs now (don't wait the ~60s worker interval).
    try:
        await unified_memory.flush_l2_microbatches()
    except Exception:  # best-effort; readiness falls back to polling
        logger.exception("memory-readiness: L2 flush failed for %s", source_name)

    deadline = time.monotonic() + (max_wait_ms / 1000.0)
    l2_ready = False
    while True:
        backlog = await unified_memory.get_l2_projection_backlog()
        pending = int((backlog or {}).get("pending", 0))
        claimed = int((backlog or {}).get("claimed", 0))
        if pending == 0 and claimed == 0:
            l2_ready = True
            break
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(0.5)

    return MemoryReadinessResponse(source_name=source_name, l1_event_count=l1_count, l2_ready=l2_ready)
