import asyncio
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import sensors as sensors_module
from magi.api.routers.sensors import sensors_router
from magi.plugins import ExtensionFieldSpec
from magi.scheduler import (
    ScheduleDefinition,
    ScheduledExecutionResult,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)
from magi.scheduler.repository import ScheduleRepository


class _FakeRuntimeCommandQueue:
    def __init__(self) -> None:
        self.sensor_sync_commands: list[object] = []
        self.sensor_state_flush_commands: list[object] = []

    async def enqueue_sensor_sync(self, command):
        self.sensor_sync_commands.append(command)
        return len(self.sensor_sync_commands)

    async def enqueue_sensor_state_flush(self, command):
        self.sensor_state_flush_commands.append(command)
        return len(self.sensor_state_flush_commands)


def _build_client(monkeypatch):
    app = FastAPI()
    app.include_router(sensors_router, prefix="/api/sensors")
    monkeypatch.setattr(sensors_module, "get_config", lambda: type("Config", (), {})())
    runtime_base_dir = tempfile.mkdtemp(prefix="magi-runtime-")
    monkeypatch.setattr(
        sensors_module,
        "get_runtime_paths",
        lambda: type(
            "Paths",
            (),
            {
                "base_dir": runtime_base_dir,
                "scheduler_db_path": f"{runtime_base_dir}/data/scheduler.db",
            },
        )(),
    )
    plugin_state = type(
        "PluginState",
        (),
        {
            "manifest": type("Manifest", (), {"plugin_id": "screen-time"})(),
            "current_settings": {
                "sensors": {
                    "screen_time": {
                        "enabled": True,
                        "sync_mode": "interval",
                        "sync_interval_minutes": 5,
                    }
                }
            },
        },
    )()
    monkeypatch.setattr(
        sensors_module,
        "require_plugin_manager",
        lambda: type("Manager", (), {"list_packages": lambda self: [plugin_state]})(),
    )
    monkeypatch.setattr(
        sensors_module,
        "require_sensor_registry",
        lambda: type(
            "Registry",
            (),
            {
                "list_contributions": lambda self: [
                    type(
                        "Contribution",
                        (),
                        {
                            "plugin_id": "screen-time",
                            "contribution_id": "timeline.screen_time",
                            "display_name": "App Usage",
                            "description": "Event-driven frontmost app usage aggregated into hourly summaries.",
                            "fields": [
                                ExtensionFieldSpec(
                                    key="sensors.screen_time.enabled",
                                    type="switch",
                                    label="Enabled",
                                    default=True,
                                    surface="timeline",
                                ),
                            ],
                            "metadata": {
                                "domain": "timeline",
                                "source_type": "screen_time",
                                "default_settings": {
                                    "enabled": True,
                                    "sync_mode": "interval",
                                    "sync_interval_minutes": 5,
                                },
                            },
                        },
                    )()
                ],
                "resolve_source_sensor": lambda self, source_name: (
                    (
                        "screen-time",
                        "timeline.screen_time",
                        type("Sensor", (), {"supports_pull_sync": True, "supports_state_flush": True})(),
                        type("Spec", (), {"metadata": {"default_settings": {"enabled": True, "sync_interval_minutes": 5}}})(),
                    )
                    if source_name == "screen_time"
                    else None
                ),
            },
        )(),
    )
    queue = _FakeRuntimeCommandQueue()
    monkeypatch.setattr(
        sensors_module,
        "require_runtime_command_queue",
        lambda: queue,
    )
    repository = ScheduleRepository(f"{runtime_base_dir}/data/scheduler.db")

    async def _seed_state():
        await repository.initialize()
        schedule_id = "sensor-sync:screen-time:screen_time"
        await repository.upsert_schedule(
            ScheduleDefinition(
                schedule_id=schedule_id,
                target_type=ScheduledTargetType.SENSOR_SYNC,
                target_key="screen-time:screen_time",
                trigger=TriggerDefinition(
                    trigger_type=TriggerType.INTERVAL,
                    config={"minutes": 5},
                ),
                target_payload={"source_name": "screen_time"},
                metadata={},
                enabled=True,
                job_id=schedule_id,
            )
        )
        await repository.update_schedule_binding(
            schedule_id,
            job_id=schedule_id,
            next_run_at=1710000500.0,
        )
        await repository.acquire_target_lock(
            ScheduledTargetType.SENSOR_SYNC,
            "screen-time:screen_time",
        )
        await repository.record_target_success(
            ScheduledTargetType.SENSOR_SYNC,
            "screen-time:screen_time",
            result=ScheduledExecutionResult(
                success=True,
                message="sensor_sync_completed",
                stats={"count": 4, "raw_count": 7},
            ),
            next_run_at=1710000500.0,
            scheduler_job_id=schedule_id,
        )

    asyncio.run(_seed_state())
    return TestClient(app), queue


def test_get_sensor_source_status(monkeypatch):
    client, _ = _build_client(monkeypatch)

    response = client.get("/api/sensors/status")

    assert response.status_code == 200
    body = response.json()
    assert body["sources"][0]["source_name"] == "screen_time"
    assert body["sources"][0]["scheduler_job_id"] == "sensor-sync:screen-time:screen_time"
    assert body["sources"][0]["supports_state_flush"] is True


def test_trigger_sensor_source_sync(monkeypatch):
    client, queue = _build_client(monkeypatch)

    response = client.post("/api/sensors/screen_time/sync")

    assert response.status_code == 200
    assert response.json()["queued"] is True
    assert len(queue.sensor_sync_commands) == 1


def test_trigger_sensor_source_state_flush(monkeypatch):
    client, queue = _build_client(monkeypatch)

    response = client.post("/api/sensors/screen_time/flush-state")

    assert response.status_code == 200
    assert response.json()["queued"] is True
    assert len(queue.sensor_state_flush_commands) == 1
