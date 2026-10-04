import asyncio
import tempfile
import time

import pytest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pathlib import Path

from alembic import command
from alembic.config import Config

from magi.api.routers import sources as sources_module
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.awareness.source_store import SourceStore
from magi_plugin_sdk.runtime import PluginConnection, SourceChange, SourceChangeBatch
from magi.api.routers.sources import _derive_source_status, sources_router
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
        self.source_sync_commands: list[object] = []
        self.source_state_flush_commands: list[object] = []

    async def enqueue_source_sync(self, command):
        self.source_sync_commands.append(command)
        return len(self.source_sync_commands)

    async def enqueue_source_state_flush(self, command):
        self.source_state_flush_commands.append(command)
        return len(self.source_state_flush_commands)


def _build_client(
    monkeypatch,
    *,
    source_settings: dict[str, object] | None = None,
    activation_flow: dict[str, object] | None = None,
):
    app = FastAPI()
    app.include_router(_build_public_router(sources_router, _PUBLIC_ROUTE_METHODS["sources"]), prefix="/api/sources")
    monkeypatch.setattr(sources_module, "get_config", lambda: type("Config", (), {})())
    runtime_base_dir = tempfile.mkdtemp(prefix="magi-runtime-")
    resolved_source_settings = {
        "enabled": True,
        "sync_mode": "interval",
        "sync_interval_minutes": 5,
        **(source_settings or {}),
    }
    connection = PluginConnection(
        connection_id=CONNECTION_ID, plugin_id="screen-time", display_name="Work Mac", enabled=True,
        settings={"sources": {"screen_time": resolved_source_settings}},
    )
    source_metadata = {
        "connection_id": CONNECTION_ID,

        "default_settings": {
            "enabled": True,
            "sync_mode": "interval",
            "sync_interval_minutes": 5,
        },
        **({"activation_flow": activation_flow} if activation_flow is not None else {}),
    }
    monkeypatch.setattr(
        sources_module,
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
                "sources": {
                    "screen_time": resolved_source_settings,
                }
            },
        },
    )()
    monkeypatch.setattr(
        sources_module,
        "resolve_plugin_manager",
        lambda: SimpleNamespace(list_packages=lambda: [plugin_state],
                                connection_store=SimpleNamespace(get=lambda connection_id: connection if connection_id == CONNECTION_ID else None)),
    )
    monkeypatch.setattr(
        sources_module,
        "resolve_source_registry",
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
                                    key="sources.screen_time.enabled",
                                    type="switch",
                                    label="Enabled",
                                    default=True,
                                    surface="timeline",
                                ),
                            ],
                            "metadata": {
                                "domain": "timeline",
                                "source_type": "screen_time",
                                **source_metadata,
                                "settings_actions": [
                                    {
                                        "action_id": "connect_github",
                                        "label": "Connect GitHub",
                                        "description": "Authorize GitHub locally.",
                                        "button_label": "Connect GitHub",
                                        "presentation": "inline",
                                        "surface": "timeline",
                                        "contribution_id": "timeline.screen_time",
                                        "contribution_type": "source",
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
                "resolve_source": lambda self, source_name, *, connection_id: (
                    (
                        "screen-time",
                        "timeline.screen_time",
                        type("Source", (), {"supports_pull_sync": True, "supports_state_flush": True, "connection": connection})(),
                        type("Spec", (), {"metadata": source_metadata})(),
                    )
                    if source_name == "screen_time" and connection_id == CONNECTION_ID
                    else None
                ),
            },
        )(),
    )
    queue = _FakeRuntimeCommandQueue()
    monkeypatch.setattr(
        sources_module,
        "require_runtime_command_queue",
        lambda: queue,
    )
    scheduler_db_path = f"{runtime_base_dir}/runtime/scheduler.db"
    repository = ScheduleRepository(scheduler_db_path)
    _bootstrap_scheduler_schema(scheduler_db_path)

    async def _seed_state():
        await repository.initialize()
        schedule_id = "source-sync:screen-account:screen_time"
        await repository.upsert_schedule(
            ScheduleDefinition(
                schedule_id=schedule_id,
                target_type=ScheduledTargetType.SOURCE_SYNC,
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
            ScheduledTargetType.SOURCE_SYNC,
            "screen-account:screen_time",
        )
        await repository.record_target_result(
            ScheduledTargetType.SOURCE_SYNC,
            "screen-account:screen_time",
            result=ScheduledExecutionResult(
                success=True,
                message="source_sync_completed",
                stats={"count": 4, "raw_count": 7},
            ),
            scheduler_job_id=schedule_id,
        )

    asyncio.run(_seed_state())
    asyncio.run(SourceStore(Path(runtime_base_dir) / "runtime" / "plugin_sources.db").initialize())
    return TestClient(app), queue, repository


def test_get_source_status(monkeypatch):
    client, _, _ = _build_client(monkeypatch)

    response = client.get("/api/sources/status")

    assert response.status_code == 200
    body = response.json()
    assert body["sources"][0]["source_name"] == "screen_time"
    assert body["sources"][0]["icon"] == "lucide:monitor"
    assert body["sources"][0]["status"] == "ready"
    assert body["sources"][0]["scheduler_job_id"] == "source-sync:screen-account:screen_time"
    assert body["sources"][0]["supports_state_flush"] is True
    assert body["sources"][0]["settings_actions"][0]["action_id"] == "connect_github"
    assert body["sources"][0]["settings_actions"][0]["button_label"] == "Connect GitHub"


def test_get_source_status_includes_queued_backfill(monkeypatch):
    client, _, repository = _build_client(monkeypatch)

    async def _seed_backfill_job() -> str:
        schedule = ScheduleDefinition(
            schedule_id="source-sync-backfill:screen-account:screen_time:custom",
            target_type=ScheduledTargetType.SOURCE_SYNC,
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
        admitted = await repository.enqueue_source_sync_execution(
            schedule=schedule,
            manual=True,
            started_at=time.time(),
        )
        assert admitted is not None
        return admitted.job_id

    job_id = asyncio.run(_seed_backfill_job())
    response = client.get("/api/sources/status")

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
        "failure": None,
    }


@pytest.mark.parametrize(
    "overrides,expected",
    [
        (
            {"activation_required": True, "enabled": False, "running": True, "last_error": "error"},
            "setup_required",
        ),
        ({"enabled": False, "retrying": True, "running": True}, "disabled"),
        ({"retrying": True, "running": True, "last_error": "temporary"}, "retrying"),
        ({"running": True, "last_error": "error"}, "running"),
        ({"last_error": "error"}, "error"),
        ({"last_success_at": None}, "never_synced"),
        ({"last_success_at": 100000 - 21600}, "ready"),
        ({"last_success_at": 100000 - 21601}, "stale"),
        ({"last_success_at": 100000 - 25200}, "stale"),
        ({"sync_mode": "manual", "last_success_at": 100000 - 25200}, "ready"),
    ],
)
def test_source_status_decision_and_operator_precedence(overrides, expected):
    inputs = {
        "enabled": True,
        "activation_required": False,
        "running": False,
        "retrying": False,
        "last_error": None,
        "last_success_at": 99900,
        "sync_mode": "interval",
        "sync_interval_minutes": 5,
        "now": 100000.0,
    }
    assert _derive_source_status(**(inputs | overrides)) == expected


def test_trigger_source_sync_rejects_setup_required(monkeypatch):
    client, queue, _ = _build_client(
        monkeypatch,
        source_settings={
            "enabled": True,
            "initial_sync_configured": False,
        },
        activation_flow={
            "enabled_key": "sources.screen_time.enabled",
            "configured_key": "sources.screen_time.initial_sync_configured",
            "fields": [],
        },
    )

    with language_context("en"):
        status_response = client.get("/api/sources/status")
        response = client.post("/api/sources/screen_time/sync?connection_id=screen-account")

    assert status_response.status_code == 200
    assert status_response.json()["sources"][0]["activation_required"] is True
    assert status_response.json()["sources"][0]["status"] == "setup_required"
    assert response.status_code == 409
    assert response.json()["detail"] == "Configure this source before syncing: screen_time"
    assert queue.source_sync_commands == []


def test_trigger_source_sync_rejects_disabled_source(monkeypatch):
    client, queue, _ = _build_client(
        monkeypatch,
        source_settings={"enabled": False},
    )

    with language_context("en"):
        response = client.post("/api/sources/screen_time/sync?connection_id=screen-account")

    assert response.status_code == 409
    assert response.json()["detail"] == "Enable this source before syncing: screen_time"
    assert queue.source_sync_commands == []


def test_trigger_source_custom_backfill_rejects_inverted_range(monkeypatch):
    client, _, _ = _build_client(monkeypatch)

    response = client.post(
        "/api/sources/screen_time/sync?connection_id=screen-account",
        json={
            "mode": "backfill",
            "backfill_scope": "custom",
            "backfill_start_date": "2026-06-30",
            "backfill_end_date": "2026-06-01",
        },
    )

    assert response.status_code == 422


def test_get_source_status_sanitizes_internal_runtime_error(monkeypatch):
    client, _, repository = _build_client(monkeypatch)

    asyncio.run(
        repository.record_target_failure(
            ScheduledTargetType.SOURCE_SYNC,
            "screen-account:screen_time",
            error=(
                "<Queue at 0x123 maxsize=2 _queue=[MemoryEvent(event_id='evt-1', "
                "content='https://auth.openai.com/oauth/authorize?...')] tasks=2> "
                "is bound to a different event loop"
            ),
            scheduler_job_id="source-sync:screen-account:screen_time",
        )
    )

    with language_context("en"):
        response = client.get("/api/sources/status")

    assert response.status_code == 200
    error_text = response.json()["sources"][0]["last_error"]
    assert error_text == "Source sync failed due to an internal runtime loop mismatch."


@pytest.mark.parametrize(
    "requested_day,expected_day",
    [(None, "2025-04-01"), ("2025-04-01", "2025-04-01"), ("2025-04-02", "2025-04-02")],
)
def test_source_day_summary_aggregates_real_events_inside_exact_day(
    monkeypatch, tmp_path, requested_day, expected_day
):
    from datetime import date, datetime, time as daytime
    from magi.memory.l1.event_store import L1EventStore
    from magi.events.events import Event, EventTypes
    from magi.memory.event_contracts import normalize_runtime_event

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2025, 4, 1)

    monkeypatch.setattr(sources_module, "date", FixedDate)
    client, _, _ = _build_client(monkeypatch)
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    start = datetime(2025, 4, 1).timestamp()
    end = datetime.combine(date(2025, 4, 1), daytime.max).timestamp()
    calls = []

    async def seed():
        for i, (source, stamp) in enumerate(
            [
                ("screen_time", start),
                ("screen_time", start + 3600),
                ("screen_time", end),
                ("git_activity", start + 1800),
                ("screen_time", start - 1),
                ("screen_time", end + 86401),
            ]
        ):
            await l1.store(
                normalize_runtime_event(
                    Event(
                        type=EventTypes.USER_MESSAGE,
                        source=source,
                        timestamp=stamp,
                        event_id=f"daily-{i}",
                        data={
                            "user_id": "user-1",
                            "content": f"Event {i}",
                            "author_type": "user",
                            "content_type": "text",
                        },
                    )
                )
            )

    asyncio.run(seed())
    summarize = l1.summarize_event_sources

    async def reverse_summary(**kwargs):
        calls.append(kwargs)
        return list(reversed(await summarize(**kwargs)))

    monkeypatch.setattr(l1, "summarize_event_sources", reverse_summary)
    monkeypatch.setattr(sources_module, "get_unified_memory", lambda: SimpleNamespace(l1=l1))
    try:
        response = client.get(
            "/api/sources/today-summary",
            params={} if requested_day is None else {"day": requested_day},
        )
        assert response.status_code == 200
        day = date.fromisoformat(expected_day)
        assert calls == [
            {
                "start_time": datetime.combine(day, daytime.min).timestamp(),
                "end_time": datetime.combine(day, daytime.max).timestamp(),
            }
        ]
        sources = [
            {
                "source_name": "screen_time",
                "plugin_id": "screen-time",
                "display_name": "App Usage",
                "enabled": True,
                "count": 3,
                "last_event_at": end,
            },
            {
                "source_name": "git_activity",
                "plugin_id": None,
                "display_name": "git_activity",
                "enabled": True,
                "count": 1,
                "last_event_at": start + 1800,
            },
        ]
        if expected_day == "2025-04-02":
            sources = [{**sources[0], "count": 0, "last_event_at": None}]
        assert response.json() == {
            "date": expected_day,
            "weekday": day.weekday(),
            "sources": sources,
        }
    finally:
        client.close()
        asyncio.run(l1.shutdown())


def test_get_source_today_summary_rejects_invalid_day(monkeypatch):
    client, _, _ = _build_client(monkeypatch)

    monkeypatch.setattr(
        "magi.api.routers.sources.get_unified_memory",
        lambda: (_ for _ in ()).throw(RuntimeError("memory unavailable")),
    )

    response = client.get("/api/sources/today-summary", params={"day": "not-a-date"})

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
    monkeypatch.setattr(sources_module, "get_unified_memory", lambda: fake)
    monkeypatch.setattr(sources_module, "source_projection_backlog", fake.projection_backlog)
    store = SourceStore(sources_module.get_runtime_paths().runtime_dir / "plugin_sources.db")
    source = sources_module.resolve_source_registry().resolve_source(
        "screen_time", connection_id=CONNECTION_ID,
    )[2]

    async def seed_accepted_source_receipts():
        checkpoint = await store.checkpoint(source.connection, "timeline.screen_time", "screen_time")
        changes = [SourceChange(object_id=event_id, version="v1", payload={"text": event_id})
                   for event_id in fake.l1.event_ids]
        pending = await store.stage_batch(source.connection, checkpoint, SourceChangeBatch(changes=changes))
        for change in changes:
            await store.record_receipt(pending, change, event_id=change.object_id, outcome="persisted")
        await store.accept_batch(source.connection, pending)

    asyncio.run(seed_accepted_source_receipts())


def test_memory_readiness_flushes_then_polls_real_connection_jobs(monkeypatch, tmp_path):
    from magi.awareness.source_readiness import source_projection_backlog
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.models import L2ProjectionLease
    from magi.events.events import Event, EventTypes
    from magi.memory.event_contracts import normalize_runtime_event

    client, _, _ = _build_client(monkeypatch)
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    l2 = L2CognitionStore(db_path=str(tmp_path / "memory.db"))
    event_ids = ["selected-1", "selected-2"]
    memory = SimpleNamespace(
        l1=SimpleNamespace(event_ids=event_ids, get_user_visible_event=l1.get_user_visible_event),
        l2=l2,
        memory_db_path=l2.db_path,
    )
    observations = []
    leases = []

    async def seed():
        for event_id in [*event_ids, "another-connection"]:
            await l1.store(
                normalize_runtime_event(
                    Event(
                        type=EventTypes.USER_MESSAGE,
                        source="screen_time",
                        event_id=event_id,
                        data={
                            "user_id": "user-1",
                            "content": event_id,
                            "author_type": "user",
                            "content_type": "text",
                        },
                    )
                )
            )
            await l2.enqueue_projection_job(
                event_id=event_id, source="screen_time", event_type=EventTypes.USER_MESSAGE
            )
        assert (await source_projection_backlog(memory, event_ids))["pending"] == 2

    asyncio.run(seed())

    async def flush():
        observations.append("flush")
        claimed = await l2.claim_projection_jobs(consumer_name="readiness-test", limit=10)
        leases.extend(
            L2ProjectionLease(
                event_id=row["event_id"],
                lease_token=row["lease_token"],
                attempt_count=row["attempt_count"],
            )
            for row in claimed
            if row["event_id"] in event_ids
        )
        assert len(leases) == 2
        assert await l2.bind_projection_job_batch(leases, consumer_name="readiness-test") == 2
        assert await l2.mark_projection_jobs_running(leases, consumer_name="readiness-test") == 2
        await l2.stage_event_entity_link_projections(
            desired_links_by_event={event_id: [] for event_id in event_ids},
            projection_leases=leases,
        )
        return len(claimed)

    async def backlog(selected_memory, selected_ids):
        assert selected_memory is memory
        assert set(selected_ids) == set(event_ids)
        result = await source_projection_backlog(memory, selected_ids)
        observations.append(("backlog", result["pending"], result["claimed"], result["completed"]))
        return result

    async def complete_on_poll(delay):
        assert delay == 0.5
        observations.append("wait")
        assert await l2.complete_projection_jobs(leases) == 2

    memory.flush_l2_projection_jobs = flush
    memory.projection_backlog = backlog
    _bind_readiness_memory(monkeypatch, memory)
    monkeypatch.setattr(sources_module, "asyncio", SimpleNamespace(sleep=complete_on_poll))
    try:
        response = client.get(
            "/api/sources/screen_time/memory-readiness",
            params={"connection_id": CONNECTION_ID, "max_wait_ms": 2000},
        )
        assert response.status_code == 200
        assert response.json() == {
            "connection_id": CONNECTION_ID,
            "source_name": "screen_time",
            "l1_event_count": 2,
            "l2_ready": True,
            "l2_total_count": 2,
            "l2_processed_count": 2,
            "l2_remaining_count": 0,
        }
        assert observations == ["flush", ("backlog", 0, 2, 0), "wait", ("backlog", 0, 0, 2)]
        assert (
            asyncio.run(source_projection_backlog(memory, ["another-connection"]))["claimed"] == 1
        )
    finally:
        client.close()
        asyncio.run(l1.shutdown())


def test_memory_readiness_not_ready_on_timeout(monkeypatch):
    client, _, _ = _build_client(monkeypatch)
    fake = _FakeReadinessMemory(
        rows=[{"source": "screen_time", "event_count": 3}],
        backlog_sequence=[{"pending": 2, "claimed": 0, "completed": 1, "failed": 0}],
    )
    _bind_readiness_memory(monkeypatch, fake)

    response = client.get(
        "/api/sources/screen_time/memory-readiness", params={"connection_id": CONNECTION_ID, "max_wait_ms": 10}
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

    response = client.get("/api/sources/screen_time/memory-readiness", params={"connection_id": CONNECTION_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["l1_event_count"] == 0
    assert body["l2_ready"] is False
    # Nothing to flush when there are no L1 events for this source.
    assert fake.flush_calls == 0


def test_memory_readiness_no_memory_binding(monkeypatch):
    client, _, _ = _build_client(monkeypatch)

    monkeypatch.setattr(
        "magi.api.routers.sources.get_unified_memory",
        lambda: (_ for _ in ()).throw(RuntimeError("no binding")),
    )

    response = client.get("/api/sources/screen_time/memory-readiness", params={"connection_id": CONNECTION_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["l1_event_count"] == 0
    assert body["l2_ready"] is False


def test_public_source_status_reports_unavailable_manager(monkeypatch):
    from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router

    def unavailable():
        raise RuntimeError("Plugin manager unavailable")

    monkeypatch.setattr(sources_module, "get_config", lambda: None)
    monkeypatch.setattr(sources_module, "resolve_plugin_manager", unavailable)
    app = FastAPI()
    app.include_router(_build_public_router(sources_router, _PUBLIC_ROUTE_METHODS["sources"]), prefix="/api/sources")
    response = TestClient(app).get("/api/sources/status")
    assert response.status_code == 503
    assert "sources" not in response.json()


def test_public_sync_history_is_bounded_and_connection_scoped(monkeypatch):
    from dataclasses import replace

    client, _, repository = _build_client(monkeypatch)
    registry = sources_module.resolve_source_registry()
    resolve = registry.resolve_source
    other_id = "screen-home"
    other_connection = PluginConnection(
        connection_id=other_id, plugin_id="screen-time", display_name="Home Mac", enabled=True
    )

    def resolve_two_accounts(source_name, *, connection_id):
        if source_name == "screen_time" and connection_id == other_id:
            return (
                "screen-time",
                "timeline.screen_time",
                SimpleNamespace(connection=other_connection),
                SimpleNamespace(metadata={"connection_id": other_id}),
            )
        return resolve(source_name, connection_id=connection_id)

    monkeypatch.setattr(registry, "resolve_source", resolve_two_accounts)
    monkeypatch.setattr(sources_module, "resolve_source_registry", lambda: registry)
    error = "PermissionError: browser data access denied: " + "nested-folder/" * 35 + "History"
    errors = {CONNECTION_ID: error, other_id: "Only the home account failed"}

    async def seed():
        original = await repository.get_schedule("source-sync:screen-account:screen_time")
        ids = {}
        for connection_id, message in errors.items():
            schedule = replace(
                original,
                schedule_id=f"source-sync:{connection_id}:screen_time",
                target_key=f"{connection_id}:screen_time",
                target_payload={
                    "plugin_id": "screen-time",
                    "connection_id": connection_id,
                    "source_type": "screen_time",
                },
            )
            await repository.upsert_schedule(schedule)
            admitted = await repository.enqueue_source_sync_execution(
                schedule=schedule, manual=True, started_at=time.time()
            )
            await repository.claim_next_source_sync_job(claimed_by="test")
            await repository.settle_source_sync_job_failure(
                admitted.job_id,
                error=message,
                failed_at=time.time(),
                retry_delay_seconds=0,
                max_attempts=1,
                scheduler_job_id=None,
                failure={"code": "file_access_denied", "platform": "darwin"},
            )
            ids[connection_id] = admitted.job_id
        return ids

    ids = asyncio.run(seed())
    for connection_id in errors:
        url = f"/api/sources/screen_time/sync-history?connection_id={connection_id}"
        response = client.get(url)
        assert response.status_code == 200
        payload = response.json()
        assert payload["connection_id"] == connection_id
        assert payload["total"] == 1
        assert [item["job_id"] for item in payload["items"]] == [ids[connection_id]]
        assert payload["items"][0]["failure"] == {
            "code": "file_access_denied",
            "platform": "darwin",
        }
        assert payload["items"][0]["error"] == errors[connection_id]
        assert client.get(url + "&offset=1").json()["items"] == []
        assert client.get(url + "&limit=101").status_code == 422
        assert client.get(url + "&offset=-1").status_code == 422
    assert (
        client.get("/api/sources/screen_time/sync-history?connection_id=unregistered").status_code
        == 404
    )
