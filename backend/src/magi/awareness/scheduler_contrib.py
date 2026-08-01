"""Sensor layer's integration with the unified scheduler."""

from __future__ import annotations

import asyncio
import copy
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from ..core.container import get_container
from ..i18n import get_preferred_language
from ..core.logger import get_logger
from ..plugins.i18n import get_current_language as get_plugin_current_language
from ..plugins.i18n import set_current_language as set_plugin_current_language
from ..plugins.sensors import SensorRegistry
from ..scheduler.contracts import (
    ScheduleDefinition,
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
    build_sensor_schedule_id,
    build_sensor_target_key,
)
from ..scheduler.service import SchedulerService
from ..utils.runtime import RuntimePaths
from .sensor_sync import SensorSyncContext

if TYPE_CHECKING:
    from ..memory.sensor_ingestion import SensorIngestionBoundary
    from .ingestion_gateway import SensorIngestionGateway, SensorIngestionResult

logger = get_logger(__name__)


@dataclass(slots=True)
class _ResolvedSensorSyncTarget:
    plugin_id: str
    sensor: Any
    spec: Any


@dataclass(slots=True)
class _SensorSyncSettings:
    package_settings: dict[str, Any]
    allowed_edge_whitelist: list[str]
    limit: int


def request_sensor_schedule_refresh() -> None:
    """Schedule a best-effort refresh of sensor-owned schedules."""
    try:
        contrib = _get_sensor_scheduler_contrib()
    except RuntimeError:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("Skipping sensor schedule refresh because no event loop is running")
        return

    task = loop.create_task(contrib.sync_schedules())
    task.add_done_callback(_log_refresh_failure)


def _get_sensor_scheduler_contrib():
    provider = get_container().sensor_scheduler_contrib
    instance = provider()
    if instance is None:
        raise RuntimeError("sensor_scheduler_contrib binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError("sensor_scheduler_contrib binding is not initialized")
    return instance


def _log_refresh_failure(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except Exception as exc:  # pragma: no cover
        logger.warning("Sensor schedule refresh failed", error=str(exc))


class SensorSchedulerContrib:
    """Sensor layer's scheduler contributor."""

    def __init__(
        self,
        *,
        scheduler_service: SchedulerService,
        sensor_registry: SensorRegistry,
        plugin_manager: Any,
        runtime_paths: RuntimePaths,
        get_config: Callable[[], Any],
        ingestion_gateway: SensorIngestionGateway,
    ) -> None:
        self._scheduler_service = scheduler_service
        self._sensor_registry = sensor_registry
        self._plugin_manager = plugin_manager
        self._runtime_paths = runtime_paths
        self._get_config = get_config
        self._ingestion_gateway = ingestion_gateway
        self._registered_schedule_ids: set[str] = set()

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        scheduler.register_handler(
            ScheduledTargetType.SENSOR_SYNC,
            self._handle_sensor_sync,
        )
        await self.sync_schedules()

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        for schedule_id in list(self._registered_schedule_ids):
            try:
                await scheduler.unschedule(
                    schedule_id,
                    target_type=ScheduledTargetType.SENSOR_SYNC,
                    target_key="",
                )
            except Exception:
                pass
        self._registered_schedule_ids.clear()

    async def sync_schedules(self) -> None:
        for contribution in self._sensor_registry.list_contributions():
            source_type = str(
                contribution.metadata.get("source_type")
                or contribution.contribution_id.split(".")[-1]
            )
            resolved = self._sensor_registry.resolve_source_sensor(source_type)
            if resolved is None:
                continue
            plugin_id, _, sensor, spec = resolved
            schedule_id = build_sensor_schedule_id(plugin_id, source_type)
            package_state = self._plugin_manager.get_package(plugin_id)
            current_settings = package_state.current_settings if package_state is not None else {}
            default_settings = dict(spec.metadata.get("default_settings", {}))
            source_settings = dict(current_settings.get("sensors", {}).get(source_type, {}))
            enabled = bool(source_settings.get("enabled", default_settings.get("enabled", True)))
            sync_mode = str(
                source_settings.get("sync_mode", default_settings.get("sync_mode", spec.sync_mode))
            )
            interval_minutes = float(
                source_settings.get(
                    "sync_interval_minutes", default_settings.get("sync_interval_minutes", 1)
                )
            )
            supports_pull_sync = bool(getattr(sensor, "supports_pull_sync", False))
            if (not enabled) or (not supports_pull_sync) or sync_mode == "manual":
                await self._scheduler_service.unschedule(
                    schedule_id,
                    target_type=ScheduledTargetType.SENSOR_SYNC,
                    target_key=build_sensor_target_key(plugin_id, source_type),
                )
                self._registered_schedule_ids.discard(schedule_id)
                continue
            if sync_mode == "watch" and not bool(getattr(sensor, "supports_watch_mode", False)):
                interval_minutes = max(1.0, interval_minutes)
            await self._scheduler_service.schedule_interval(
                schedule_id=schedule_id,
                target_type=ScheduledTargetType.SENSOR_SYNC,
                target_key=build_sensor_target_key(plugin_id, source_type),
                seconds=max(1.0, interval_minutes * 60.0),
                target_payload={
                    "plugin_id": plugin_id,
                    "source_type": source_type,
                    "manual": False,
                },
                metadata={"source_type": source_type, "plugin_id": plugin_id},
            )
            self._registered_schedule_ids.add(schedule_id)

    async def queue_manual_sync(
        self,
        source_type: str,
        *,
        first_context: bool = False,
        sync_mode: str = "latest",
        backfill_scope: str | None = None,
        backfill_days: int | None = None,
        backfill_start_date: str | None = None,
        backfill_end_date: str | None = None,
    ) -> ScheduleDefinition:
        resolved = self._sensor_registry.resolve_source_sensor(source_type)
        if resolved is None:
            raise KeyError(source_type)
        plugin_id, _, sensor, _ = resolved
        if not bool(getattr(sensor, "supports_pull_sync", False)):
            raise ValueError(f"Sensor source does not support pull sync: {source_type}")
        normalized_mode = "backfill" if sync_mode == "backfill" else "latest"
        normalized_scope = str(backfill_scope or "last_30_days").strip() or "last_30_days"
        normalized_start_date = _normalize_optional_date(backfill_start_date)
        normalized_end_date = _normalize_optional_date(backfill_end_date)
        if normalized_mode == "backfill":
            schedule_suffix = normalized_scope
            if normalized_scope == "custom" and normalized_start_date and normalized_end_date:
                schedule_suffix = f"custom:{normalized_start_date}:{normalized_end_date}"
            schedule_id = f"sensor-sync-backfill:{plugin_id}:{source_type}:{schedule_suffix}"
        else:
            schedule_id = f"sensor-sync-manual:{plugin_id}:{source_type}:{uuid.uuid4().hex}"
        target_payload = {
            "plugin_id": plugin_id,
            "source_type": source_type,
            "manual": True,
        }
        metadata = {"manual": True, "source_type": source_type, "plugin_id": plugin_id}
        if first_context:
            target_payload["first_context"] = True
            metadata["first_context"] = True
        if normalized_mode == "backfill":
            sync_request: dict[str, Any] = {
                "mode": "backfill",
                "backfill_scope": normalized_scope,
            }
            if backfill_days is not None:
                sync_request["backfill_days"] = int(backfill_days)
            if normalized_start_date is not None:
                sync_request["backfill_start_date"] = normalized_start_date
            if normalized_end_date is not None:
                sync_request["backfill_end_date"] = normalized_end_date
            target_payload["sync_request"] = dict(sync_request)
            metadata["sync_request"] = dict(sync_request)
        return await self._scheduler_service.schedule_once(
            schedule_id=schedule_id,
            target_type=ScheduledTargetType.SENSOR_SYNC,
            target_key=build_sensor_target_key(plugin_id, source_type),
            run_at=time.time(),
            target_payload=target_payload,
            metadata=metadata,
        )

    async def _handle_sensor_sync(
        self,
        context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        source_type = str(context.schedule.target_payload.get("source_type") or "")
        return await self._run_sensor_sync(
            schedule_id=context.schedule.schedule_id,
            target_key=context.schedule.target_key,
            source_type=source_type,
            manual=context.manual,
            target_state=context.target_state,
            sync_payload=context.schedule.target_payload,
            admitted_at=context.triggered_at,
        )

    async def execute_sensor_sync_job(self, job: dict[str, object]) -> ScheduledExecutionResult:
        target_state = await self._scheduler_service.get_target_state(
            ScheduledTargetType(str(job["target_type"])),
            str(job["target_key"]),
        )
        return await self._run_sensor_sync(
            schedule_id=str(job["schedule_id"]),
            target_key=str(job["target_key"]),
            source_type=str(job["source_type"]),
            manual=bool(job["manual"]),
            target_state=target_state,
            sync_payload=job.get("payload") if isinstance(job.get("payload"), dict) else {},
            admitted_at=float(job.get("created_at") or 0.0),
        )

    async def flush_sensor_state(self, source_type: str) -> dict[str, Any]:
        resolved = self._sensor_registry.resolve_source_sensor(source_type)
        if resolved is None:
            raise RuntimeError(f"Sensor source not found: {source_type}")
        plugin_id, _, sensor, _ = resolved
        flush_state = getattr(sensor, "flush_runtime_state", None)
        if not callable(flush_state):
            raise RuntimeError(f"Sensor source does not support state flush: {source_type}")
        package_state = self._plugin_manager.get_package(plugin_id)
        package_settings = package_state.current_settings if package_state is not None else {}
        return await flush_state(
            runtime_paths=self._runtime_paths, plugin_settings=package_settings
        )

    async def _run_sensor_sync(
        self,
        *,
        schedule_id: str,
        target_key: str,
        source_type: str,
        manual: bool,
        target_state: Any,
        sync_payload: dict[str, Any] | None = None,
        admitted_at: float = 0.0,
    ) -> ScheduledExecutionResult:
        target = self._resolve_sensor_sync_target(source_type)
        settings = self._sensor_sync_settings(
            plugin_id=target.plugin_id,
            source_type=source_type,
            spec=target.spec,
        )
        sync_request = _extract_backfill_sync_request(sync_payload)
        last_cursor = target_state.last_cursor
        if sync_request is not None:
            settings = _apply_backfill_sync_request(
                settings=settings,
                source_type=source_type,
                sync_request=sync_request,
            )
            if not schedule_id.startswith("sensor-sync-continuation:"):
                last_cursor = None
        preferred_language = get_preferred_language()
        if preferred_language:
            settings.package_settings.setdefault("locale", preferred_language)
        previous_language = get_plugin_current_language()
        set_plugin_current_language(preferred_language or None)
        try:
            ingestion_boundary = (
                await self._ingestion_gateway.capture_ingestion_boundary()
            )
            allow_pre_clear_events = bool(
                manual
                and (
                    ingestion_boundary.clear_generation == 0
                    or admitted_at > ingestion_boundary.clear_cutoff_at
                )
            )
            pull_context = SensorSyncContext(
                source_type=source_type,
                manual=manual,
                last_cursor=last_cursor,
                last_success_at=target_state.last_success_at,
                limit=settings.limit,
                runtime_paths=self._runtime_paths,
                plugin_settings=settings.package_settings,
            )
            result = await target.sensor.collect_items(pull_context)
            clear_boundary_crossed = await self._ingest_sensor_sync_items(
                sensor=target.sensor,
                result=result,
                schedule_id=schedule_id,
                target_key=target_key,
                manual=manual,
                allowed_edge_whitelist=settings.allowed_edge_whitelist,
                ingestion_boundary=ingestion_boundary,
                allow_pre_clear_events=allow_pre_clear_events,
            )
            stats = dict(_merge_sync_request_stats(result.stats, sync_request) or {})
            if clear_boundary_crossed:
                stats.update(
                    {
                        "memory_clear_skipped": True,
                        "has_more": False,
                        "continue_sync": False,
                        "backfill_has_more": False,
                    }
                )
            return ScheduledExecutionResult(
                success=True,
                message="sensor_sync_completed",
                next_cursor=result.next_cursor,
                watermark_ts=result.watermark_ts,
                stats=stats,
            )
        finally:
            set_plugin_current_language(previous_language or None)

    def _resolve_sensor_sync_target(self, source_type: str) -> _ResolvedSensorSyncTarget:
        resolved = self._sensor_registry.resolve_source_sensor(source_type)
        if resolved is None:
            raise RuntimeError(f"Sensor source not found: {source_type}")
        plugin_id, _, sensor, spec = resolved
        if not bool(getattr(sensor, "supports_pull_sync", False)):
            raise RuntimeError(f"Sensor source does not support pull sync: {source_type}")
        return _ResolvedSensorSyncTarget(plugin_id=plugin_id, sensor=sensor, spec=spec)

    def _sensor_sync_settings(
        self,
        *,
        plugin_id: str,
        source_type: str,
        spec: Any,
    ) -> _SensorSyncSettings:
        package_state = self._plugin_manager.get_package(plugin_id)
        package_settings = (
            copy.deepcopy(package_state.current_settings) if package_state is not None else {}
        )
        source_settings = dict(package_settings.get("sensors", {}).get(source_type, {}))
        default_settings = spec.metadata.get("default_settings", {})
        allowed_edge_whitelist = [
            str(edge_type)
            for edge_type in source_settings.get(
                "edge_whitelist",
                default_settings.get("edge_whitelist", []),
            )
        ]
        return _SensorSyncSettings(
            package_settings=package_settings,
            allowed_edge_whitelist=allowed_edge_whitelist,
            limit=int(source_settings.get("max_items_per_sync", 200)),
        )

    async def _ingest_sensor_sync_items(
        self,
        *,
        sensor: Any,
        result: Any,
        schedule_id: str,
        target_key: str,
        manual: bool,
        allowed_edge_whitelist: list[str],
        ingestion_boundary: SensorIngestionBoundary,
        allow_pre_clear_events: bool,
    ) -> bool:
        sorted_items = sorted(
            result.items,
            key=lambda it: float(it.get("modified_at") or 0.0),
        )
        checkpoint_modified_cursor = _should_checkpoint_modified_cursor(result.stats)
        total_items = len(sorted_items)
        clear_boundary_crossed = False
        for idx, item in enumerate(sorted_items):
            ingestion_result = await self._ingest_sensor_sync_item(
                sensor=sensor,
                item=item,
                schedule_id=schedule_id,
                target_key=target_key,
                manual=manual,
                allowed_edge_whitelist=allowed_edge_whitelist,
                ingestion_boundary=ingestion_boundary,
                allow_pre_clear_events=allow_pre_clear_events,
            )
            if ingestion_result.stats.get("skip_reason") == "memory_clear_epoch_changed":
                clear_boundary_crossed = True
            await self._checkpoint_sensor_sync_cursor(
                item=item,
                item_index=idx,
                total_items=total_items,
                target_key=target_key,
                checkpoint_modified_cursor=checkpoint_modified_cursor,
            )
        return clear_boundary_crossed

    async def _ingest_sensor_sync_item(
        self,
        *,
        sensor: Any,
        item: dict[str, Any],
        schedule_id: str,
        target_key: str,
        manual: bool,
        allowed_edge_whitelist: list[str],
        ingestion_boundary: SensorIngestionBoundary,
        allow_pre_clear_events: bool,
    ) -> SensorIngestionResult:
        fetched = await sensor.fetch_item(item)
        output = await sensor.build_output(fetched)
        metadata = await sensor.extract_metadata(fetched)
        output.provenance.update(
            {
                "scheduler_schedule_id": schedule_id,
                "scheduler_target_key": target_key,
                "sensor_sync_mode": "manual" if manual else "scheduled",
            }
        )
        ingestion_result = await self._ingestion_gateway.ingest(
            sensor,
            output,
            metadata,
            allowed_edge_whitelist=allowed_edge_whitelist,
            boundary=ingestion_boundary,
            allow_pre_clear_events=allow_pre_clear_events,
        )
        if not ingestion_result.ingested:
            raise RuntimeError(f"Sensor ingestion was not confirmed: {sensor.sensor_id}")
        return ingestion_result

    async def _checkpoint_sensor_sync_cursor(
        self,
        *,
        item: dict[str, Any],
        item_index: int,
        total_items: int,
        target_key: str,
        checkpoint_modified_cursor: bool,
    ) -> None:
        checkpoint_interval = 50
        if not checkpoint_modified_cursor or (item_index + 1) % checkpoint_interval != 0:
            return
        if item_index + 1 >= total_items:
            return
        item_mtime = float(item.get("modified_at") or 0.0)
        if item_mtime <= 0:
            return
        try:
            await self._scheduler_service.update_target_cursor(
                ScheduledTargetType.SENSOR_SYNC,
                target_key,
                cursor=str(item_mtime),
                watermark_ts=item_mtime,
            )
        except Exception:
            logger.debug("Mid-batch cursor save failed", target_key=target_key)


def _should_checkpoint_modified_cursor(stats: Any) -> bool:
    stats_dict = dict(stats or {})
    cursor_kind = str(stats_dict.get("cursor_kind") or "modified_at").strip().lower()
    return cursor_kind in {"modified_at", "mtime", "timestamp"}


def _extract_backfill_sync_request(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    request = payload.get("sync_request")
    if not isinstance(request, dict):
        return None
    if request.get("mode") != "backfill":
        return None
    scope = str(request.get("backfill_scope") or "last_30_days").strip() or "last_30_days"
    normalized: dict[str, Any] = {
        "mode": "backfill",
        "backfill_scope": scope,
    }
    days = request.get("backfill_days")
    if days is not None:
        try:
            normalized["backfill_days"] = int(days)
        except (TypeError, ValueError):
            pass
    start_date = _normalize_optional_date(request.get("backfill_start_date"))
    end_date = _normalize_optional_date(request.get("backfill_end_date"))
    if start_date is not None:
        normalized["backfill_start_date"] = start_date
    if end_date is not None:
        normalized["backfill_end_date"] = end_date
    return normalized


def _apply_backfill_sync_request(
    *,
    settings: _SensorSyncSettings,
    source_type: str,
    sync_request: dict[str, Any],
) -> _SensorSyncSettings:
    package_settings = copy.deepcopy(settings.package_settings)
    sensors_settings = package_settings.get("sensors")
    if not isinstance(sensors_settings, dict):
        sensors_settings = {}
        package_settings["sensors"] = sensors_settings
    source_settings = sensors_settings.get(source_type)
    if not isinstance(source_settings, dict):
        source_settings = {}
    else:
        source_settings = dict(source_settings)
    sensors_settings[source_type] = source_settings

    if sync_request.get("backfill_scope") == "custom":
        source_settings["initial_sync_policy"] = "custom_range"
        source_settings.pop("initial_sync_lookback_days", None)
        start_date = _normalize_optional_date(sync_request.get("backfill_start_date"))
        end_date = _normalize_optional_date(sync_request.get("backfill_end_date"))
        if start_date is not None:
            source_settings["initial_sync_start_date"] = start_date
        if end_date is not None:
            source_settings["initial_sync_end_date"] = end_date
    elif sync_request.get("backfill_scope") == "full":
        source_settings["initial_sync_policy"] = "full"
        source_settings.pop("initial_sync_lookback_days", None)
    else:
        source_settings["initial_sync_policy"] = "lookback_days"
        days = sync_request.get("backfill_days")
        if days is not None:
            source_settings["initial_sync_lookback_days"] = int(days)

    return _SensorSyncSettings(
        package_settings=package_settings,
        allowed_edge_whitelist=settings.allowed_edge_whitelist,
        limit=settings.limit,
    )


def _normalize_optional_date(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _merge_sync_request_stats(
    stats: dict[str, Any] | None,
    sync_request: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if sync_request is None:
        return stats
    merged = dict(stats or {})
    merged["sync_request"] = dict(sync_request)
    return merged
