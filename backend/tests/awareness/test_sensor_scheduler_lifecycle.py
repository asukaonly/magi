from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.awareness.sensor_base import SensorBase
from magi.awareness.sensor_output import (
    ActivityFacet,
    ContentBlock,
    SensorActivity,
    SensorMemoryPolicy,
    SensorNarration,
)
from magi.awareness.scheduler_contrib import SensorSchedulerContrib
from magi.awareness.sensor_sync import PullSyncSensor, SensorSyncResult
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.plugins.sensors import SensorRegistry, SensorSpec
from magi.scheduler.contracts import ScheduledTargetState, ScheduledTargetType, build_sensor_target_key
from magi.utils.runtime import RuntimePaths


class _FakeUnifiedMemory:
    async def ingest_event(self, event_dict):
        pass

    async def upsert_user_graph_edge(self, **kwargs):
        pass


class _FakeTimelineService:
    async def on_sensor_output(self, *args, **kwargs):
        return None


class _FakePluginManager:
    def __init__(self) -> None:
        self.package = type(
            "Package",
            (),
            {
                "current_settings": {
                    "sensors": {
                        "pull_history": {
                            "enabled": True,
                            "sync_mode": "interval",
                            "sync_interval_minutes": 5,
                            "edge_whitelist": ["LIKES"],
                        }
                    }
                }
            },
        )()

    def get_package(self, plugin_id: str):
        return self.package if plugin_id == "pull-plugin" else None


class _FakeSchedulerRepository:
    def __init__(self) -> None:
        self.schedules: dict[str, object] = {}

    async def get_schedule(self, schedule_id: str):
        return self.schedules.get(schedule_id)


class _FakeSchedulerService:
    def __init__(self) -> None:
        self.registrations: list[tuple[object, object]] = []
        self.repository = _FakeSchedulerRepository()
        self.interval_calls: list[dict[str, object]] = []
        self.unschedule_calls: list[dict[str, object]] = []
        self.once_calls: list[dict[str, object]] = []
        self.cursor_updates: list[dict[str, object]] = []

    def register_handler(self, target_type, handler) -> None:  # type: ignore[no-untyped-def]
        self.registrations.append((target_type, handler))

    async def schedule_interval(self, **kwargs):  # type: ignore[no-untyped-def]
        self.interval_calls.append(kwargs)
        schedule = type("Schedule", (), {"schedule_id": kwargs["schedule_id"], "job_id": kwargs["schedule_id"]})()
        self.repository.schedules[kwargs["schedule_id"]] = schedule
        return schedule

    async def unschedule(self, schedule_id, **kwargs):  # type: ignore[no-untyped-def]
        self.unschedule_calls.append({"schedule_id": schedule_id, **kwargs})
        self.repository.schedules.pop(schedule_id, None)

    async def schedule_once(self, **kwargs):  # type: ignore[no-untyped-def]
        self.once_calls.append(kwargs)
        return type("Schedule", (), {"schedule_id": kwargs["schedule_id"]})()

    async def update_target_cursor(self, target_type, target_key, *, cursor, watermark_ts=None):  # type: ignore[no-untyped-def]
        self.cursor_updates.append(
            {
                "target_type": target_type,
                "target_key": target_key,
                "cursor": cursor,
                "watermark_ts": watermark_ts,
            }
        )


class _PullHistorySensor(SensorBase, PullSyncSensor):
    sensor_id = "timeline.pull_history"
    display_name = "Pull History"
    source_type = "pull_history"
    supports_pull_sync = True
    memory_policy = SensorMemoryPolicy()

    async def collect_items(self, context):
        return SensorSyncResult(
            items=[
                {
                    "item_id": "item-1",
                    "title": "Pulled item",
                    "timestamp": 1710000000.0,
                    "relation_candidates": [],
                }
            ],
            next_cursor="cursor-2",
            watermark_ts=1710000000.0,
            stats={"count": 1},
        )

    async def build_output(self, item):
        return self._build_output(
            source_item_id=str(item["item_id"]),
            activity=SensorActivity(
                source=ActivityFacet(
                    code="test_source",
                    i18n_key="activity.source.test",
                    fallback="test source",
                ),
                action=ActivityFacet(
                    code="pull",
                    i18n_key="activity.action.pull",
                    fallback="pull",
                ),
                object=ActivityFacet(
                    code=str(item["item_id"]),
                    i18n_key="activity.object.item",
                    fallback=str(item["title"]),
                ),
            ),
            narration=SensorNarration(
                title=str(item["title"]),
                body=str(item["title"]),
            ),
            occurred_at=float(item["timestamp"]),
            content_blocks=[ContentBlock(kind="text", value=str(item["title"]))],
        )


class _OpaqueCursorSensor(_PullHistorySensor):
    async def collect_items(self, context):
        return SensorSyncResult(
            items=[
                {
                    "item_id": f"item-{idx}",
                    "title": f"Pulled item {idx}",
                    "timestamp": 1710000000.0 + idx,
                    "modified_at": 1710000000.0 + idx,
                    "relation_candidates": [],
                }
                for idx in range(55)
            ],
            next_cursor='{"version":1,"mode":"backfill","page":2}',
            watermark_ts=1710000055.0,
            stats={"count": 55, "cursor_kind": "opaque"},
        )


class _ContextRecordingSensor(_PullHistorySensor):
    def __init__(self) -> None:
        self.contexts: list[object] = []

    async def collect_items(self, context):
        self.contexts.append(context)
        return SensorSyncResult(
            items=[],
            next_cursor=None,
            watermark_ts=None,
            stats={"count": 0},
        )


def _build_sensor_registry() -> SensorRegistry:
    sensor_registry = SensorRegistry()
    sensor_registry.register(
        "pull-plugin",
        "timeline.pull_history",
        _PullHistorySensor(),
        SensorSpec(
            sensor_id="timeline.pull_history",
            display_name="Pull History",
            description="Pull-capable sensor",
            domain="timeline",
            surface="timeline",
            sync_mode="interval",
            metadata={
                "source_type": "pull_history",
                "default_settings": {
                    "enabled": True,
                    "sync_mode": "interval",
                    "sync_interval_minutes": 5,
                    "edge_whitelist": ["LIKES"],
                },
            },
        ),
    )
    return sensor_registry


def _build_sensor_registry_with_sensor(sensor: SensorBase) -> SensorRegistry:
    sensor_registry = SensorRegistry()
    sensor_registry.register(
        "pull-plugin",
        "timeline.pull_history",
        sensor,
        SensorSpec(
            sensor_id="timeline.pull_history",
            display_name="Pull History",
            description="Pull-capable sensor",
            domain="timeline",
            surface="timeline",
            sync_mode="interval",
            metadata={
                "source_type": "pull_history",
                "default_settings": {
                    "enabled": True,
                    "sync_mode": "interval",
                    "sync_interval_minutes": 5,
                    "edge_whitelist": ["LIKES"],
                },
            },
        ),
    )
    return sensor_registry


class _FakeIngestionGateway:
    def __init__(self) -> None:
        self.items: list[object] = []

    async def ingest(self, sensor, output, metadata, *, allowed_edge_whitelist=None):  # type: ignore[no-untyped-def]
        self.items.append(output)


@pytest.mark.asyncio
async def test_sensor_schedule_registration_module_registers_handler_and_syncs_schedules(monkeypatch, tmp_path) -> None:
    from magi.awareness.lifecycle import SensorScheduleRegistrationModule
    from magi.scheduler.contracts import ScheduledTargetType, build_sensor_schedule_id

    context = RuntimeBootstrapContext()
    context.core.runtime_paths = RuntimePaths(tmp_path / "runtime")
    context.plugins.sensor_registry = _build_sensor_registry()
    context.plugins.plugin_manager = _FakePluginManager()
    context.timeline.timeline_service = _FakeTimelineService()
    context.scheduler.scheduler_service = _FakeSchedulerService()
    context.memory.unified_memory = _FakeUnifiedMemory()
    context.message_bus.message_bus = MagicMock(publish=AsyncMock())

    module = SensorScheduleRegistrationModule(context)
    await module.init()

    registrations = context.scheduler.scheduler_service.registrations
    assert len(registrations) == 1
    assert registrations[0][0] == ScheduledTargetType.SENSOR_SYNC
    assert context.scheduler.scheduler_service.interval_calls[0]["schedule_id"] == build_sensor_schedule_id(
        "pull-plugin",
        "pull_history",
    )
    assert context.agent_runtime.sensor_scheduler_contrib is not None

    await module.shutdown()
    assert context.agent_runtime.sensor_scheduler_contrib is None


@pytest.mark.asyncio
async def test_sensor_schedule_registration_module_supports_manual_sync(tmp_path) -> None:
    from magi.awareness.lifecycle import SensorScheduleRegistrationModule

    context = RuntimeBootstrapContext()
    context.core.runtime_paths = RuntimePaths(tmp_path / "runtime")
    context.plugins.sensor_registry = _build_sensor_registry()
    context.plugins.plugin_manager = _FakePluginManager()
    context.timeline.timeline_service = _FakeTimelineService()
    context.scheduler.scheduler_service = _FakeSchedulerService()
    context.memory.unified_memory = _FakeUnifiedMemory()
    context.message_bus.message_bus = MagicMock(publish=AsyncMock())

    module = SensorScheduleRegistrationModule(context)
    await module.init()

    schedule = await module.queue_manual_sync("pull_history")

    assert schedule.schedule_id.startswith("sensor-sync-manual:pull-plugin:pull_history:")
    assert context.scheduler.scheduler_service.once_calls[0]["run_at"] <= time.time() + 1.0

    await module.shutdown()


@pytest.mark.asyncio
async def test_sensor_schedule_registration_module_queues_backfill_with_stable_scope(tmp_path) -> None:
    from magi.awareness.lifecycle import SensorScheduleRegistrationModule

    context = RuntimeBootstrapContext()
    context.core.runtime_paths = RuntimePaths(tmp_path / "runtime")
    context.plugins.sensor_registry = _build_sensor_registry()
    context.plugins.plugin_manager = _FakePluginManager()
    context.timeline.timeline_service = _FakeTimelineService()
    context.scheduler.scheduler_service = _FakeSchedulerService()
    context.memory.unified_memory = _FakeUnifiedMemory()
    context.message_bus.message_bus = MagicMock(publish=AsyncMock())

    module = SensorScheduleRegistrationModule(context)
    await module.init()

    first = await module.queue_manual_sync(
        "pull_history",
        sync_mode="backfill",
        backfill_scope="last_30_days",
        backfill_days=30,
    )
    second = await module.queue_manual_sync(
        "pull_history",
        sync_mode="backfill",
        backfill_scope="last_30_days",
        backfill_days=30,
    )

    assert first.schedule_id == "sensor-sync-backfill:pull-plugin:pull_history:last_30_days"
    assert second.schedule_id == first.schedule_id
    once_call = context.scheduler.scheduler_service.once_calls[0]
    assert once_call["target_payload"]["sync_request"] == {
        "mode": "backfill",
        "backfill_scope": "last_30_days",
        "backfill_days": 30,
    }
    assert once_call["metadata"]["sync_request"] == {
        "mode": "backfill",
        "backfill_scope": "last_30_days",
        "backfill_days": 30,
    }

    await module.shutdown()


@pytest.mark.asyncio
async def test_sensor_schedule_registration_module_queues_custom_backfill_with_stable_range(tmp_path) -> None:
    from magi.awareness.lifecycle import SensorScheduleRegistrationModule

    context = RuntimeBootstrapContext()
    context.core.runtime_paths = RuntimePaths(tmp_path / "runtime")
    context.plugins.sensor_registry = _build_sensor_registry()
    context.plugins.plugin_manager = _FakePluginManager()
    context.timeline.timeline_service = _FakeTimelineService()
    context.scheduler.scheduler_service = _FakeSchedulerService()
    context.memory.unified_memory = _FakeUnifiedMemory()
    context.message_bus.message_bus = MagicMock(publish=AsyncMock())

    module = SensorScheduleRegistrationModule(context)
    await module.init()

    first = await module.queue_manual_sync(
        "pull_history",
        sync_mode="backfill",
        backfill_scope="custom",
        backfill_start_date="2026-06-01",
        backfill_end_date="2026-06-30",
    )
    second = await module.queue_manual_sync(
        "pull_history",
        sync_mode="backfill",
        backfill_scope="custom",
        backfill_start_date="2026-06-01",
        backfill_end_date="2026-06-30",
    )

    assert first.schedule_id == "sensor-sync-backfill:pull-plugin:pull_history:custom:2026-06-01:2026-06-30"
    assert second.schedule_id == first.schedule_id
    once_call = context.scheduler.scheduler_service.once_calls[0]
    assert once_call["target_payload"]["sync_request"] == {
        "mode": "backfill",
        "backfill_scope": "custom",
        "backfill_start_date": "2026-06-01",
        "backfill_end_date": "2026-06-30",
    }
    assert once_call["metadata"]["sync_request"] == {
        "mode": "backfill",
        "backfill_scope": "custom",
        "backfill_start_date": "2026-06-01",
        "backfill_end_date": "2026-06-30",
    }

    await module.shutdown()


@pytest.mark.asyncio
async def test_sensor_sync_backfill_request_uses_initial_history_context(tmp_path) -> None:
    scheduler_service = _FakeSchedulerService()
    ingestion_gateway = _FakeIngestionGateway()
    sensor = _ContextRecordingSensor()
    contrib = SensorSchedulerContrib(
        scheduler_service=scheduler_service,
        sensor_registry=_build_sensor_registry_with_sensor(sensor),
        plugin_manager=_FakePluginManager(),
        runtime_paths=RuntimePaths(tmp_path / "runtime"),
        get_config=lambda: None,
        ingestion_gateway=ingestion_gateway,
    )

    await contrib._run_sensor_sync(
        schedule_id="sensor-sync-backfill:pull-plugin:pull_history:last_30_days",
        target_key=build_sensor_target_key("pull-plugin", "pull_history"),
        source_type="pull_history",
        manual=True,
        target_state=ScheduledTargetState(
            target_type=ScheduledTargetType.SENSOR_SYNC,
            target_key=build_sensor_target_key("pull-plugin", "pull_history"),
            last_cursor="existing-cursor",
            last_success_at=1710000000.0,
        ),
        sync_payload={
            "sync_request": {
                "mode": "backfill",
                "backfill_scope": "last_30_days",
                "backfill_days": 30,
            }
        },
    )

    assert len(sensor.contexts) == 1
    context = sensor.contexts[0]
    assert context.last_cursor is None
    source_settings = context.plugin_settings["sensors"]["pull_history"]
    assert source_settings["initial_sync_policy"] == "lookback_days"
    assert source_settings["initial_sync_lookback_days"] == 30


@pytest.mark.asyncio
async def test_sensor_sync_custom_backfill_request_uses_custom_history_context(tmp_path) -> None:
    scheduler_service = _FakeSchedulerService()
    ingestion_gateway = _FakeIngestionGateway()
    sensor = _ContextRecordingSensor()
    contrib = SensorSchedulerContrib(
        scheduler_service=scheduler_service,
        sensor_registry=_build_sensor_registry_with_sensor(sensor),
        plugin_manager=_FakePluginManager(),
        runtime_paths=RuntimePaths(tmp_path / "runtime"),
        get_config=lambda: None,
        ingestion_gateway=ingestion_gateway,
    )

    await contrib._run_sensor_sync(
        schedule_id="sensor-sync-backfill:pull-plugin:pull_history:custom:2026-06-01:2026-06-30",
        target_key=build_sensor_target_key("pull-plugin", "pull_history"),
        source_type="pull_history",
        manual=True,
        target_state=ScheduledTargetState(
            target_type=ScheduledTargetType.SENSOR_SYNC,
            target_key=build_sensor_target_key("pull-plugin", "pull_history"),
            last_cursor="existing-cursor",
            last_success_at=1710000000.0,
        ),
        sync_payload={
            "sync_request": {
                "mode": "backfill",
                "backfill_scope": "custom",
                "backfill_start_date": "2026-06-01",
                "backfill_end_date": "2026-06-30",
            }
        },
    )

    assert len(sensor.contexts) == 1
    context = sensor.contexts[0]
    assert context.last_cursor is None
    source_settings = context.plugin_settings["sensors"]["pull_history"]
    assert source_settings["initial_sync_policy"] == "custom_range"
    assert source_settings["initial_sync_start_date"] == "2026-06-01"
    assert source_settings["initial_sync_end_date"] == "2026-06-30"


@pytest.mark.asyncio
async def test_sensor_sync_backfill_continuation_keeps_backfill_cursor(tmp_path) -> None:
    scheduler_service = _FakeSchedulerService()
    ingestion_gateway = _FakeIngestionGateway()
    sensor = _ContextRecordingSensor()
    contrib = SensorSchedulerContrib(
        scheduler_service=scheduler_service,
        sensor_registry=_build_sensor_registry_with_sensor(sensor),
        plugin_manager=_FakePluginManager(),
        runtime_paths=RuntimePaths(tmp_path / "runtime"),
        get_config=lambda: None,
        ingestion_gateway=ingestion_gateway,
    )

    await contrib._run_sensor_sync(
        schedule_id="sensor-sync-continuation:pull-plugin:pull_history:abc123",
        target_key=build_sensor_target_key("pull-plugin", "pull_history"),
        source_type="pull_history",
        manual=True,
        target_state=ScheduledTargetState(
            target_type=ScheduledTargetType.SENSOR_SYNC,
            target_key=build_sensor_target_key("pull-plugin", "pull_history"),
            last_cursor='{"version":1,"mode":"backfill","capture_before":1718409600}',
            last_success_at=1710000000.0,
        ),
        sync_payload={
            "sync_request": {
                "mode": "backfill",
                "backfill_scope": "custom",
                "backfill_start_date": "2026-06-01",
                "backfill_end_date": "2026-06-30",
            }
        },
    )

    assert len(sensor.contexts) == 1
    assert sensor.contexts[0].last_cursor == '{"version":1,"mode":"backfill","capture_before":1718409600}'


@pytest.mark.asyncio
async def test_sensor_sync_opaque_cursor_skips_mid_batch_checkpoint(tmp_path) -> None:
    scheduler_service = _FakeSchedulerService()
    ingestion_gateway = _FakeIngestionGateway()
    contrib = SensorSchedulerContrib(
        scheduler_service=scheduler_service,
        sensor_registry=_build_sensor_registry_with_sensor(_OpaqueCursorSensor()),
        plugin_manager=_FakePluginManager(),
        runtime_paths=RuntimePaths(tmp_path / "runtime"),
        get_config=lambda: None,
        ingestion_gateway=ingestion_gateway,
    )

    result = await contrib._run_sensor_sync(
        schedule_id="sensor-sync:pull-plugin:pull_history",
        target_key=build_sensor_target_key("pull-plugin", "pull_history"),
        source_type="pull_history",
        manual=False,
        target_state=ScheduledTargetState(
            target_type=ScheduledTargetType.SENSOR_SYNC,
            target_key=build_sensor_target_key("pull-plugin", "pull_history"),
            last_cursor=None,
            last_success_at=None,
        ),
    )

    assert result.next_cursor == '{"version":1,"mode":"backfill","page":2}'
    assert len(ingestion_gateway.items) == 55
    assert scheduler_service.cursor_updates == []
