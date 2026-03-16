from __future__ import annotations

import time

import pytest

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.plugins.sensors import SensorRegistry, SensorSpec
from magi.timeline import SensorSyncResult, TimelineContentBlock, TimelineEvent
from magi.timeline.sensors import TimelineSensorBase
from magi.timeline.sync import PullSyncSensor
from magi.utils.runtime import RuntimePaths


class _FakeTimelineService:
    def __init__(self) -> None:
        self.events: list[TimelineEvent] = []
        self.relations: list[list[dict]] = []

    async def upsert_event(self, event, *, relation_candidates=None, allowed_edge_whitelist=None) -> str:
        self.events.append(event)
        self.relations.append(list(relation_candidates or []))
        return event.event_id


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


class _PullHistorySensor(TimelineSensorBase, PullSyncSensor):
    sensor_id = "timeline.pull_history"
    display_name = "Pull History"
    source_type = "pull_history"
    supports_pull_sync = True

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

    async def build_timeline_event(self, item):
        return self._build_event(
            source_item_id=str(item["item_id"]),
            title=str(item["title"]),
            summary=str(item["title"]),
            occurred_at=float(item["timestamp"]),
            content_blocks=[TimelineContentBlock(kind="text", value=str(item["title"]))],
        )

    async def extract_candidates(self, item):
        return {"entities": [], "tags": ["pull_history"], "relation_candidates": list(item.get("relation_candidates", []))}


def _build_sensor_registry() -> SensorRegistry:
    sensor_registry = SensorRegistry()
    sensor_registry.register(
        "pull-plugin",
        "timeline.pull_history",
        _PullHistorySensor(),
        SensorSpec(
            sensor_id="timeline.pull_history",
            display_name="Pull History",
            description="Pull-capable timeline sensor",
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


def test_timeline_schedule_registration_module_lives_in_timeline_layer() -> None:
    from magi.timeline.lifecycle import TimelineScheduleRegistrationModule

    assert TimelineScheduleRegistrationModule.__module__ == "magi.timeline.lifecycle"


@pytest.mark.asyncio
async def test_timeline_schedule_registration_module_registers_handler_and_syncs_schedules(monkeypatch, tmp_path) -> None:
    from magi.scheduler.contracts import ScheduledTargetType, build_timeline_schedule_id
    from magi.timeline.lifecycle import TimelineScheduleRegistrationModule
    from magi.timeline.scheduler_contrib import get_timeline_scheduler_contrib

    context = RuntimeBootstrapContext()
    context.core.runtime_paths = RuntimePaths(tmp_path / "runtime")
    context.timeline.timeline_service = _FakeTimelineService()
    context.scheduler.scheduler_service = _FakeSchedulerService()

    sensor_registry = _build_sensor_registry()
    plugin_manager = _FakePluginManager()

    monkeypatch.setattr("magi.timeline.lifecycle.get_sensor_registry", lambda: sensor_registry)
    monkeypatch.setattr("magi.timeline.lifecycle.get_plugin_manager", lambda: plugin_manager)
    monkeypatch.setattr(
        "magi.timeline.lifecycle.get_config",
        lambda: type("Config", (), {"timeline": type("Timeline", (), {"enabled": True})()})(),
    )

    module = TimelineScheduleRegistrationModule(context)
    await module.init()

    registrations = context.scheduler.scheduler_service.registrations
    assert len(registrations) == 1
    assert registrations[0][0] == ScheduledTargetType.TIMELINE_SENSOR_SYNC
    assert context.scheduler.scheduler_service.interval_calls[0]["schedule_id"] == build_timeline_schedule_id(
        "pull-plugin",
        "pull_history",
    )
    assert get_timeline_scheduler_contrib() is not None

    await module.shutdown()
    assert get_timeline_scheduler_contrib() is None


@pytest.mark.asyncio
async def test_timeline_schedule_registration_module_supports_manual_sync(monkeypatch, tmp_path) -> None:
    from magi.timeline.lifecycle import TimelineScheduleRegistrationModule

    context = RuntimeBootstrapContext()
    context.core.runtime_paths = RuntimePaths(tmp_path / "runtime")
    context.timeline.timeline_service = _FakeTimelineService()
    context.scheduler.scheduler_service = _FakeSchedulerService()

    monkeypatch.setattr("magi.timeline.lifecycle.get_sensor_registry", _build_sensor_registry)
    monkeypatch.setattr("magi.timeline.lifecycle.get_plugin_manager", _FakePluginManager)
    monkeypatch.setattr(
        "magi.timeline.lifecycle.get_config",
        lambda: type("Config", (), {"timeline": type("Timeline", (), {"enabled": True})()})(),
    )

    module = TimelineScheduleRegistrationModule(context)
    await module.init()

    schedule = await module.queue_manual_sync("pull_history")

    assert schedule.schedule_id.startswith("timeline-sync-manual:pull-plugin:pull_history:")
    assert context.scheduler.scheduler_service.once_calls[0]["run_at"] <= time.time() + 1.0

    await module.shutdown()
