"""Connection identity is mandatory through the product's public sensor router."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from magi_plugin_sdk.runtime import PluginConnection
from magi_plugin_sdk.sensors import SensorSpec

from magi.api.routers import sensors
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.events.contracts import SensorStateFlushCommand, SensorSyncCommand


def setup_api(monkeypatch):
    connection = PluginConnection(connection_id="account-b", plugin_id="notes", display_name="Work", enabled=True)
    sensor = SimpleNamespace(connection=connection, supports_pull_sync=True, supports_state_flush=True, request_activation_authorization=AsyncMock(return_value={"authorized": True}))
    registry = Mock()
    registry.resolve_source_sensor.side_effect = lambda source_name, connection_id: (
        ("notes", "notes.sensor", sensor, SensorSpec(sensor_id="notes.sensor", display_name="Notes"))
        if source_name == "notes" and connection_id == "account-b" else None
    )
    queue = SimpleNamespace(enqueue_sensor_sync=AsyncMock(return_value=7), enqueue_sensor_state_flush=AsyncMock(return_value=8))
    monkeypatch.setattr(sensors, "get_config", lambda: None)
    monkeypatch.setattr(sensors, "resolve_sensor_registry", lambda: registry)
    monkeypatch.setattr(sensors, "require_runtime_command_queue", lambda: queue)
    app = FastAPI()
    app.include_router(_build_public_router(sensors.sensors_router, _PUBLIC_ROUTE_METHODS["sensors"]), prefix="/api/sensors")
    return TestClient(app), queue, sensor


@pytest.mark.parametrize("action", ["sync", "flush-state", "authorize"])
def test_public_source_action_requires_connection_query(monkeypatch, action):
    client, queue, _ = setup_api(monkeypatch)
    assert client.post(f"/api/sensors/notes/{action}", json={}).status_code == 422
    queue.enqueue_sensor_sync.assert_not_called()
    queue.enqueue_sensor_state_flush.assert_not_called()


@pytest.mark.parametrize("action", ["sync", "flush-state", "authorize"])
def test_public_source_action_does_not_choose_another_connection(monkeypatch, action):
    client, _, _ = setup_api(monkeypatch)
    assert client.post(f"/api/sensors/notes/{action}?connection_id=unknown", json={}).status_code == 404


def test_source_commands_preserve_explicit_identity_and_authorization(monkeypatch):
    client, queue, sensor = setup_api(monkeypatch)
    result = client.post("/api/sensors/notes/sync?connection_id=account-b", json={})
    assert result.status_code == 200
    assert result.json()["connection_id"] == "account-b"
    command = queue.enqueue_sensor_sync.await_args.args[0]
    assert command.connection_id == "account-b"
    assert command.source_name == "notes"
    result = client.post("/api/sensors/notes/flush-state?connection_id=account-b", json={})
    assert result.status_code == 200
    assert queue.enqueue_sensor_state_flush.await_args.args[0].connection_id == "account-b"
    assert client.post("/api/sensors/notes/authorize?connection_id=account-b", json={"field_values": {"scope": "notes"}}).status_code == 200
    sensor.request_activation_authorization.assert_awaited_once_with({"scope": "notes"})


@pytest.mark.parametrize("command_type", [SensorSyncCommand, SensorStateFlushCommand])
def test_runtime_source_command_cannot_omit_or_blank_identity(command_type):
    with pytest.raises(TypeError):
        command_type(source="test", source_name="notes")
    with pytest.raises(ValueError):
        command_type(source="test", source_name="notes", connection_id="")
    assert command_type(source="test", source_name="notes", connection_id="account-b").to_payload()["connection_id"] == "account-b"


def test_memory_readiness_requires_a_connection(monkeypatch):
    client, _, _ = setup_api(monkeypatch)
    assert client.get("/api/sensors/notes/memory-readiness?max_wait_ms=0").status_code == 422
    assert client.get("/api/sensors/notes/memory-readiness?connection_id=unknown&max_wait_ms=0").status_code == 404


@pytest.mark.asyncio
async def test_status_reads_connection_settings_and_scheduler_identity(monkeypatch):
    from magi.api.routers import sensor_status_projection as projection
    from magi_plugin_sdk.contracts import PluginContribution
    from magi.scheduler.contracts import ScheduledTargetState, ScheduledTargetType

    item = PluginContribution(plugin_id="notes", contribution_id="account-b:notes.sensor", contribution_type="sensor", display_name="Notes", metadata={"source_type": "notes", "connection_id": "account-b"})
    connection = PluginConnection(connection_id="account-b", plugin_id="notes", display_name="Work", enabled=True, revision=4, settings={"sensors": {"notes": {"enabled": True, "sync_interval_minutes": 7}}})
    sensor = SimpleNamespace(connection=connection, supports_pull_sync=True, supports_state_flush=False)
    registry = Mock()
    registry.resolve_source_sensor.return_value = ("notes", item.contribution_id, sensor, None)
    repository = SimpleNamespace(
        get_target_state=AsyncMock(return_value=ScheduledTargetState(ScheduledTargetType.SENSOR_SYNC, "unused")),
        get_schedule=AsyncMock(return_value=None), get_recurring_target_binding=AsyncMock(return_value=None),
        get_latest_sensor_sync_job=AsyncMock(return_value=None),
    )
    package = SimpleNamespace(manifest=SimpleNamespace(icon="", plugin_dir=""), current_settings={"sensors": {"notes": {"enabled": False}}})
    monkeypatch.setattr(projection, "_load_plugin_i18n", lambda *_: None)
    result = await projection._build_source_status(item, packages={"notes": package}, sensor_registry=registry, repository=repository, runtime_base_dir="/test")
    assert result["connection_id"] == "account-b"
    assert result["connection_display_name"] == "Work"
    assert result["connection_revision"] == 4
    assert result["enabled"] is True
    assert result["sync_interval_minutes"] == 7
    assert repository.get_target_state.await_args.args[1] == "account-b:notes"
    registry.resolve_source_sensor.assert_called_once_with("notes", connection_id="account-b")
