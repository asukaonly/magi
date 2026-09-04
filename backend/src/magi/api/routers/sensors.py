"""Sensor operations API router."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator

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
    _resolve_source_settings,
    build_sensor_source_status_payload,
)

sensors_router = APIRouter()

logger = logging.getLogger(__name__)

__all__ = ["_derive_sensor_status", "sensors_router"]


class SensorSourceAuthorizationRequest(BaseModel):
    field_values: dict[str, Any] = Field(default_factory=dict)


class SensorSourceSyncRequest(BaseModel):
    first_context: bool = False
    mode: Literal["latest", "backfill"] = "latest"
    backfill_scope: Literal["last_7_days", "last_30_days", "full", "custom"] | None = None
    backfill_start_date: date | None = None
    backfill_end_date: date | None = None

    @model_validator(mode="after")
    def _validate_custom_backfill_range(self) -> "SensorSourceSyncRequest":
        if self.mode != "backfill" or self.backfill_scope != "custom":
            return self
        if self.backfill_start_date is None or self.backfill_end_date is None:
            raise ValueError("custom backfill requires start and end dates")
        if self.backfill_start_date > self.backfill_end_date:
            raise ValueError("custom backfill end date cannot be earlier than start date")
        return self


_BACKFILL_SCOPE_DAYS = {
    "last_7_days": 7,
    "last_30_days": 30,
}


@dataclass(slots=True, frozen=True)
class _NormalizedSensorSyncRequest:
    mode: str
    backfill_scope: str | None = None
    backfill_days: int | None = None
    backfill_start_date: str | None = None
    backfill_end_date: str | None = None


def _normalize_sensor_sync_request(
    request: SensorSourceSyncRequest | None,
) -> _NormalizedSensorSyncRequest:
    if request is None or request.first_context or request.mode != "backfill":
        return _NormalizedSensorSyncRequest(mode="latest")
    scope = request.backfill_scope or "last_30_days"
    if scope == "custom":
        return _NormalizedSensorSyncRequest(
            mode="backfill",
            backfill_scope=scope,
            backfill_start_date=(
                request.backfill_start_date.isoformat()
                if request.backfill_start_date is not None
                else None
            ),
            backfill_end_date=(
                request.backfill_end_date.isoformat()
                if request.backfill_end_date is not None
                else None
            ),
        )
    return _NormalizedSensorSyncRequest(
        mode="backfill",
        backfill_scope=scope,
        backfill_days=_BACKFILL_SCOPE_DAYS.get(scope),
    )


def _plugin_current_settings(plugin_id: str) -> dict[str, Any]:
    manager = resolve_plugin_manager()
    get_package = getattr(manager, "get_package", None)
    package = get_package(plugin_id) if callable(get_package) else None
    if package is None:
        package = next(
            (
                item
                for item in manager.list_packages()
                if str(getattr(getattr(item, "manifest", None), "plugin_id", ""))
                == plugin_id
            ),
            None,
        )
    current_settings = getattr(package, "current_settings", {}) if package is not None else {}
    return current_settings if isinstance(current_settings, dict) else {}


def _validate_source_sync_readiness(
    *,
    source_name: str,
    plugin_id: str,
    spec: Any,
) -> None:
    source_settings = _resolve_source_settings(
        spec,
        _plugin_current_settings(plugin_id),
        source_name,
    )
    if source_settings["activation_required"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=core_i18n.t(
                "sensors.errors.setup_required",
                fallback="Configure this source before syncing: {source_name}",
                source_name=source_name,
            ),
        )
    if not source_settings["enabled"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=core_i18n.t(
                "sensors.errors.source_disabled",
                fallback="Enable this source before syncing: {source_name}",
                source_name=source_name,
            ),
        )


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
async def trigger_sensor_source_sync(
    source_name: str,
    request: SensorSourceSyncRequest | None = None,
):
    _ = get_config()
    sensor_registry = resolve_sensor_registry()
    resolved = sensor_registry.resolve_source_sensor(source_name)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "sensors.errors.source_not_found", fallback="Sensor source not found"
            ),
        )
    plugin_id, _, sensor, spec = resolved
    if not bool(getattr(sensor, "supports_pull_sync", False)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t(
                "sensors.errors.pull_sync_unsupported",
                fallback="Sensor source does not support pull sync: {source_name}",
                source_name=source_name,
            ),
        )
    _validate_source_sync_readiness(
        source_name=source_name,
        plugin_id=plugin_id,
        spec=spec,
    )
    try:
        runtime_command_queue = require_runtime_command_queue()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=core_i18n.t(
                "sensors.errors.scheduler_unavailable", fallback="Scheduler unavailable"
            ),
        ) from exc
    sync_request = _normalize_sensor_sync_request(request)
    command_id = await runtime_command_queue.enqueue_sensor_sync(
        SensorSyncCommand(
            source="api.sensors",
            source_name=source_name,
            first_context=bool(request and request.first_context),
            sync_mode=sync_request.mode,
            backfill_scope=sync_request.backfill_scope,
            backfill_days=sync_request.backfill_days,
            backfill_start_date=sync_request.backfill_start_date,
            backfill_end_date=sync_request.backfill_end_date,
        )
    )
    response = {
        "queued": True,
        "source_name": source_name,
        "command_id": command_id,
        "mode": sync_request.mode,
    }
    if sync_request.backfill_scope is not None:
        response["backfill_scope"] = sync_request.backfill_scope
    if sync_request.backfill_days is not None:
        response["backfill_days"] = sync_request.backfill_days
    if sync_request.backfill_start_date is not None:
        response["backfill_start_date"] = sync_request.backfill_start_date
    if sync_request.backfill_end_date is not None:
        response["backfill_end_date"] = sync_request.backfill_end_date
    return response


@sensors_router.post("/{source_name}/flush-state")
async def trigger_sensor_state_flush(source_name: str):
    _ = get_config()
    sensor_registry = resolve_sensor_registry()
    resolved = sensor_registry.resolve_source_sensor(source_name)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "sensors.errors.source_not_found", fallback="Sensor source not found"
            ),
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
            detail=core_i18n.t(
                "sensors.errors.scheduler_unavailable", fallback="Scheduler unavailable"
            ),
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
            detail=core_i18n.t(
                "sensors.errors.source_not_found", fallback="Sensor source not found"
            ),
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
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
    day: str | None = Query(
        default=None, description="Optional ISO date (YYYY-MM-DD); defaults to server-local today."
    ),
):
    """Return per-source L1 event counts for the requested day.

    Powers the chat shell's "today context strip". Joins the day's L1 event
    count grouped by ``source`` with sensor contribution metadata so the UI
    can render human-friendly labels without a second round trip.
    """
    target_day, start_time, end_time = _resolve_day_range(day)
    counts_by_source, last_event_by_source = await _summarize_l1_sources_by_day(
        start_time=start_time,
        end_time=end_time,
    )
    sensor_metadata = _sensor_today_metadata()
    return {
        "date": target_day.isoformat(),
        "weekday": target_day.weekday(),
        "sources": _build_sensor_today_sources(
            counts_by_source=counts_by_source,
            last_event_by_source=last_event_by_source,
            sensor_metadata=sensor_metadata,
        ),
    }


async def _summarize_l1_sources_by_day(
    *,
    start_time: float,
    end_time: float,
) -> tuple[dict[str, int], dict[str, float | None]]:
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
    return counts_by_source, last_event_by_source


def _sensor_today_metadata() -> dict[str, dict[str, Any]]:
    sensor_metadata: dict[str, dict[str, Any]] = {}
    try:
        manager = resolve_plugin_manager()
    except RuntimeError:
        manager = None
    if manager is not None:
        sensor_registry = resolve_sensor_registry()
        packages = {state.manifest.plugin_id: state for state in manager.list_packages()}
        for item in sensor_registry.list_contributions():
            source_name = str(
                item.metadata.get("source_type") or item.contribution_id.split(".")[-1]
            )
            package_state = packages.get(item.plugin_id)
            current_settings = package_state.current_settings if package_state is not None else {}
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
    return sensor_metadata


def _build_sensor_today_sources(
    *,
    counts_by_source: dict[str, int],
    last_event_by_source: dict[str, float | None],
    sensor_metadata: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen_source_names: set[str] = set()
    for source_name, count in counts_by_source.items():
        meta = sensor_metadata.get(source_name, {})
        sources.append(
            _sensor_today_source_entry(
                source_name=source_name,
                meta=meta,
                count=count,
                last_event_at=last_event_by_source.get(source_name),
                enabled=bool(meta.get("enabled", True)),
                display_name=meta.get("display_name") or source_name,
            )
        )
        seen_source_names.add(source_name)

    for source_name, meta in sensor_metadata.items():
        if source_name in seen_source_names:
            continue
        if not meta.get("enabled", True):
            continue
        sources.append(
            _sensor_today_source_entry(
                source_name=source_name,
                meta=meta,
                count=0,
                last_event_at=None,
                enabled=True,
                display_name=meta.get("display_name") or source_name,
            )
        )
    sources.sort(key=lambda entry: (-int(entry["count"]), str(entry["source_name"])))
    return sources


def _sensor_today_source_entry(
    *,
    source_name: str,
    meta: dict[str, Any],
    count: int,
    last_event_at: float | None,
    enabled: bool,
    display_name: Any,
) -> dict[str, Any]:
    return {
        "source_name": source_name,
        "plugin_id": meta.get("plugin_id"),
        "display_name": display_name,
        "enabled": enabled,
        "count": count,
        "last_event_at": last_event_at,
    }


class MemoryReadinessResponse(BaseModel):
    source_name: str
    l1_event_count: int
    l2_ready: bool
    l2_total_count: int = 0
    l2_processed_count: int = 0
    l2_remaining_count: int = 0


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
    """Count source L1 events, claim pending L2 projections, then poll
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

    # Claim durable projection jobs now instead of waiting for the poll worker.
    try:
        await unified_memory.flush_l2_projection_jobs()
    except Exception:  # best-effort; readiness falls back to polling
        logger.exception("memory-readiness: L2 flush failed for %s", source_name)

    deadline = time.monotonic() + (max_wait_ms / 1000.0)
    l2_ready = False
    while True:
        backlog = await unified_memory.get_l2_projection_backlog(source_filter=source_name)
        pending = int((backlog or {}).get("pending", 0))
        claimed = int((backlog or {}).get("claimed", 0))
        if pending == 0 and claimed == 0:
            l2_ready = True
            break
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(0.5)

    progress = _build_memory_readiness_progress(l1_count=l1_count, backlog=backlog)
    return MemoryReadinessResponse(
        source_name=source_name,
        l1_event_count=l1_count,
        l2_ready=l2_ready,
        l2_total_count=progress["total"],
        l2_processed_count=progress["processed"],
        l2_remaining_count=progress["remaining"],
    )


def _build_memory_readiness_progress(*, l1_count: int, backlog: dict[str, Any] | None) -> dict[str, int]:
    pending = int((backlog or {}).get("pending", 0) or 0)
    claimed = int((backlog or {}).get("claimed", 0) or 0)
    completed = int((backlog or {}).get("completed", 0) or 0)
    failed = int((backlog or {}).get("failed", 0) or 0)
    remaining = max(0, pending + claimed)
    total = max(0, l1_count, remaining + completed + failed)
    processed = max(0, min(total, total - remaining))
    return {"total": total, "processed": processed, "remaining": remaining}
