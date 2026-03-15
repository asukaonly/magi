from __future__ import annotations

import asyncio
import time

import pytest

from magi.plugins.actions import ActionRegistry, ActionSpec, BaseAction
from magi.plugins.sensors import SensorRegistry, SensorSpec
from magi.scheduler import (
    SchedulerBootstrap,
    SchedulerService,
    ScheduledTargetType,
    build_timeline_schedule_id,
    build_timeline_target_key,
)
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


class _FakeTaskAgentManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    async def add_fact_to_agent(self, agent_type, agent_id, fact) -> bool:
        self.calls.append((str(agent_type), agent_id, fact))
        return True


class _FakeActionExecutor:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def emit_action_event(self, fact, success: bool, error: str | None = None) -> None:
        self.events.append((fact, success, error))


class _StaleChatPluginManager:
    def __init__(self) -> None:
        self.package = type(
            "Package",
            (),
            {
                "current_settings": {
                    "sensors": {
                        "chat": {
                            "enabled": True,
                            "sync_mode": "watch",
                            "sync_interval_minutes": 1,
                        }
                    }
                }
            },
        )()

    def get_package(self, plugin_id: str):
        return self.package if plugin_id == "core-timeline" else None


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
                    "relation_candidates": [
                        {
                            "subject_id": "user:self",
                            "subject_type": "user",
                            "predicate": "LIKES",
                            "object_id": "topic:scheduler",
                            "object_type": "topic",
                            "confidence": 0.9,
                        }
                    ],
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


class _NotifyAction(BaseAction):
    def __init__(self) -> None:
        self.calls: list[dict] = []
        super().__init__()

    def build_spec(self) -> ActionSpec:
        return ActionSpec(
            action_id="notify-user",
            display_name="Notify User",
            description="Notify the user",
            input_schema={"type": "object", "properties": {"message": {"type": "string"}}},
        )

    async def execute(self, parameters, context):
        self.calls.append({"parameters": parameters, "context": context})
        return {"status": "sent"}


class _ChatSensor(TimelineSensorBase):
    sensor_id = "timeline.chat"
    display_name = "Chat"
    source_type = "chat"
    polling_mode = "watch"

    async def build_timeline_event(self, item):
        return self._build_event(
            source_item_id="chat",
            title="Chat",
            summary="Chat",
            occurred_at=1710000000.0,
            content_blocks=[TimelineContentBlock(kind="text", value="Chat")],
        )


@pytest.mark.asyncio
async def test_scheduler_bootstrap_syncs_timeline_sources_and_updates_target_state(tmp_path):
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = SchedulerService(db_path=runtime_paths.scheduler_db_path, runtime_dir=runtime_paths.base_dir)
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
    action_registry = ActionRegistry()
    task_agent_manager = _FakeTaskAgentManager()
    action_executor = _FakeActionExecutor()
    timeline_service = _FakeTimelineService()
    bootstrap = SchedulerBootstrap(
        scheduler_service=service,
        sensor_registry=sensor_registry,
        action_registry=action_registry,
        plugin_manager=_FakePluginManager(),
        timeline_service=timeline_service,
        runtime_paths=runtime_paths,
        task_agent_manager=task_agent_manager,
        action_executor=action_executor,
        get_config=lambda: type("Config", (), {"timeline": type("Timeline", (), {"enabled": True})()})(),
    )
    bootstrap.register_handlers()
    await service.start()
    await bootstrap.sync_timeline_sensor_schedules()

    schedule_id = build_timeline_schedule_id("pull-plugin", "pull_history")
    schedule = await service.repository.get_schedule(schedule_id)
    assert schedule is not None

    manual = await bootstrap.queue_manual_timeline_sync("pull_history")
    assert manual.trigger.trigger_type.value == "once"

    deadline = time.monotonic() + 1.0
    while len(timeline_service.events) < 1 and time.monotonic() < deadline:
        await asyncio.sleep(0.05)

    state = await service.get_target_state(
        ScheduledTargetType.TIMELINE_SENSOR_SYNC,
        build_timeline_target_key("pull-plugin", "pull_history"),
    )

    assert len(timeline_service.events) == 1
    assert timeline_service.events[0].event_id == "pull_history:item-1"
    assert state.last_cursor == "cursor-2"
    assert state.watermark_ts == 1710000000.0
    assert state.last_success_at is not None

    await service.stop()


@pytest.mark.asyncio
async def test_scheduler_bootstrap_dispatches_action_and_agent_targets(tmp_path):
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = SchedulerService(db_path=runtime_paths.scheduler_db_path, runtime_dir=runtime_paths.base_dir)
    sensor_registry = SensorRegistry()
    action_registry = ActionRegistry()
    action = _NotifyAction()
    action_registry.register("core-actions", action)
    task_agent_manager = _FakeTaskAgentManager()
    action_executor = _FakeActionExecutor()
    bootstrap = SchedulerBootstrap(
        scheduler_service=service,
        sensor_registry=sensor_registry,
        action_registry=action_registry,
        plugin_manager=_FakePluginManager(),
        timeline_service=_FakeTimelineService(),
        runtime_paths=runtime_paths,
        task_agent_manager=task_agent_manager,
        action_executor=action_executor,
        get_config=lambda: type("Config", (), {"timeline": type("Timeline", (), {"enabled": True})()})(),
    )
    bootstrap.register_handlers()
    await service.start()

    await service.schedule_once(
        schedule_id="scheduled-action",
        target_type=ScheduledTargetType.ACTION_DISPATCH,
        target_key="notify-user",
        run_at=time.time() + 60.0,
        target_payload={"action_id": "notify-user", "parameters": {"message": "hi"}, "user_id": "u1"},
    )
    await service.trigger_now("scheduled-action")

    await service.schedule_once(
        schedule_id="scheduled-agent",
        target_type=ScheduledTargetType.AGENT_TASK,
        target_key="chat:u1",
        run_at=time.time() + 60.0,
        target_payload={"agent_type": "chat", "agent_id": "u1", "event_type": "ScheduledAgentTask", "payload": "ok"},
    )
    await service.trigger_now("scheduled-agent")

    assert len(action.calls) == 1
    assert action.calls[0]["parameters"]["message"] == "hi"
    assert len(action_executor.events) == 1
    assert len(task_agent_manager.calls) == 1
    assert task_agent_manager.calls[0][0] == "chat"
    assert task_agent_manager.calls[0][1] == "u1"

    await service.stop()


@pytest.mark.asyncio
async def test_scheduler_bootstrap_clears_stale_state_for_non_pull_timeline_sources(tmp_path):
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    service = SchedulerService(db_path=runtime_paths.scheduler_db_path, runtime_dir=runtime_paths.base_dir)
    sensor_registry = SensorRegistry()
    sensor_registry.register(
        "core-timeline",
        "timeline.chat",
        _ChatSensor(),
        SensorSpec(
            sensor_id="timeline.chat",
            display_name="Chat",
            description="Chat source",
            domain="timeline",
            surface="timeline",
            sync_mode="watch",
            metadata={
                "source_type": "chat",
                "default_settings": {
                    "enabled": True,
                    "sync_mode": "watch",
                    "sync_interval_minutes": 1,
                },
            },
        ),
    )
    bootstrap = SchedulerBootstrap(
        scheduler_service=service,
        sensor_registry=sensor_registry,
        action_registry=ActionRegistry(),
        plugin_manager=_StaleChatPluginManager(),
        timeline_service=_FakeTimelineService(),
        runtime_paths=runtime_paths,
        task_agent_manager=_FakeTaskAgentManager(),
        action_executor=_FakeActionExecutor(),
        get_config=lambda: type("Config", (), {"timeline": type("Timeline", (), {"enabled": True})()})(),
    )
    await service.start()
    await service.repository.record_target_failure(
        ScheduledTargetType.TIMELINE_SENSOR_SYNC,
        build_timeline_target_key("core-timeline", "chat"),
        error="timeline.chat does not implement pull sync",
        next_run_at=time.time() + 60.0,
        scheduler_job_id="timeline-sync:core-timeline:chat",
    )

    await bootstrap.sync_timeline_sensor_schedules()

    state = await service.get_target_state(
        ScheduledTargetType.TIMELINE_SENSOR_SYNC,
        build_timeline_target_key("core-timeline", "chat"),
    )
    assert state.last_error is None
    assert state.scheduler_job_id is None
    assert state.next_run_at is None

    await service.stop()
