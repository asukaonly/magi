"""Sensor operations API router."""
from __future__ import annotations

import inspect
from datetime import date, datetime, time as datetime_time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ...config import get_config
from ...core.runtime_bindings import require_runtime_command_queue
from ...events.contracts import SensorStateFlushCommand, SensorSyncCommand
from ... import i18n as core_i18n
from ...memory.provider import get_unified_memory
from ...plugins.provider import resolve_plugin_manager, resolve_sensor_registry
from ...scheduler import ScheduledTargetType
from ...scheduler.contracts import build_sensor_schedule_id, build_sensor_target_key
from ...scheduler.repository import ScheduleRepository
from ...utils.runtime import get_runtime_paths
from .plugins_common import (
    _get_plugin_i18n,
    _serialize_activation_flow,
    _serialize_field,
    _serialize_settings_ui_block,
    normalize_plugin_id,
    translate_with_fallback,
)

sensors_router = APIRouter()

_SENSOR_INTERNAL_ERROR_MARKERS = ("<Queue at ", "MemoryEvent(", " is bound to a different event loop")


class SensorSourceAuthorizationRequest(BaseModel):
    field_values: dict[str, Any] = Field(default_factory=dict)


def _get_nested_value(payload: dict[str, Any], path: str, default: Any) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return default
        if part not in current:
            return default
        current = current[part]
    return current


def _collect_source_setting_defaults(item) -> dict[str, Any]:
    defaults = {field.key: field.default for field in item.fields}
    activation_flow = item.metadata.get("activation_flow")
    if isinstance(activation_flow, dict):
        for field in activation_flow.get("fields", []):
            if isinstance(field, dict) and isinstance(field.get("key"), str):
                defaults[field["key"]] = field.get("default")
        for extra_key, extra_default in (
            (activation_flow.get("enabled_key"), item.metadata.get("default_settings", {}).get("enabled")),
            (activation_flow.get("configured_key"), False),
        ):
            if isinstance(extra_key, str):
                defaults.setdefault(extra_key, extra_default)
    for block in item.metadata.get("settings_ui_blocks", []):
        if not isinstance(block, dict):
            continue
        value_key = block.get("value_key")
        if not isinstance(value_key, str):
            continue
        defaults.setdefault(
            value_key,
            item.metadata.get("default_settings", {}).get(value_key.split(".")[-1], []),
        )
    return defaults


def _sanitize_sensor_error(error: Any) -> str | None:
    text = str(error or "").strip()
    if not text:
        return None
    if " is bound to a different event loop" in text:
        return core_i18n.t(
            "sensors.sync.loop_mismatch",
            fallback="Sensor sync failed due to an internal runtime loop mismatch.",
        )
    if any(marker in text for marker in _SENSOR_INTERNAL_ERROR_MARKERS):
        return core_i18n.t(
            "sensors.sync.internal_runtime_error",
            fallback="Sensor sync failed due to an internal runtime error.",
        )
    if len(text) > 280:
        return f"{text[:277]}..."
    return text


@sensors_router.get("/status")
async def get_sensor_source_status():
    get_config()
    runtime_paths = get_runtime_paths()
    scheduler_db_path = getattr(runtime_paths, "scheduler_db_path", Path(runtime_paths.base_dir) / "runtime" / "scheduler.db")
    repository = ScheduleRepository(scheduler_db_path)
    await repository.initialize()
    try:
        manager = resolve_plugin_manager()
    except RuntimeError:
        return []
    sensor_registry = resolve_sensor_registry()
    packages = {state.manifest.plugin_id: state for state in manager.list_packages()}
    contributions = sensor_registry.list_contributions()
    sources = []
    for item in contributions:
        source_name = str(item.metadata.get("source_type") or item.contribution_id.split(".")[-1])
        package = packages.get(item.plugin_id)
        current_settings = package.current_settings if package is not None else {}
        plugin_dir = (
            package.manifest.plugin_dir if package is not None and package.manifest is not None else ""
        )
        try:
            i18n = _get_plugin_i18n(item.plugin_id, plugin_dir)
        except Exception:  # noqa: BLE001 - never block status on i18n
            i18n = None
        plugin_id_normalized = normalize_plugin_id(item.plugin_id)
        display_name_translated = (
            translate_with_fallback(
                i18n, f"{plugin_id_normalized}.name", item.display_name
            )
            if i18n is not None
            else item.display_name
        )
        description_translated = (
            translate_with_fallback(
                i18n, f"{plugin_id_normalized}.description", item.description
            )
            if i18n is not None
            else item.description
        )

        translated_fields: list[dict[str, Any]] = []
        if i18n is not None:
            translated_fields = [
                _serialize_field(field, i18n, item.contribution_id, plugin_id=item.plugin_id)
                for field in item.fields
            ]
        else:
            translated_fields = [field.model_dump() for field in item.fields]

        raw_activation_flow = item.metadata.get("activation_flow")
        if isinstance(raw_activation_flow, dict) and i18n is not None:
            activation_flow_payload = _serialize_activation_flow(
                raw_activation_flow, i18n, plugin_id=item.plugin_id
            )
        else:
            activation_flow_payload = raw_activation_flow

        raw_ui_blocks = item.metadata.get("settings_ui_blocks", []) or []
        if isinstance(raw_ui_blocks, list) and i18n is not None:
            settings_ui_blocks_payload = [
                _serialize_settings_ui_block(block, i18n, plugin_id=item.plugin_id)
                if isinstance(block, dict)
                else block
                for block in raw_ui_blocks
            ]
        else:
            settings_ui_blocks_payload = raw_ui_blocks
        resolved = sensor_registry.resolve_source_sensor(source_name)
        sensor = resolved[2] if resolved is not None else None
        schedule_id = build_sensor_schedule_id(item.plugin_id, source_name)
        state = await repository.get_target_state(
            ScheduledTargetType.SENSOR_SYNC,
            build_sensor_target_key(item.plugin_id, source_name),
        )
        schedule = await repository.get_schedule(schedule_id)
        recurring_binding = await repository.get_recurring_target_binding(
            ScheduledTargetType.SENSOR_SYNC,
            build_sensor_target_key(item.plugin_id, source_name),
        )
        supports_pull_sync = bool(getattr(sensor, "supports_pull_sync", False))
        supports_state_flush = bool(getattr(sensor, "supports_state_flush", False))
        visible_last_error = (
            _sanitize_sensor_error(state.last_error)
            if (state is not None and supports_pull_sync)
            else None
        )
        resolved_next_run_at = (
            state.next_run_at
            if (state is not None and state.next_run_at is not None)
            else (recurring_binding[1] if recurring_binding is not None else None)
        )
        resolved_scheduler_job_id = (
            recurring_binding[0]
            if recurring_binding is not None
            else (
                schedule.job_id
                if schedule is not None
                else (state.scheduler_job_id if state is not None else None)
            )
        )
        sources.append(
            {
                "source_name": source_name,
                "plugin_id": item.plugin_id,
                "contribution_id": item.contribution_id,
                "display_name": item.display_name,
                "display_name_translated": display_name_translated,
                "description": item.description,
                "description_translated": description_translated,
                "fields": translated_fields,
                "current_settings": {
                    key: _get_nested_value(current_settings, key, default)
                    for key, default in _collect_source_setting_defaults(item).items()
                },
                "enabled": bool(
                    _get_nested_value(
                        current_settings,
                        f"sensors.{source_name}.enabled",
                        item.metadata.get("default_settings", {}).get("enabled", True),
                    )
                ),
                "sync_mode": str(
                    _get_nested_value(
                        current_settings,
                        f"sensors.{source_name}.sync_mode",
                        item.metadata.get("default_settings", {}).get("sync_mode", item.metadata.get("sync_mode", "manual")),
                    )
                ),
                "sync_interval_minutes": int(
                    _get_nested_value(
                        current_settings,
                        f"sensors.{source_name}.sync_interval_minutes",
                        item.metadata.get("default_settings", {}).get("sync_interval_minutes", 1),
                    )
                ),
                "storage_mode": str(
                    _get_nested_value(
                        current_settings,
                        f"sensors.{source_name}.storage_mode",
                        item.metadata.get("default_settings", {}).get("storage_mode", "managed"),
                    )
                ),
                "source_path": _get_nested_value(
                    current_settings,
                    f"sensors.{source_name}.source_path",
                    item.metadata.get("default_settings", {}).get("source_path"),
                ),
                "fetch_page_content": bool(
                    _get_nested_value(
                        current_settings,
                        f"sensors.{source_name}.fetch_page_content",
                        item.metadata.get("default_settings", {}).get("fetch_page_content", False),
                    )
                ),
                "edge_whitelist": list(
                    _get_nested_value(
                        current_settings,
                        f"sensors.{source_name}.edge_whitelist",
                        item.metadata.get("default_settings", {}).get("edge_whitelist", []),
                    )
                ),
                "supports_pull_sync": supports_pull_sync,
                "supports_state_flush": supports_state_flush,
                "activation_flow": activation_flow_payload,
                "settings_ui_blocks": settings_ui_blocks_payload,
                "activation_required": bool(
                    isinstance(item.metadata.get("activation_flow"), dict)
                    and not bool(
                        _get_nested_value(
                            current_settings,
                            f"sensors.{source_name}.enabled",
                            item.metadata.get("default_settings", {}).get("enabled", True),
                        )
                    )
                    and not bool(
                        _get_nested_value(
                            current_settings,
                            str(item.metadata.get("activation_flow", {}).get("configured_key") or ""),
                            False,
                        )
                    )
                ),
                "running": bool(state.running) if state is not None else False,
                "last_run_at": state.last_run_at if state is not None else None,
                "last_result_count": int((state.stats or {}).get("count", 0)) if state is not None else 0,
                "last_raw_result_count": int((state.stats or {}).get("raw_count", 0)) if state is not None else 0,
                "last_error": visible_last_error,
                "last_success": state.last_success_at if state is not None else None,
                "last_sync_at": state.last_success_at if state is not None else None,
                "next_run_at": resolved_next_run_at,
                "scheduler_job_id": resolved_scheduler_job_id,
                "runtime_base_dir": str(runtime_paths.base_dir),
            }
        )
    return {"sources": sources}


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
