"""Runtime bootstrap helpers for scheduler-backed targets."""
from __future__ import annotations

import time
import uuid

from ..core.runtime.contracts import FactRecord
from ..plugins.actions import ActionExecutionContext, ActionRegistry
from ..plugins.sensors import SensorRegistry
from ..timeline.contracts import TimelineEvent
from ..timeline.service import TimelineService
from ..timeline.sync import SensorSyncContext
from ..utils.runtime import Runtimepaths
from .contracts import (
    ScheduleDefinition,
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from .service import SchedulerService


def build_timeline_target_key(plugin_id: str, source_type: str) -> str:
    """Build stable scheduler target key for a timeline source."""

    return f"{plugin_id}:{source_type}"


def build_timeline_schedule_id(plugin_id: str, source_type: str) -> str:
    """Build stable recurring schedule id for a timeline source."""

    return f"timeline-sync:{plugin_id}:{source_type}"


class SchedulerBootstrap:
    """Registers runtime handlers and synchronizes plugin-backed schedules."""

    def __init__(
        self,
        *,
        scheduler_service: SchedulerService,
        sensor_registry: SensorRegistry,
        action_registry: ActionRegistry,
        plugin_manager,
        timeline_service: TimelineService,
        runtime_paths: Runtimepaths,
        task_agent_manager,
        action_executor,
        get_config,
    ) -> None:
        self._scheduler_service = scheduler_service
        self._sensor_registry = sensor_registry
        self._action_registry = action_registry
        self._plugin_manager = plugin_manager
        self._timeline_service = timeline_service
        self._runtime_paths = runtime_paths
        self._task_agent_manager = task_agent_manager
        self._action_executor = action_executor
        self._get_config = get_config

    def register_handlers(self) -> None:
        self._scheduler_service.register_handler(
            ScheduledTargetType.TIMELINE_SENSOR_SYNC,
            self._handle_timeline_sensor_sync,
        )
        self._scheduler_service.register_handler(
            ScheduledTargetType.AGENT_TASK,
            self._handle_agent_task,
        )
        self._scheduler_service.register_handler(
            ScheduledTargetType.ACTION_DISPATCH,
            self._handle_action_dispatch,
        )

    async def sync_timeline_sensor_schedules(self) -> None:
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
                await self._scheduler_service.unschedule(schedule_id)
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

    async def queue_manual_timeline_sync(self, source_type: str) -> ScheduleDefinition:
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

    async def _handle_agent_task(
        self,
        context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        payload = dict(context.schedule.target_payload)
        agent_type = str(payload.pop("agent_type"))
        agent_id = str(payload.pop("agent_id"))
        event_type = str(payload.pop("event_type", "ScheduledAgentTask"))
        fact = FactRecord(
            agent_id=f"{agent_type}:{agent_id}",
            event_type=event_type,
            payload=payload,
            agent_type=agent_type,
            agent_instance_id=agent_id,
            correlation_id=str(payload.get("correlation_id") or uuid.uuid4()),
        )
        added = await self._task_agent_manager.add_fact_to_agent(agent_type, agent_id, fact)
        if not added:
            raise RuntimeError("Failed to enqueue scheduled agent task")
        return ScheduledExecutionResult(success=True, message="agent_task_enqueued")

    async def _handle_action_dispatch(
        self,
        context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        payload = dict(context.schedule.target_payload)
        action_id = str(payload.get("action_id") or "")
        parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
        action = self._action_registry.get_action(action_id)
        if action is None:
            raise RuntimeError(f"Unknown action: {action_id}")
        result = await action.execute(
            parameters,
            ActionExecutionContext(
                user_id=str(payload.get("user_id") or "") or None,
                session_id=str(payload.get("session_id") or "") or None,
                runtime_key=context.schedule.schedule_id,
                metadata={"scheduled": True, "manual": context.manual},
            ),
        )
        await self._action_executor.emit_action_event(
            fact=FactRecord(
                agent_id=str(payload.get("user_id") or "scheduler"),
                event_type="ScheduledActionDispatch",
                payload={
                    "action_type": action_id,
                    "params": parameters,
                    "response": str(result),
                    "execution_time": 0.0,
                    "user_id": payload.get("user_id"),
                    "session_id": payload.get("session_id"),
                },
                correlation_id=str(payload.get("correlation_id") or uuid.uuid4()),
            ),
            success=True,
            error=None,
        )
        return ScheduledExecutionResult(
            success=True,
            message="action_dispatched",
            stats={"result": result},
        )
