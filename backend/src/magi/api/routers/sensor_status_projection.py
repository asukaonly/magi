"""Read-model projection for sensor source status responses."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ... import i18n as core_i18n
from ...plugins.icon_assets import resolve_plugin_icon
from ...scheduler import ScheduledTargetType
from ...scheduler.contracts import build_sensor_schedule_id, build_sensor_target_key
from ...scheduler.repository import ScheduleRepository
from ..services.plugin_secrets import mask_plugin_setting_values
from .plugins_common import (
    _get_plugin_i18n,
    _serialize_activation_flow,
    _serialize_field,
    _serialize_sensor_capability,
    _serialize_settings_action,
    _serialize_settings_layout,
    _serialize_settings_ui_block,
    normalize_plugin_id,
    translate_with_fallback,
)

_SENSOR_INTERNAL_ERROR_MARKERS = ("<Queue at ", "MemoryEvent(", " is bound to a different event loop")
_INTERVAL_STALE_FLOOR_SECONDS = 6 * 60 * 60
_SYNC_CONTINUATION_GRACE_SECONDS = 5.0
_SYNC_CONTINUATION_STATS_KEYS = ("has_more", "continue_sync", "backfill_has_more")


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


def _coerce_timestamp_seconds(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric <= 0:
            return None
        return numeric / 1000.0 if numeric > 1_000_000_000_000 else numeric
    text = str(value).strip()
    if not text:
        return None
    try:
        return _coerce_timestamp_seconds(float(text))
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _derive_sensor_status(
    *,
    enabled: bool,
    activation_required: bool,
    running: bool,
    retrying: bool = False,
    last_error: str | None,
    last_success_at: Any,
    sync_mode: str,
    sync_interval_minutes: int,
    now: float | None = None,
) -> str:
    if activation_required:
        return "setup_required"
    if not enabled:
        return "disabled"
    if retrying:
        return "retrying"
    if running:
        return "running"
    if last_error:
        return "error"
    last_success = _coerce_timestamp_seconds(last_success_at)
    if last_success is None:
        return "never_synced"
    if str(sync_mode or "").lower() == "interval":
        interval_seconds = max(int(sync_interval_minutes or 0), 1) * 60
        stale_after = max(interval_seconds * 2, _INTERVAL_STALE_FLOOR_SECONDS)
        if (now if now is not None else time.time()) - last_success > stale_after:
            return "stale"
    return "ready"


async def build_sensor_source_status_payload(
    *,
    runtime_paths: Any,
    manager: Any,
    sensor_registry: Any,
) -> dict[str, Any]:
    repository = _build_schedule_repository(runtime_paths)
    await repository.initialize()
    packages = {state.manifest.plugin_id: state for state in manager.list_packages()}
    sources = [
        await _build_source_status(
            item,
            packages=packages,
            sensor_registry=sensor_registry,
            repository=repository,
            runtime_base_dir=str(runtime_paths.base_dir),
        )
        for item in sensor_registry.list_contributions()
    ]
    return {"sources": sources}


def _build_schedule_repository(runtime_paths: Any) -> ScheduleRepository:
    scheduler_db_path = getattr(
        runtime_paths,
        "scheduler_db_path",
        Path(runtime_paths.base_dir) / "runtime" / "scheduler.db",
    )
    return ScheduleRepository(scheduler_db_path)


async def _build_source_status(
    item: Any,
    *,
    packages: dict[str, Any],
    sensor_registry: Any,
    repository: ScheduleRepository,
    runtime_base_dir: str,
) -> dict[str, Any]:
    source_name = _source_name(item)
    package = packages.get(item.plugin_id)
    current_settings = package.current_settings if package is not None else {}
    i18n = _load_plugin_i18n(item, package)
    plugin_id_normalized = normalize_plugin_id(item.plugin_id)
    entry_id_for_translation = str(item.metadata.get("entry_id") or source_name)
    resolved = sensor_registry.resolve_source_sensor(source_name)
    sensor = resolved[2] if resolved is not None else None
    state, schedule, recurring_binding, latest_sync_job = await _load_scheduler_state(
        repository,
        plugin_id=item.plugin_id,
        source_name=source_name,
    )
    source_settings = _resolve_source_settings(item, current_settings, source_name)
    capabilities = _resolve_sensor_capabilities(sensor, state)
    sync_activity = _serialize_sensor_sync_activity(latest_sync_job)

    return {
        **_source_identity_payload(
            item,
            package=package,
            source_name=source_name,
            i18n=i18n,
            plugin_id_normalized=plugin_id_normalized,
            entry_id=entry_id_for_translation,
        ),
        **_source_ui_payload(item, i18n=i18n, current_settings=current_settings),
        **source_settings,
        **capabilities,
        **_source_run_payload(
            state=state,
            source_settings=source_settings,
            capabilities=capabilities,
            sync_activity=sync_activity,
        ),
        "sync_activity": sync_activity,
        **_source_schedule_payload(
            recurring_binding=recurring_binding,
            schedule=schedule,
            state=state,
            runtime_base_dir=runtime_base_dir,
        ),
    }


def _source_identity_payload(
    item: Any,
    *,
    package: Any,
    source_name: str,
    i18n: Any,
    plugin_id_normalized: str,
    entry_id: str,
) -> dict[str, Any]:
    package_icon = (
        resolve_plugin_icon(package.manifest.icon, package.manifest.plugin_dir)
        if package is not None
        else ""
    )
    return {
        "source_name": source_name,
        "plugin_id": item.plugin_id,
        "contribution_id": item.contribution_id,
        "icon": package_icon or str(item.metadata.get("icon") or ""),
        "display_name": item.display_name,
        "display_name_translated": _translate_entry_text(
            i18n,
            plugin_id_normalized=plugin_id_normalized,
            entry_id=entry_id,
            key="display_name",
            plugin_fallback_key="name",
            fallback=item.display_name,
        ),
        "description": item.description,
        "description_translated": _translate_entry_text(
            i18n,
            plugin_id_normalized=plugin_id_normalized,
            entry_id=entry_id,
            key="description",
            plugin_fallback_key="description",
            fallback=item.description,
        ),
        **_serialize_sensor_capability(
            item.metadata,
            i18n,
            plugin_id=item.plugin_id,
            fallback_source_name=source_name,
            fallback_display_name=item.display_name,
            fallback_description=item.description,
        ),
        **_source_entry_metadata_payload(
            item,
            i18n=i18n,
            plugin_id_normalized=plugin_id_normalized,
            entry_id=entry_id,
        ),
    }


def _source_entry_metadata_payload(
    item: Any,
    *,
    i18n: Any,
    plugin_id_normalized: str,
    entry_id: str,
) -> dict[str, Any]:
    return {
        "entry_order": item.metadata.get("entry_order"),
        "available": item.metadata.get("available"),
        "platforms": item.metadata.get("platforms"),
        "unavailable_reason": item.metadata.get("unavailable_reason"),
        "unavailable_reason_translated": translate_with_fallback(
            i18n,
            f"{plugin_id_normalized}.entries.{entry_id}.unavailable_reason",
            item.metadata.get("unavailable_reason"),
        ),
    }


def _source_ui_payload(
    item: Any,
    *,
    i18n: Any,
    current_settings: dict[str, Any],
) -> dict[str, Any]:
    return {
        "fields": _serialize_source_fields(item, i18n),
        "current_settings": _current_source_settings(item, current_settings),
        "activation_flow": _serialize_activation_flow_payload(item, i18n),
        "settings_layout": _serialize_settings_layout_payload(item, i18n),
        "settings_ui_blocks": _serialize_settings_ui_blocks_payload(item, i18n),
        "settings_actions": _serialize_settings_actions_payload(item, i18n),
    }


def _source_run_payload(
    *,
    state: Any,
    source_settings: dict[str, Any],
    capabilities: dict[str, Any],
    sync_activity: dict[str, Any] | None,
) -> dict[str, Any]:
    retrying = bool(sync_activity and sync_activity.get("status") == "retrying")
    return {
        "running": capabilities["running"],
        "last_run_at": state.last_run_at if state is not None else None,
        "last_result_count": int((state.stats or {}).get("count", 0)) if state is not None else 0,
        "last_raw_result_count": int((state.stats or {}).get("raw_count", 0)) if state is not None else 0,
        "last_error": capabilities["last_error"],
        "last_success": state.last_success_at if state is not None else None,
        "last_sync_at": state.last_success_at if state is not None else None,
        "status": _derive_sensor_status(
            enabled=source_settings["enabled"],
            activation_required=source_settings["activation_required"],
            running=capabilities["running"],
            retrying=retrying,
            last_error=capabilities["last_error"],
            last_success_at=state.last_success_at if state is not None else None,
            sync_mode=source_settings["sync_mode"],
            sync_interval_minutes=source_settings["sync_interval_minutes"],
        ),
    }


def _source_schedule_payload(
    *,
    recurring_binding: Any,
    schedule: Any,
    state: Any,
    runtime_base_dir: str,
) -> dict[str, Any]:
    return {
        "next_run_at": recurring_binding[1] if recurring_binding is not None else None,
        "scheduler_job_id": _resolve_scheduler_job_id(
            recurring_binding=recurring_binding,
            schedule=schedule,
            state=state,
        ),
        "runtime_base_dir": runtime_base_dir,
    }


def _source_name(item: Any) -> str:
    return str(item.metadata.get("source_type") or item.contribution_id.split(".")[-1])


def _load_plugin_i18n(item: Any, package: Any):
    plugin_dir = (
        package.manifest.plugin_dir if package is not None and package.manifest is not None else ""
    )
    try:
        return _get_plugin_i18n(item.plugin_id, plugin_dir)
    except Exception:
        return None


async def _load_scheduler_state(
    repository: ScheduleRepository,
    *,
    plugin_id: str,
    source_name: str,
) -> tuple[Any, Any, Any, Any]:
    target_key = build_sensor_target_key(plugin_id, source_name)
    schedule_id = build_sensor_schedule_id(plugin_id, source_name)
    state = await repository.get_target_state(ScheduledTargetType.SENSOR_SYNC, target_key)
    schedule = await repository.get_schedule(schedule_id)
    recurring_binding = await repository.get_recurring_target_binding(
        ScheduledTargetType.SENSOR_SYNC,
        target_key,
    )
    latest_sync_job = await repository.get_latest_sensor_sync_job(
        ScheduledTargetType.SENSOR_SYNC,
        target_key,
    )
    return state, schedule, recurring_binding, latest_sync_job


def _serialize_sensor_sync_activity(
    job: dict[str, object] | None,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    if job is None:
        return None
    payload = job.get("payload")
    sync_request = (
        payload.get("sync_request")
        if isinstance(payload, dict) and isinstance(payload.get("sync_request"), dict)
        else None
    )
    mode = "backfill" if sync_request is not None else "latest"
    status = str(job.get("status") or "")
    raw_attempt_count = job.get("attempt_count")
    attempt_count = max(0, raw_attempt_count if isinstance(raw_attempt_count, int) else 0)
    if (status == "queued" and attempt_count > 0) or (
        status == "running" and attempt_count > 1
    ):
        status = "retrying"
    stats = job.get("stats")
    finished_at = _coerce_timestamp_seconds(job.get("finished_at"))
    current_time = time.time() if now is None else now
    continuation_requested = bool(
        isinstance(stats, dict)
        and any(_coerce_bool(stats.get(key)) for key in _SYNC_CONTINUATION_STATS_KEYS)
    )
    if (
        status == "success"
        and continuation_requested
        and finished_at is not None
        and current_time - finished_at < _SYNC_CONTINUATION_GRACE_SECONDS
    ):
        status = "continuing"
    request = sync_request or {}
    return {
        "job_id": str(job.get("job_id") or ""),
        "mode": mode,
        "status": status,
        "backfill_scope": request.get("backfill_scope"),
        "backfill_start_date": request.get("backfill_start_date"),
        "backfill_end_date": request.get("backfill_end_date"),
        "created_at": _coerce_timestamp_seconds(job.get("created_at")),
        "started_at": _coerce_timestamp_seconds(job.get("started_at")),
        "finished_at": finished_at,
        "attempt_count": attempt_count,
        "next_attempt_at": _coerce_timestamp_seconds(job.get("next_attempt_at")),
        "error": _sanitize_sensor_error(job.get("error")),
    }


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _resolve_scheduler_job_id(*, recurring_binding: Any, schedule: Any, state: Any) -> Any:
    if recurring_binding is not None:
        return recurring_binding[0]
    if schedule is not None:
        return schedule.job_id
    return state.scheduler_job_id if state is not None else None


def _resolve_source_settings(
    item: Any,
    current_settings: dict[str, Any],
    source_name: str,
) -> dict[str, Any]:
    enabled = bool(_source_setting(item, current_settings, source_name, "enabled", True))
    return {
        "enabled": enabled,
        **_source_sync_settings(item, current_settings, source_name),
        **_source_storage_settings(item, current_settings, source_name),
        "activation_required": _activation_required(item, current_settings, enabled),
    }


def _source_setting(
    item: Any,
    current_settings: dict[str, Any],
    source_name: str,
    key: str,
    fallback: Any,
) -> Any:
    default_settings = item.metadata.get("default_settings", {})
    return _get_nested_value(
        current_settings,
        f"sensors.{source_name}.{key}",
        default_settings.get(key, fallback),
    )


def _source_sync_settings(
    item: Any,
    current_settings: dict[str, Any],
    source_name: str,
) -> dict[str, Any]:
    return {
        "sync_mode": str(
            _source_setting(
                item,
                current_settings,
                source_name,
                "sync_mode",
                item.metadata.get("sync_mode", "manual"),
            )
        ),
        "sync_interval_minutes": int(
            _source_setting(item, current_settings, source_name, "sync_interval_minutes", 1)
        ),
    }


def _source_storage_settings(
    item: Any,
    current_settings: dict[str, Any],
    source_name: str,
) -> dict[str, Any]:
    return {
        "storage_mode": str(
            _source_setting(item, current_settings, source_name, "storage_mode", "managed")
        ),
        "source_path": _source_setting(item, current_settings, source_name, "source_path", None),
        "fetch_page_content": bool(
            _source_setting(item, current_settings, source_name, "fetch_page_content", False)
        ),
        "edge_whitelist": list(
            _source_setting(item, current_settings, source_name, "edge_whitelist", [])
        ),
    }


def _activation_required(
    item: Any,
    current_settings: dict[str, Any],
    enabled: bool,
) -> bool:
    activation_flow = item.metadata.get("activation_flow")
    if not isinstance(activation_flow, dict) or enabled:
        return False
    return not bool(
        _get_nested_value(
            current_settings,
            str(activation_flow.get("configured_key") or ""),
            False,
        )
    )


def _resolve_sensor_capabilities(sensor: Any, state: Any) -> dict[str, Any]:
    supports_pull_sync = bool(getattr(sensor, "supports_pull_sync", False))
    return {
        "supports_pull_sync": supports_pull_sync,
        "supports_state_flush": bool(getattr(sensor, "supports_state_flush", False)),
        "running": bool(state.running) if state is not None else False,
        "last_error": (
            _sanitize_sensor_error(state.last_error)
            if (state is not None and supports_pull_sync)
            else None
        ),
    }


def _translate_entry_text(
    i18n: Any,
    *,
    plugin_id_normalized: str,
    entry_id: str,
    key: str,
    plugin_fallback_key: str,
    fallback: str,
) -> str | None:
    return translate_with_fallback(
        i18n,
        f"{plugin_id_normalized}.entries.{entry_id}.{key}",
        translate_with_fallback(i18n, f"{plugin_id_normalized}.{plugin_fallback_key}", fallback),
    )


def _serialize_source_fields(item: Any, i18n: Any) -> list[dict[str, Any]]:
    if i18n is None:
        return [field.model_dump() for field in item.fields]
    return [
        _serialize_field(field, i18n, item.contribution_id, plugin_id=item.plugin_id)
        for field in item.fields
    ]


def _current_source_settings(item: Any, current_settings: dict[str, Any]) -> dict[str, Any]:
    values = {
        key: _get_nested_value(current_settings, key, default)
        for key, default in _collect_source_setting_defaults(item).items()
    }
    return mask_plugin_setting_values(values, [item])


def _serialize_activation_flow_payload(item: Any, i18n: Any) -> Any:
    raw_activation_flow = item.metadata.get("activation_flow")
    if isinstance(raw_activation_flow, dict) and i18n is not None:
        return _serialize_activation_flow(raw_activation_flow, i18n, plugin_id=item.plugin_id)
    return raw_activation_flow


def _serialize_settings_ui_blocks_payload(item: Any, i18n: Any) -> Any:
    raw_ui_blocks = item.metadata.get("settings_ui_blocks", []) or []
    if isinstance(raw_ui_blocks, list) and i18n is not None:
        return [
            _serialize_settings_ui_block(block, i18n, plugin_id=item.plugin_id)
            if isinstance(block, dict)
            else block
            for block in raw_ui_blocks
        ]
    return raw_ui_blocks


def _serialize_settings_layout_payload(item: Any, i18n: Any) -> dict[str, Any] | None:
    raw_settings_layout = item.metadata.get("settings_layout")
    if isinstance(raw_settings_layout, dict) and i18n is not None:
        return _serialize_settings_layout(raw_settings_layout, i18n, plugin_id=item.plugin_id)
    return raw_settings_layout if isinstance(raw_settings_layout, dict) else None


def _serialize_settings_actions_payload(item: Any, i18n: Any) -> list[Any]:
    raw_settings_actions = item.metadata.get("settings_actions", []) or []
    if isinstance(raw_settings_actions, list) and i18n is not None:
        return [
            _serialize_settings_action(action, i18n, plugin_id=item.plugin_id)
            if isinstance(action, dict)
            else action
            for action in raw_settings_actions
        ]
    return raw_settings_actions if isinstance(raw_settings_actions, list) else []


__all__ = [
    "_derive_sensor_status",
    "_get_nested_value",
    "_serialize_sensor_sync_activity",
    "build_sensor_source_status_payload",
]
