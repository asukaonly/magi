"""Sensor layer's integration with the unified scheduler."""

from __future__ import annotations

import asyncio
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
    from .ingestion_gateway import SensorIngestionGateway

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
        ingestion_gateway: SensorIngestionGateway | None = None,
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

    async def queue_manual_sync(self, source_type: str) -> ScheduleDefinition:
        resolved = self._sensor_registry.resolve_source_sensor(source_type)
        if resolved is None:
            raise KeyError(source_type)
        plugin_id, _, sensor, _ = resolved
        if not bool(getattr(sensor, "supports_pull_sync", False)):
            raise ValueError(f"Sensor source does not support pull sync: {source_type}")
        schedule_id = f"sensor-sync-manual:{plugin_id}:{source_type}:{uuid.uuid4().hex}"
        return await self._scheduler_service.schedule_once(
            schedule_id=schedule_id,
            target_type=ScheduledTargetType.SENSOR_SYNC,
            target_key=build_sensor_target_key(plugin_id, source_type),
            run_at=time.time(),
            target_payload={
                "plugin_id": plugin_id,
                "source_type": source_type,
                "manual": True,
            },
            metadata={"manual": True, "source_type": source_type, "plugin_id": plugin_id},
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
    ) -> ScheduledExecutionResult:
        target = self._resolve_sensor_sync_target(source_type)
        settings = self._sensor_sync_settings(
            plugin_id=target.plugin_id,
            source_type=source_type,
            spec=target.spec,
        )
        preferred_language = get_preferred_language()
        if preferred_language:
            settings.package_settings.setdefault("locale", preferred_language)
        previous_language = get_plugin_current_language()
        set_plugin_current_language(preferred_language or None)
        try:
            pull_context = SensorSyncContext(
                source_type=source_type,
                manual=manual,
                last_cursor=target_state.last_cursor,
                last_success_at=target_state.last_success_at,
                limit=settings.limit,
                runtime_paths=self._runtime_paths,
                plugin_settings=settings.package_settings,
            )
            result = await target.sensor.collect_items(pull_context)
            await self._ingest_sensor_sync_items(
                sensor=target.sensor,
                result=result,
                schedule_id=schedule_id,
                target_key=target_key,
                manual=manual,
                allowed_edge_whitelist=settings.allowed_edge_whitelist,
            )
            return ScheduledExecutionResult(
                success=True,
                message="sensor_sync_completed",
                next_cursor=result.next_cursor,
                watermark_ts=result.watermark_ts,
                stats=result.stats,
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
        package_settings = dict(package_state.current_settings) if package_state is not None else {}
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
    ) -> None:
        sorted_items = sorted(
            result.items,
            key=lambda it: float(it.get("modified_at") or 0.0),
        )
        checkpoint_modified_cursor = _should_checkpoint_modified_cursor(result.stats)
        total_items = len(sorted_items)
        for idx, item in enumerate(sorted_items):
            await self._ingest_sensor_sync_item(
                sensor=sensor,
                item=item,
                schedule_id=schedule_id,
                target_key=target_key,
                manual=manual,
                allowed_edge_whitelist=allowed_edge_whitelist,
            )
            await self._checkpoint_sensor_sync_cursor(
                item=item,
                item_index=idx,
                total_items=total_items,
                target_key=target_key,
                checkpoint_modified_cursor=checkpoint_modified_cursor,
            )

    async def _ingest_sensor_sync_item(
        self,
        *,
        sensor: Any,
        item: dict[str, Any],
        schedule_id: str,
        target_key: str,
        manual: bool,
        allowed_edge_whitelist: list[str],
    ) -> None:
        fetched = await sensor.fetch_item(item)
        if self._ingestion_gateway is None:
            raise RuntimeError("SensorIngestionGateway is required for sensor sync")
        output = await sensor.build_output(fetched)
        metadata = await sensor.extract_metadata(fetched)
        output.provenance.update(
            {
                "scheduler_schedule_id": schedule_id,
                "scheduler_target_key": target_key,
                "sensor_sync_mode": "manual" if manual else "scheduled",
            }
        )
        await self._ingestion_gateway.ingest(
            sensor,
            output,
            metadata,
            allowed_edge_whitelist=allowed_edge_whitelist,
        )

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
