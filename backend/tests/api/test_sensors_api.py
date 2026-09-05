import asyncio
import tempfile
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pathlib import Path

from alembic import command
from alembic.config import Config

from magi.api.routers import sensors as sensors_module
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.awareness.source_store import SourceStore
from magi_plugin_sdk.runtime import PluginConnection, SourceChange, SourceChangeBatch
from magi.api.routers.sensors import _derive_sensor_status, sensors_router
from magi.db import MIGRATION_TARGETS
from magi.i18n import language_context
from magi.plugins import ExtensionFieldSpec
from magi.scheduler import (
    ScheduleDefinition,
    ScheduledExecutionResult,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)
from magi.scheduler.repository import ScheduleRepository

CONNECTION_ID = "screen-account"

_SCHEDULER_MIGRATION = next(t for t in MIGRATION_TARGETS if t.name == "scheduler")


def _bootstrap_scheduler_schema(db_path: str) -> None:
    """Bring a fresh scheduler SQLite file up to head via its Alembic env.

    The scheduler schema is owned solely by Alembic (commit 613ef6cc removed the
    legacy ``ensure_scheduler_schema`` no-op), so ``schedules``/``target_state``
    only exist after the migration runs.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = Config()
    cfg.set_main_option("script_location", str(_SCHEDULER_MIGRATION.script_location()))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    cfg.set_main_option("version_path_separator", "os")
    command.upgrade(cfg, "head")


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


def _build_client(
    monkeypatch,
    *,
    source_settings: dict[str, object] | None = None,
    activation_flow: dict[str, object] | None = None,
):
    app = FastAPI()
    app.include_router(_build_public_router(sensors_router, _PUBLIC_ROUTE_METHODS["sensors"]), prefix="/api/sensors")
    monkeypatch.setattr(sensors_module, "get_config", lambda: type("Config", (), {})())
    runtime_base_dir = tempfile.mkdtemp(prefix="magi-runtime-")
    resolved_source_settings = {
        "enabled": True,
        "sync_mode": "interval",
        "sync_interval_minutes": 5,
        **(source_settings or {}),
    }
    connection = PluginConnection(
        connection_id=CONNECTION_ID, plugin_id="screen-time", display_name="Work Mac", enabled=True,
        settings={"sensors": {"screen_time": resolved_source_settings}},
    )
    sensor_metadata = {
        "connection_id": CONNECTION_ID,

        "default_settings": {
            "enabled": True,
            "sync_mode": "interval",
            "sync_interval_minutes": 5,
        },
        **({"activation_flow": activation_flow} if activation_flow is not None else {}),
    }
    monkeypatch.setattr(
        sensors_module,
        "get_runtime_paths",
        lambda: type(
            "Paths",
            (),
            {
                "base_dir": runtime_base_dir,
                "runtime_dir": Path(runtime_base_dir) / "runtime",
                "scheduler_db_path": f"{runtime_base_dir}/runtime/scheduler.db",
            },
        )(),
    )
    plugin_state = type(
        "PluginState",
        (),
        {
            "manifest": type("Manifest", (), {"plugin_id": "screen-time", "plugin_dir": "", "icon": "lucide:monitor"})(),
            "current_settings": {
                "sensors": {
                    "screen_time": resolved_source_settings,
                }
            },
        },
    )()
    monkeypatch.setattr(
        sensors_module,
        "resolve_plugin_manager",
        lambda: SimpleNamespace(list_packages=lambda: [plugin_state],
                                connection_store=SimpleNamespace(get=lambda connection_id: connection if connection_id == CONNECTION_ID else None)),
    )
    monkeypatch.setattr(
        sensors_module,
        "resolve_sensor_registry",
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
                            "contribution_id": "screen-account:timeline.screen_time",
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
                                **sensor_metadata,
                                "settings_actions": [
                                    {
                                        "action_id": "connect_github",
                                        "label": "Connect GitHub",
                                        "description": "Authorize GitHub locally.",
                                        "button_label": "Connect GitHub",
                                        "presentation": "inline",
                                        "surface": "timeline",
                                        "contribution_id": "timeline.screen_time",
                                        "contribution_type": "sensor",
                                        "order": 0,
                                        "destructive": False,
                                        "requires_enabled": False,
                                        "poll_interval_ms": 5000,
                                        "timeout_ms": 900000,
                                        "persist_settings_on_success": True,
                                    }
                                ],
                            },
                        },
                    )()
                ],
                "resolve_source_sensor": lambda self, source_name, *, connection_id: (
                    (
                        "screen-time",
                        "timeline.screen_time",
                        type("Sensor", (), {"supports_pull_sync": True, "supports_state_flush": True, "connection": connection})(),
                        type("Spec", (), {"metadata": sensor_metadata})(),
                    )
                    if source_name == "screen_time" and connection_id == CONNECTION_ID
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
    scheduler_db_path = f"{runtime_base_dir}/runtime/scheduler.db"
    repository = ScheduleRepository(scheduler_db_path)
    _bootstrap_scheduler_schema(scheduler_db_path)

    async def _seed_state():
        await repository.initialize()
        schedule_id = "sensor-sync:screen-account:screen_time"
        await repository.upsert_schedule(
            ScheduleDefinition(
                schedule_id=schedule_id,
                target_type=ScheduledTargetType.SENSOR_SYNC,
                target_key="screen-account:screen_time",
                trigger=TriggerDefinition(
                    trigger_type=TriggerType.INTERVAL,
                    config={"minutes": 5},
                ),
                target_payload={"source_type": "screen_time", "connection_id": CONNECTION_ID},
                metadata={},
                enabled=True,
                job_id=schedule_id,
            )
        )
        await repository.update_schedule_binding(
            schedule_id,
            job_id=schedule_id,
        )
        await repository.acquire_target_lock(
            ScheduledTargetType.SENSOR_SYNC,
            "screen-account:screen_time",
        )
        await repository.record_target_success(
            ScheduledTargetType.SENSOR_SYNC,
            "screen-account:screen_time",
            result=ScheduledExecutionResult(
                success=True,
                message="sensor_sync_completed",
                stats={"count": 4, "raw_count": 7},
            ),
            scheduler_job_id=schedule_id,
        )

    asyncio.run(_seed_state())
    asyncio.run(SourceStore(Path(runtime_base_dir) / "runtime" / "plugin_sources.db").initialize())
    return TestClient(app), queue, repository


def test_get_sensor_source_status(monkeypatch):
    client, _, _ = _build_client(monkeypatch)

    response = client.get("/api/sensors/status")

    assert response.status_code == 200
    body = response.json()
    assert body["sources"][0]["source_name"] == "screen_time"
    assert body["sources"][0]["icon"] == "lucide:monitor"
    assert body["sources"][0]["status"] == "ready"
    assert body["sources"][0]["scheduler_job_id"] == "sensor-sync:screen-account:screen_time"
    assert body["sources"][0]["supports_state_flush"] is True
    assert body["sources"][0]["settings_actions"][0]["action_id"] == "connect_github"
    assert body["sources"][0]["settings_actions"][0]["button_label"] == "Connect GitHub"


def test_get_sensor_source_status_includes_queued_backfill(monkeypatch):
    client, _, repository = _build_client(monkeypatch)

    async def _seed_backfill_job() -> str:
        schedule = ScheduleDefinition(
            schedule_id="sensor-sync-backfill:screen-account:screen_time:custom",
            target_type=ScheduledTargetType.SENSOR_SYNC,
            target_key="screen-account:screen_time",
            trigger=TriggerDefinition(
                trigger_type=TriggerType.INTERVAL,
                config={"minutes": 5},
            ),
            target_payload={
                "plugin_id": "screen-time",
                "connection_id": CONNECTION_ID,
                "source_type": "screen_time",
                "sync_request": {
                    "mode": "backfill",
                    "backfill_scope": "custom",
                    "backfill_start_date": "2026-06-01",
                    "backfill_end_date": "2026-06-30",
                },
            },
            metadata={"manual": True},
        )
        await repository.upsert_schedule(schedule)
        admitted = await repository.enqueue_sensor_sync_execution(
            schedule=schedule,
            manual=True,
            started_at=time.time(),
        )
        assert admitted is not None
        return admitted.job_id

    job_id = asyncio.run(_seed_backfill_job())
    response = client.get("/api/sensors/status")

    assert response.status_code == 200
    activity = response.json()["sources"][0]["sync_activity"]
    assert activity["created_at"] is not None
    assert {key: value for key, value in activity.items() if key != "created_at"} == {
        "job_id": job_id,
        "mode": "backfill",
        "status": "queued",
        "backfill_scope": "custom",
        "backfill_start_date": "2026-06-01",
        "backfill_end_date": "2026-06-30",
        "started_at": None,
        "finished_at": None,
        "attempt_count": 0,
        "next_attempt_at": activity["created_at"],
        "error": None,
    }


def test_derive_sensor_status_prioritizes_operator_states():
    assert _derive_sensor_status(
        enabled=True,
        activation_required=True,
        running=False,
        last_error=None,
        last_success_at=None,
        sync_mode="interval",
        sync_interval_minutes=5,
        now=100_000.0,
    ) == "setup_required"
    assert _derive_sensor_status(
        enabled=False,
        activation_required=False,
        running=False,
        last_error=None,
        last_success_at=None,
        sync_mode="interval",
        sync_interval_minutes=5,
        now=1_000.0,
    ) == "disabled"
    assert _derive_sensor_status(
        enabled=True,
        activation_required=False,
        running=True,
        last_error="boom",
        last_success_at=990.0,
        sync_mode="interval",
        sync_interval_minutes=5,
        now=1_000.0,
    ) == "running"
    assert _derive_sensor_status(
        enabled=True,
        activation_required=False,
        running=False,
        last_error="boom",
        last_success_at=990.0,
        sync_mode="interval",
        sync_interval_minutes=5,
        now=1_000.0,
    ) == "error"


def test_derive_sensor_status_keeps_retryable_failure_distinct_from_terminal_error():
    assert _derive_sensor_status(
        enabled=True,
        activation_required=False,
        running=False,
        retrying=True,
        last_error="temporary source failure",
        last_success_at=990.0,
        sync_mode="interval",
        sync_interval_minutes=5,
        now=1_000.0,
    ) == "retrying"


def test_derive_sensor_status_reports_never_synced_and_stale_interval_sources():
    assert _derive_sensor_status(
        enabled=True,
        activation_required=False,
        running=False,
        last_error=None,
        last_success_at=None,
        sync_mode="interval",
        sync_interval_minutes=5,
        now=1_000.0,
    ) == "never_synced"
    assert _derive_sensor_status(
        enabled=True,
        activation_required=False,
        running=False,
        last_error=None,
        last_success_at=100_000.0 - (7 * 60 * 60),
        sync_mode="interval",
        sync_interval_minutes=5,
        now=100_000.0,
    ) == "stale"
    assert _derive_sensor_status(
        enabled=True,
        activation_required=False,
        running=False,
        last_error=None,
        last_success_at=900.0,
        sync_mode="manual",
        sync_interval_minutes=5,
        now=1_000.0,
    ) == "ready"


def test_trigger_sensor_source_sync(monkeypatch):
    client, queue, _ = _build_client(monkeypatch)

    response = client.post("/api/sensors/screen_time/sync?connection_id=screen-account")

    assert response.status_code == 200
    assert response.json()["queued"] is True
    assert len(queue.sensor_sync_commands) == 1
    assert queue.sensor_sync_commands[0].connection_id == CONNECTION_ID
    assert queue.sensor_sync_commands[0].first_context is False


def test_trigger_sensor_source_sync_rejects_setup_required(monkeypatch):
    client, queue, _ = _build_client(
        monkeypatch,
        source_settings={
            "enabled": True,
            "initial_sync_configured": False,
        },
        activation_flow={
            "enabled_key": "sensors.screen_time.enabled",
            "configured_key": "sensors.screen_time.initial_sync_configured",
            "fields": [],
        },
    )

    with language_context("en"):
        status_response = client.get("/api/sensors/status")
        response = client.post("/api/sensors/screen_time/sync?connection_id=screen-account")

    assert status_response.status_code == 200
    assert status_response.json()["sources"][0]["activation_required"] is True
    assert status_response.json()["sources"][0]["status"] == "setup_required"
    assert response.status_code == 409
    assert response.json()["detail"] == "Configure this source before syncing: screen_time"
    assert queue.sensor_sync_commands == []


def test_trigger_sensor_source_sync_rejects_disabled_source(monkeypatch):
    client, queue, _ = _build_client(
        monkeypatch,
        source_settings={"enabled": False},
    )

    with language_context("en"):
        response = client.post("/api/sensors/screen_time/sync?connection_id=screen-account")

    assert response.status_code == 409
    assert response.json()["detail"] == "Enable this source before syncing: screen_time"
    assert queue.sensor_sync_commands == []


def test_trigger_first_context_sensor_source_sync(monkeypatch):
    client, queue, _ = _build_client(monkeypatch)

    response = client.post("/api/sensors/screen_time/sync?connection_id=screen-account", json={"first_context": True})

    assert response.status_code == 200
    assert response.json()["queued"] is True
    assert len(queue.sensor_sync_commands) == 1
    assert queue.sensor_sync_commands[0].connection_id == CONNECTION_ID
    assert queue.sensor_sync_commands[0].first_context is True


def test_trigger_sensor_source_backfill_sync(monkeypatch):
    client, queue, _ = _build_client(monkeypatch)

    response = client.post(
        "/api/sensors/screen_time/sync?connection_id=screen-account",
        json={"mode": "backfill", "backfill_scope": "last_30_days"},
    )

    assert response.status_code == 200
    assert response.json()["queued"] is True
    assert response.json()["mode"] == "backfill"
    assert response.json()["backfill_scope"] == "last_30_days"
    assert len(queue.sensor_sync_commands) == 1
    assert queue.sensor_sync_commands[0].connection_id == CONNECTION_ID
    command = queue.sensor_sync_commands[0]
    assert command.first_context is False
    assert command.sync_mode == "backfill"
    assert command.backfill_scope == "last_30_days"
    assert command.backfill_days == 30


def test_trigger_sensor_source_custom_backfill_sync(monkeypatch):
    client, queue, _ = _build_client(monkeypatch)

    response = client.post(
        "/api/sensors/screen_time/sync?connection_id=screen-account",
        json={
            "mode": "backfill",
            "backfill_scope": "custom",
            "backfill_start_date": "2026-06-01",
            "backfill_end_date": "2026-06-30",
        },
    )

    assert response.status_code == 200
    assert response.json()["queued"] is True
    assert response.json()["mode"] == "backfill"
    assert response.json()["backfill_scope"] == "custom"
    assert response.json()["backfill_start_date"] == "2026-06-01"
    assert response.json()["backfill_end_date"] == "2026-06-30"
    assert len(queue.sensor_sync_commands) == 1
    assert queue.sensor_sync_commands[0].connection_id == CONNECTION_ID
    command = queue.sensor_sync_commands[0]
    assert command.sync_mode == "backfill"
    assert command.backfill_scope == "custom"
    assert command.backfill_days is None
    assert command.backfill_start_date == "2026-06-01"
    assert command.backfill_end_date == "2026-06-30"


def test_trigger_sensor_source_custom_backfill_rejects_inverted_range(monkeypatch):
    client, _, _ = _build_client(monkeypatch)

    response = client.post(
        "/api/sensors/screen_time/sync?connection_id=screen-account",
        json={
            "mode": "backfill",
            "backfill_scope": "custom",
            "backfill_start_date": "2026-06-30",
            "backfill_end_date": "2026-06-01",
        },
    )

    assert response.status_code == 422


def test_trigger_sensor_source_state_flush(monkeypatch):
    client, queue, _ = _build_client(monkeypatch)

    response = client.post("/api/sensors/screen_time/flush-state?connection_id=screen-account")

    assert response.status_code == 200
    assert response.json()["queued"] is True
    assert len(queue.sensor_state_flush_commands) == 1
    assert queue.sensor_state_flush_commands[0].connection_id == CONNECTION_ID


def test_get_sensor_source_status_sanitizes_internal_runtime_error(monkeypatch):
    client, _, repository = _build_client(monkeypatch)

    asyncio.run(
        repository.record_target_failure(
            ScheduledTargetType.SENSOR_SYNC,
            "screen-account:screen_time",
            error=(
                "<Queue at 0x123 maxsize=2 _queue=[MemoryEvent(event_id='evt-1', "
                "content='https://auth.openai.com/oauth/authorize?...')] tasks=2> "
                "is bound to a different event loop"
            ),
            scheduler_job_id="sensor-sync:screen-account:screen_time",
        )
    )

    with language_context("en"):
        response = client.get("/api/sensors/status")

    assert response.status_code == 200
    error_text = response.json()["sources"][0]["last_error"]
    assert error_text == "Sensor sync failed due to an internal runtime loop mismatch."


def test_trigger_sensor_source_sync_returns_localized_not_found(monkeypatch):
    client, _, _ = _build_client(monkeypatch)

    with language_context("zh-CN"):
        response = client.post("/api/sensors/missing/sync?connection_id=screen-account")

    assert response.status_code == 404
    assert response.json()["detail"] == "未找到传感器来源"


def test_get_sensor_today_summary_aggregates_counts(monkeypatch):
    client, _, _ = _build_client(monkeypatch)

    summarize_calls: list[dict] = []

    class _FakeL1:
        async def summarize_event_sources(self, **kwargs):
            summarize_calls.append(kwargs)
            return [
                {
                    "source": "screen_time",
                    "event_count": 17,
                    "avg_importance": 0.5,
                    "min_timestamp": 1710000000.0,
                    "max_timestamp": 1710003600.0,
                },
                {
                    "source": "git_activity",
                    "event_count": 3,
                    "avg_importance": 0.8,
                    "min_timestamp": 1710000200.0,
                    "max_timestamp": 1710001100.0,
                },
            ]

    class _FakeUnifiedMemory:
        l1 = _FakeL1()

    monkeypatch.setattr(
        "magi.api.routers.sensors.get_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )

    response = client.get("/api/sensors/today-summary")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["date"], str)
    assert body["weekday"] in range(7)
    assert {entry["source_name"] for entry in body["sources"]} == {"screen_time", "git_activity"}
    screen_time = next(entry for entry in body["sources"] if entry["source_name"] == "screen_time")
    assert screen_time["count"] == 17
    assert screen_time["display_name"] == "App Usage"
    assert screen_time["plugin_id"] == "screen-time"
    assert screen_time["last_event_at"] == 1710003600.0
    # screen_time has the higher count, so it must come first.
    assert body["sources"][0]["source_name"] == "screen_time"
    # The endpoint should have asked the L1 layer for today's window.
    assert summarize_calls and "start_time" in summarize_calls[0] and "end_time" in summarize_calls[0]
    assert summarize_calls[0]["start_time"] < summarize_calls[0]["end_time"]


def test_get_sensor_today_summary_accepts_explicit_day(monkeypatch):
    client, _, _ = _build_client(monkeypatch)

    class _FakeL1:
        async def summarize_event_sources(self, **kwargs):
            return []

    class _FakeUnifiedMemory:
        l1 = _FakeL1()

    monkeypatch.setattr(
        "magi.api.routers.sensors.get_unified_memory",
        lambda: _FakeUnifiedMemory(),
    )

    response = client.get("/api/sensors/today-summary", params={"day": "2025-04-01"})

    assert response.status_code == 200
    body = response.json()
    assert body["date"] == "2025-04-01"
    # Empty L1 + one enabled sensor → emit a quiet zero-count placeholder.
    assert any(entry["source_name"] == "screen_time" and entry["count"] == 0 for entry in body["sources"])


def test_get_sensor_today_summary_rejects_invalid_day(monkeypatch):
    client, _, _ = _build_client(monkeypatch)

    monkeypatch.setattr(
        "magi.api.routers.sensors.get_unified_memory",
        lambda: (_ for _ in ()).throw(RuntimeError("memory unavailable")),
    )

    response = client.get("/api/sensors/today-summary", params={"day": "not-a-date"})

    assert response.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# GET /{source_name}/memory-readiness
# ──────────────────────────────────────────────────────────────────────


class _FakeReadinessL1:
    """Apply user-visible memory lookup to accepted source receipts."""

    def __init__(self, rows: list[dict]):
        self.event_ids = [f"event-{index}" for index in range(sum(row["event_count"] for row in rows))]

    async def get_user_visible_event(self, event_id):
        return {"event_id": event_id} if event_id in self.event_ids else None


class _FakeReadinessMemory:
    def __init__(self, *, rows, backlog_sequence, flush_result=1):
        self.l1 = _FakeReadinessL1(rows)
        self._backlog_seq = list(backlog_sequence)
        self.flush_calls = 0
        self._flush_result = flush_result
        self.backlog_event_ids = []

    async def flush_l2_projection_jobs(self):
        self.flush_calls += 1
        return self._flush_result

    async def projection_backlog(self, memory, event_ids):
        assert memory is self
        self.backlog_event_ids.append(event_ids)
        if len(self._backlog_seq) > 1:
            return self._backlog_seq.pop(0)
        return self._backlog_seq[0]


def _bind_readiness_memory(monkeypatch, fake):
    monkeypatch.setattr(sensors_module, "get_unified_memory", lambda: fake)
    monkeypatch.setattr(sensors_module, "source_projection_backlog", fake.projection_backlog)
    store = SourceStore(sensors_module.get_runtime_paths().runtime_dir / "plugin_sources.db")
    sensor = sensors_module.resolve_sensor_registry().resolve_source_sensor(
        "screen_time", connection_id=CONNECTION_ID,
    )[2]

    async def seed_accepted_source_receipts():
        checkpoint = await store.checkpoint(sensor.connection, "timeline.screen_time", "screen_time")
        changes = [SourceChange(object_id=event_id, version="v1", payload={"text": event_id})
                   for event_id in fake.l1.event_ids]
        pending = await store.stage_batch(sensor.connection, checkpoint, SourceChangeBatch(changes=changes))
        for change in changes:
            await store.record_receipt(pending, change, event_id=change.object_id, outcome="persisted")
        await store.accept_batch(sensor.connection, pending)

    asyncio.run(seed_accepted_source_receipts())


def test_memory_readiness_ready_when_backlog_drained(monkeypatch):
    client, _, _ = _build_client(monkeypatch)
    fake = _FakeReadinessMemory(
        rows=[{"source": "screen_time", "event_count": 7}],
        backlog_sequence=[{"pending": 0, "claimed": 0}],
    )
    _bind_readiness_memory(monkeypatch, fake)

    response = client.get(
        "/api/sensors/screen_time/memory-readiness", params={"connection_id": CONNECTION_ID, "max_wait_ms": 2000}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_name"] == "screen_time"
    assert body["l1_event_count"] == 7
    assert body["l2_ready"] is True
    assert body["l2_total_count"] == 7
    assert body["l2_processed_count"] == 7
    assert body["l2_remaining_count"] == 0
    # flush is forced before polling the backlog.
    assert fake.flush_calls == 1
    assert fake.backlog_event_ids == [fake.l1.event_ids]


def test_memory_readiness_not_ready_on_timeout(monkeypatch):
    client, _, _ = _build_client(monkeypatch)
    fake = _FakeReadinessMemory(
        rows=[{"source": "screen_time", "event_count": 3}],
        backlog_sequence=[{"pending": 2, "claimed": 0, "completed": 1, "failed": 0}],
    )
    _bind_readiness_memory(monkeypatch, fake)

    response = client.get(
        "/api/sensors/screen_time/memory-readiness", params={"connection_id": CONNECTION_ID, "max_wait_ms": 10}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["l1_event_count"] == 3
    assert body["l2_ready"] is False
    assert body["l2_total_count"] == 3
    assert body["l2_processed_count"] == 1
    assert body["l2_remaining_count"] == 2


def test_memory_readiness_no_events_skips_flush(monkeypatch):
    client, _, _ = _build_client(monkeypatch)
    fake = _FakeReadinessMemory(
        rows=[],
        backlog_sequence=[{"pending": 0, "claimed": 0}],
    )
    _bind_readiness_memory(monkeypatch, fake)

    response = client.get("/api/sensors/screen_time/memory-readiness", params={"connection_id": CONNECTION_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["l1_event_count"] == 0
    assert body["l2_ready"] is False
    # Nothing to flush when there are no L1 events for this source.
    assert fake.flush_calls == 0


def test_memory_readiness_no_memory_binding(monkeypatch):
    client, _, _ = _build_client(monkeypatch)

    monkeypatch.setattr(
        "magi.api.routers.sensors.get_unified_memory",
        lambda: (_ for _ in ()).throw(RuntimeError("no binding")),
    )

    response = client.get("/api/sensors/screen_time/memory-readiness", params={"connection_id": CONNECTION_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["l1_event_count"] == 0
    assert body["l2_ready"] is False
