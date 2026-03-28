"""Sensor operations API router."""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ...config import get_config
from ...core.runtime_bindings import (
    require_plugin_manager,
    require_runtime_command_queue,
    require_sensor_registry,
)
from ...events.contracts import SensorSyncCommand
from ...scheduler import ScheduledTargetType
from ...scheduler.contracts import build_sensor_schedule_id, build_sensor_target_key
from ...scheduler.repository import ScheduleRepository
from ...utils.runtime import get_runtime_paths

sensors_router = APIRouter()


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


@sensors_router.get("/status")
async def get_sensor_source_status():
    get_config()
    runtime_paths = get_runtime_paths()
    scheduler_db_path = getattr(runtime_paths, "scheduler_db_path", Path(runtime_paths.base_dir) / "data" / "scheduler.db")
    repository = ScheduleRepository(scheduler_db_path)
    await repository.initialize()
    manager = require_plugin_manager()
    sensor_registry = require_sensor_registry()
    packages = {state.manifest.plugin_id: state for state in manager.list_packages()}
    contributions = sensor_registry.list_contributions()
    sources = []
    for item in contributions:
        source_name = str(item.metadata.get("source_type") or item.contribution_id.split(".")[-1])
        current_settings = (
            packages.get(item.plugin_id).current_settings if packages.get(item.plugin_id) is not None else {}
        )
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
        visible_last_error = state.last_error if (state is not None and supports_pull_sync) else None
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
                "description": item.description,
                "fields": [field.model_dump() for field in item.fields],
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
                "activation_flow": item.metadata.get("activation_flow"),
                "settings_ui_blocks": item.metadata.get("settings_ui_blocks", []),
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
    sensor_registry = require_sensor_registry()
    resolved = sensor_registry.resolve_source_sensor(source_name)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sensor source not found")
    _, _, sensor, _ = resolved
    if not bool(getattr(sensor, "supports_pull_sync", False)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Sensor source does not support pull sync: {source_name}",
        )
    try:
        runtime_command_queue = require_runtime_command_queue()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Scheduler unavailable") from exc
    command_id = await runtime_command_queue.enqueue_sensor_sync(
        SensorSyncCommand(
            source="api.sensors",
            source_name=source_name,
        )
    )
    return {"queued": True, "source_name": source_name, "command_id": command_id}


@sensors_router.post("/{source_name}/authorize")
async def authorize_sensor_source(source_name: str, request: SensorSourceAuthorizationRequest):
    _ = get_config()
    sensor_registry = require_sensor_registry()
    resolved = sensor_registry.resolve_source_sensor(source_name)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sensor source not found")

    _, _, sensor, _ = resolved
    authorize = getattr(sensor, "request_activation_authorization", None)
    if not callable(authorize):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sensor source does not support authorization",
        )

    result = authorize(dict(request.field_values))
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Sensor source authorization returned an invalid response",
        )
    return result
