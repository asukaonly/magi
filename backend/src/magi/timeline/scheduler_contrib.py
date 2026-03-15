"""Timeline layer's integration with the unified scheduler."""
from __future__ import annotations

import uuid
import time
from typing import Any, Callable

from ..plugins.sensors import SensorRegistry
from ..utils.runtime import RuntimePaths
from .contracts import TimelineEvent
from .service import TimelineService
from .sync import SensorSyncContext
from ..scheduler.contracts import (
    ScheduleDefinition,
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from ..scheduler.service import SchedulerService


_timeline_contrib: TimelineSchedulerContrib | None = None


def get_timeline_scheduler_contrib() -> TimelineSchedulerContrib | None:
    """Return the active timeline scheduler contrib instance."""
    return _timeline_contrib


def set_timeline_scheduler_contrib(contrib: TimelineSchedulerContrib | None) -> None:
    """Set the active timeline scheduler contrib instance."""
    global _timeline_contrib
    _timeline_contrib = contrib


def build_timeline_target_key(plugin_id: str, source_type: str) -> str:
    """Build stable scheduler target key for a timeline source."""
    return f"{plugin_id}:{source_type}"


def build_timeline_schedule_id(plugin_id: str, source_type: str) -> str:
    """Build stable recurring schedule id for a timeline source."""
    return f"timeline-sync:{plugin_id}:{source_type}"


class TimelineSchedulerContrib:
    """Registers timeline-specific scheduled sync handlers and manages sensor schedules."""

    def __init__(
        self,
        *,
        scheduler_service: SchedulerService,
        sensor_registry: SensorRegistry,
        plugin_manager: Any,
        timeline_service: TimelineService,
        runtime_paths: RuntimePaths,
        get_config: Callable[[], Any],
    ) -> None:
        self._scheduler_service = scheduler_service
        self._sensor_registry = sensor_registry
        self._plugin_manager = plugin_manager
        self._timeline_service = timeline_service
        self._runtime_paths = runtime_paths
        self._get_config = get_config

    def register_handler(self) -> None:
        """Register the TIMELINE_SENSOR_SYNC handler with the scheduler service."""
        self._scheduler_service.register_handler(
            ScheduledTargetType.TIMELINE_SENSOR_SYNC,
            self._handle_timeline_sensor_sync,
        )

    async def sync_schedules(self) -> None:
        """Synchronize timeline sensor schedules based on plugin config."""
        config = self._get_config()
        for contribution in self._sensor_registry.list_contributions():
            if contribution.metadata.get("domain") != "timeline":
                continue
            source_type = str(contribution.metadata.get("source_type") or contribution.contribution_id.split(".")[-1])
            resolved = self._sensor_registry.resolve_domain_sensor("timeline", source_type)
            if resolved is None:
                continue
            plugin_id, _, sensor, spec = resolved
            schedule_id = build_timeline_schedule_id(plugin_id, source_type)
            package_state = self._plugin_manager.get_package(plugin_id)
            current_settings = package_state.current_settings if package_state is not None else {}
            default_settings = dict(spec.metadata.get("default_settings", {}))
            source_settings = dict(current_settings.get("sensors", {}).get(source_type, {}))
            enabled = bool(source_settings.get("enabled", default_settings.get("enabled", True)))
            sync_mode = str(source_settings.get("sync_mode", default_settings.get("sync_mode", spec.sync_mode)))
            interval_minutes = float(source_settings.get("sync_interval_minutes", default_settings.get("sync_interval_minutes", 1)))
            supports_pull_sync = bool(getattr(sensor, "supports_pull_sync", False))
            if (not config.timeline.enabled) or (not enabled) or (not supports_pull_sync) or sync_mode == "manual":
                await self._scheduler_service.unschedule(
                    schedule_id,
                    target_type=ScheduledTargetType.TIMELINE_SENSOR_SYNC,
                    target_key=build_timeline_target_key(plugin_id, source_type),
                )
                continue
            if sync_mode == "watch" and not bool(getattr(sensor, "supports_watch_mode", False)):
                interval_minutes = max(1.0, interval_minutes)
            await self._scheduler_service.schedule_interval(
                schedule_id=schedule_id,
                target_type=ScheduledTargetType.TIMELINE_SENSOR_SYNC,
                target_key=build_timeline_target_key(plugin_id, source_type),
                seconds=max(1.0, interval_minutes * 60.0),
                target_payload={
                    "plugin_id": plugin_id,
                    "source_type": source_type,
                    "manual": False,
                },
                metadata={"source_type": source_type, "plugin_id": plugin_id},
            )

    async def queue_manual_sync(self, source_type: str) -> ScheduleDefinition:
        """Queue a one-time immediate sync for a timeline source."""
        resolved = self._sensor_registry.resolve_domain_sensor("timeline", source_type)
        if resolved is None:
            raise KeyError(source_type)
        plugin_id, _, sensor, _ = resolved
        if not bool(getattr(sensor, "supports_pull_sync", False)):
            raise ValueError(f"Timeline source does not support pull sync: {source_type}")
        schedule_id = f"timeline-sync-manual:{plugin_id}:{source_type}:{uuid.uuid4().hex}"
        return await self._scheduler_service.schedule_once(
            schedule_id=schedule_id,
            target_type=ScheduledTargetType.TIMELINE_SENSOR_SYNC,
            target_key=build_timeline_target_key(plugin_id, source_type),
            run_at=time.time(),
            target_payload={
                "plugin_id": plugin_id,
                "source_type": source_type,
                "manual": True,
            },
            metadata={"manual": True, "source_type": source_type, "plugin_id": plugin_id},
        )

    async def _handle_timeline_sensor_sync(
        self,
        context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        source_type = str(context.schedule.target_payload.get("source_type") or "")
        resolved = self._sensor_registry.resolve_domain_sensor("timeline", source_type)
        if resolved is None:
            raise RuntimeError(f"Timeline source not found: {source_type}")
        plugin_id, _, sensor, spec = resolved
        if not bool(getattr(sensor, "supports_pull_sync", False)):
            raise RuntimeError(f"Timeline source does not support pull sync: {source_type}")
        package_state = self._plugin_manager.get_package(plugin_id)
        package_settings = package_state.current_settings if package_state is not None else {}
        source_settings = dict(package_settings.get("sensors", {}).get(source_type, {}))
        pull_context = SensorSyncContext(
            source_type=source_type,
            manual=context.manual,
            last_cursor=context.target_state.last_cursor,
            last_success_at=context.target_state.last_success_at,
            limit=int(source_settings.get("max_items_per_sync", 200)),
            runtime_paths=self._runtime_paths,
            plugin_settings=package_settings,
        )
        result = await sensor.collect_items(pull_context)
        allowed_edge_whitelist = [
            str(edge_type)
            for edge_type in source_settings.get(
                "edge_whitelist",
                spec.metadata.get("default_settings", {}).get("edge_whitelist", []),
            )
        ]
        for item in result.items:
            fetched = await sensor.fetch_item(item)
            event: TimelineEvent = await sensor.build_timeline_event(fetched)
            extracted = await sensor.extract_candidates(fetched)
            event.entities = list(extracted.get("entities", []))
            event.tags = list(dict.fromkeys([*event.tags, *list(extracted.get("tags", []))]))
            event.provenance.update(
                {
                    "scheduler_schedule_id": context.schedule.schedule_id,
                    "scheduler_target_key": context.schedule.target_key,
                    "sensor_sync_mode": "manual" if context.manual else "scheduled",
                }
            )
            await self._timeline_service.upsert_event(
                event,
                relation_candidates=list(extracted.get("relation_candidates", [])),
                allowed_edge_whitelist=allowed_edge_whitelist,
            )
        return ScheduledExecutionResult(
            success=True,
            message="timeline_sync_completed",
            next_cursor=result.next_cursor,
            watermark_ts=result.watermark_ts,
            stats=result.stats,
        )
