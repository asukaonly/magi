import asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import tempfile

from magi.api.routers import timeline as timeline_module
from magi.api.routers.timeline import timeline_router
from magi.plugins import ExtensionFieldSpec
from magi.scheduler import (
    SchedulerService,
    ScheduleDefinition,
    ScheduledExecutionResult,
    ScheduledTargetState,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)
from magi.scheduler.repository import ScheduleRepository
from magi.timeline.contracts import TimelineContentBlock, TimelineEvent


class _FakeTimelineService:
    def __init__(self):
        self.viewport_calls = []
        self.context_calls = []

    async def get_viewport(self, *, scale, start, end, query=None, timezone=None, focus="self"):
        self.viewport_calls.append(
            {
                "scale": scale,
                "start": start,
                "end": end,
                "query": query,
                "timezone": timezone,
                "focus": focus,
            }
        )
        payload = {
            "viewport": {
                "scale": scale,
                "start": start,
                "end": end,
                "focus": focus,
                "query": query,
                "timezone": timezone,
            },
            "summary": {
                "cluster_count": 1 if scale in {"week", "day"} else 0,
                "event_count": 3,
                "dominant_modes": ["deep_work"],
            },
            "state_bands": [
                {
                    "band_id": "band-1",
                    "time_start": start,
                    "time_end": end,
                    "valence": 0.35,
                    "stress_level": 0.62,
                    "engagement": 0.78,
                    "confidence": 0.71,
                    "label": "Focused with mild stress",
                    "source_summary_ids": ["summary-1"],
                    "source_assertion_ids": ["assertion-1"],
                }
            ],
            "state_markers": [
                {
                    "marker_id": "marker-1",
                    "timestamp": start + 3600,
                    "kind": "shift",
                    "label": "Stress rose",
                    "summary": "Pressure increased around midday.",
                    "source_band_ids": ["band-1"],
                    "source_summary_ids": ["summary-1"],
                }
            ],
            "clusters": [],
            "reflections": [],
            "raw_events": [],
        }
        if scale == "month":
            payload["reflections"] = [
                {
                    "reflection_id": "reflection-1",
                    "time_start": start,
                    "time_end": end,
                    "title": "Month reflection",
                    "summary": "A sustained month of focused work and recovery.",
                    "key_topics": ["work", "recovery"],
                    "key_entities": ["project:magi"],
                    "sentiment_summary": {"tone": "steady"},
                    "change_and_pattern": {"patterns": ["late-night work"]},
                    "source_summary_ids": ["summary-1"],
                    "source_event_ids": ["event-1", "event-2"],
                }
            ]
        elif scale in {"week", "day"}:
            payload["clusters"] = [
                {
                    "block_id": "cluster-1",
                    "time_start": start,
                    "time_end": min(end, start + 7200),
                    "duration_seconds": min(end - start, 7200),
                    "label": "Deep work",
                    "summary": "A long focused stretch across coding and note-taking.",
                    "dominant_mode": "deep_work",
                    "source_types": ["chat", "manual_journal"],
                    "event_count": 3,
                    "representative_event_ids": ["event-1", "event-2"],
                    "keywords": ["coding", "notes"],
                    "media_refs": [],
                    "state_snapshot": {
                        "valence": 0.32,
                        "stress_level": 0.61,
                        "engagement": 0.83,
                    },
                }
            ]
        elif scale == "hour":
            payload["raw_events"] = [
                {
                    "event_id": "event-1",
                    "timestamp": start + 300,
                    "title": "Opened design note",
                    "summary": "Reviewing implementation notes.",
                    "source_type": "manual_journal",
                }
            ]
        return payload

    async def get_context_bundle(self, anchor_id):
        self.context_calls.append(anchor_id)
        return {
            "anchor": {
                "anchor_id": anchor_id,
                "anchor_type": "cluster",
                "title": "Deep work",
                "summary": "A long focused stretch across coding and note-taking.",
            },
            "l1_events": [
                {
                    "event_id": "event-1",
                    "title": "Opened design note",
                    "summary": "Reviewing implementation notes.",
                    "source_type": "manual_journal",
                }
            ],
            "l2_state_evidence": [
                {
                    "assertion_id": "assertion-1",
                    "trait_name": "mood",
                    "trait_value": "focused",
                    "confidence_score": 0.74,
                }
            ],
            "l3_reflections": [
                {
                    "summary_id": "summary-1",
                    "summary_category": "day",
                    "content": "Focus remained high despite rising stress.",
                }
            ],
            "l4_related_procedures": [
                {
                    "skill_id": "skill-1",
                    "skill_name": "Deep work loop",
                    "success_rate": 0.81,
                }
            ],
            "chat_excerpts": [
                {
                    "event_id": "event-2",
                    "content": "Let's restructure the timeline around semantic zoom.",
                }
            ],
            "runtime_trace": [],
        }


class _FakeSchedulerRepository:
    async def get_schedule(self, schedule_id):
        return type("Schedule", (), {"job_id": schedule_id})()


class _FakeSchedulerService:
    def __init__(self) -> None:
        self.repository = _FakeSchedulerRepository()

    async def get_target_state(self, target_type, target_key):
        return ScheduledTargetState(
            target_type=ScheduledTargetType.TIMELINE_SENSOR_SYNC,
            target_key=target_key,
            running=True,
            last_run_at=1710000190.0,
            last_success_at=1710000200.0,
            last_error=None,
            next_run_at=1710000500.0,
            scheduler_job_id="timeline-sync:photo-library:photo_library",
            stats={"count": 4, "raw_count": 7},
        )


class _FakeTimelineSchedulerContrib:
    async def queue_manual_sync(self, source_name):
        return type("Schedule", (), {"schedule_id": f"manual:{source_name}"})()


class _FakeRuntimeCommandQueue:
    def __init__(self) -> None:
        self.timeline_sync_commands: list[object] = []

    async def enqueue_timeline_source_sync(self, command):
        self.timeline_sync_commands.append(command)
        return len(self.timeline_sync_commands)


def _build_client(monkeypatch):
    app = FastAPI()
    app.include_router(timeline_router, prefix="/api/timeline")
    service = _FakeTimelineService()
    monkeypatch.setattr(timeline_module, "get_timeline_service", lambda: service)
    monkeypatch.setattr(timeline_module, "get_config", lambda: type("Config", (), {})())
    runtime_base_dir = tempfile.mkdtemp(prefix="magi-runtime-")
    monkeypatch.setattr(
        timeline_module,
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
            "manifest": type("Manifest", (), {"plugin_id": "photo-library"})(),
            "current_settings": {
                "sensors": {
                    "photo_library": {
                        "enabled": False,
                        "sync_mode": "interval",
                        "sync_interval_minutes": 60,
                        "default_retention_mode": "retain_raw",
                        "storage_mode": "external_reference",
                        "source_path": "",
                        "fetch_page_content": False,
                        "edge_whitelist": ["CAPTURED", "RELATED_TO", "INTERACTED_WITH", "CREATED"],
                    }
                }
            },
        },
    )()
    monkeypatch.setattr(
        timeline_module,
        "require_plugin_manager",
        lambda: type("Manager", (), {"list_packages": lambda self: [plugin_state]})(),
    )
    monkeypatch.setattr(
        timeline_module,
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
                            "plugin_id": "photo-library",
                            "contribution_id": "timeline.photo_library",
                            "display_name": "Photo Library",
                            "description": "Photo assets referenced from a local library path.",
                            "fields": [
                                ExtensionFieldSpec(
                                    key="sensors.photo_library.enabled",
                                    type="switch",
                                    label="Enabled",
                                    default=True,
                                    surface="timeline",
                                ),
                                ExtensionFieldSpec(
                                    key="sensors.photo_library.source_path",
                                    type="path",
                                    label="Source Path",
                                    default="",
                                    surface="timeline",
                                ),
                            ],
                            "metadata": {
                                "domain": "timeline",
                                "source_type": "photo_library",
                                "default_settings": {
                                    "sync_mode": "interval",
                                    "sync_interval_minutes": 60,
                                    "default_retention_mode": "retain_raw",
                                    "storage_mode": "external_reference",
                                    "source_path": "",
                                    "fetch_page_content": False,
                                    "edge_whitelist": ["CAPTURED", "RELATED_TO", "INTERACTED_WITH", "CREATED"],
                                },
                            },
                        },
                    )()
                ],
                "resolve_domain_sensor": lambda self, domain, source_name: (
                    (
                        "photo-library",
                        "timeline.photo_library",
                        type("Sensor", (), {"supports_pull_sync": True})(),
                        object(),
                    )
                    if domain == "timeline" and source_name == "photo_library"
                    else None
                ),
            },
        )(),
    )
    monkeypatch.setattr(
        timeline_module,
        "require_runtime_command_queue",
        lambda: _FakeRuntimeCommandQueue(),
    )
    repository = ScheduleRepository(f"{runtime_base_dir}/data/scheduler.db")

    async def _seed_state():
        await repository.initialize()
        schedule_id = "timeline-sync:photo-library:photo_library"
        await repository.upsert_schedule(
            ScheduleDefinition(
                schedule_id=schedule_id,
                target_type=ScheduledTargetType.TIMELINE_SENSOR_SYNC,
                target_key="photo-library:photo_library",
                trigger=TriggerDefinition(
                    trigger_type=TriggerType.INTERVAL,
                    config={"minutes": 60},
                ),
                target_payload={"source_name": "photo_library"},
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
            ScheduledTargetType.TIMELINE_SENSOR_SYNC,
            "photo-library:photo_library",
        )
        await repository.record_target_success(
            ScheduledTargetType.TIMELINE_SENSOR_SYNC,
            "photo-library:photo_library",
            result=ScheduledExecutionResult(
                success=True,
                message="timeline_sync_completed",
                stats={"count": 4, "raw_count": 7},
            ),
            next_run_at=1710000500.0,
            scheduler_job_id=schedule_id,
        )

    asyncio.run(_seed_state())
    return TestClient(app), service


def test_get_timeline_viewport_returns_month_reflections(monkeypatch):
    client, service = _build_client(monkeypatch)

    response = client.get(
        "/api/timeline/viewport",
        params={"scale": "month", "start": 1710000000, "end": 1712592000, "timezone": "Asia/Shanghai"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["viewport"]["scale"] == "month"
    assert body["reflections"][0]["reflection_id"] == "reflection-1"
    assert body["state_bands"][0]["band_id"] == "band-1"
    assert service.viewport_calls[0]["scale"] == "month"
    assert service.viewport_calls[0]["timezone"] == "Asia/Shanghai"


def test_get_timeline_viewport_returns_day_clusters(monkeypatch):
    client, service = _build_client(monkeypatch)

    response = client.get(
        "/api/timeline/viewport",
        params={"scale": "day", "start": 1710000000, "end": 1710086400, "query": "focused coding"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["viewport"]["scale"] == "day"
    assert body["clusters"][0]["block_id"] == "cluster-1"
    assert body["clusters"][0]["dominant_mode"] == "deep_work"
    assert service.viewport_calls[0]["query"] == "focused coding"


def test_get_timeline_viewport_returns_hour_raw_events(monkeypatch):
    client, _ = _build_client(monkeypatch)

    response = client.get(
        "/api/timeline/viewport",
        params={"scale": "hour", "start": 1710000000, "end": 1710003600},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["viewport"]["scale"] == "hour"
    assert body["raw_events"][0]["event_id"] == "event-1"
    assert body["clusters"] == []


def test_get_timeline_context_bundle_returns_cross_layer_sections(monkeypatch):
    client, service = _build_client(monkeypatch)

    response = client.get("/api/timeline/context/cluster-1")

    assert response.status_code == 200
    body = response.json()
    assert body["anchor"]["anchor_id"] == "cluster-1"
    assert body["l1_events"][0]["event_id"] == "event-1"
    assert body["l2_state_evidence"][0]["assertion_id"] == "assertion-1"
    assert body["l3_reflections"][0]["summary_id"] == "summary-1"
    assert body["l4_related_procedures"][0]["skill_id"] == "skill-1"
    assert service.context_calls == ["cluster-1"]


def test_get_timeline_source_status(monkeypatch):
    client, _ = _build_client(monkeypatch)

    response = client.get("/api/timeline/sources/status")

    assert response.status_code == 200
    body = response.json()
    assert body["sources"][0]["source_name"] == "photo_library"
    assert body["sources"][0]["fetch_page_content"] is False
    assert body["sources"][0]["plugin_id"] == "photo-library"
    assert body["sources"][0]["supports_pull_sync"] is True
    assert body["sources"][0]["scheduler_job_id"] == "timeline-sync:photo-library:photo_library"
    assert body["sources"][0]["activation_flow"] is None
    assert body["sources"][0]["activation_required"] is False
    assert body["sources"][0]["enabled"] is False
    assert body["sources"][0]["running"] is False
    assert body["sources"][0]["last_run_at"] is not None
    assert body["sources"][0]["last_result_count"] == 4
    assert body["sources"][0]["last_raw_result_count"] == 7


@pytest.mark.asyncio
async def test_get_timeline_source_status_reads_persisted_scheduler_state_when_service_unavailable(
    monkeypatch, tmp_path
):
    app = FastAPI()
    app.include_router(timeline_router, prefix="/api/timeline")
    monkeypatch.setattr(timeline_module, "get_timeline_service", lambda: _FakeTimelineService())
    monkeypatch.setattr(timeline_module, "get_config", lambda: type("Config", (), {})())
    runtime_base_dir = tmp_path / "runtime"
    runtime_paths = type(
        "Paths",
        (),
        {
            "base_dir": runtime_base_dir,
            "scheduler_db_path": runtime_base_dir / "data" / "scheduler.db",
        },
    )()
    monkeypatch.setattr(timeline_module, "get_runtime_paths", lambda: runtime_paths)
    plugin_state = type(
        "PluginState",
        (),
        {
            "manifest": type("Manifest", (), {"plugin_id": "photo-library"})(),
            "current_settings": {
                "sensors": {
                    "photo_library": {
                        "enabled": True,
                        "sync_mode": "interval",
                        "sync_interval_minutes": 60,
                        "default_retention_mode": "retain_raw",
                    }
                }
            },
        },
    )()
    monkeypatch.setattr(
        timeline_module,
        "require_plugin_manager",
        lambda: type("Manager", (), {"list_packages": lambda self: [plugin_state]})(),
    )
    monkeypatch.setattr(
        timeline_module,
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
                            "plugin_id": "photo-library",
                            "contribution_id": "timeline.photo_library",
                            "display_name": "Photo Library",
                            "description": "Photo assets referenced from a local library path.",
                            "fields": [],
                            "metadata": {
                                "domain": "timeline",
                                "source_type": "photo_library",
                                "default_settings": {
                                    "enabled": True,
                                    "sync_mode": "interval",
                                    "sync_interval_minutes": 60,
                                    "default_retention_mode": "retain_raw",
                                },
                            },
                        },
                    )()
                ],
                "resolve_domain_sensor": lambda self, domain, source_name: (
                    (
                        "photo-library",
                        "timeline.photo_library",
                        type("Sensor", (), {"supports_pull_sync": True})(),
                        object(),
                    )
                    if domain == "timeline" and source_name == "photo_library"
                    else None
                ),
            },
        )(),
    )
    repository = ScheduleRepository(runtime_paths.scheduler_db_path)
    await repository.initialize()
    target_type = ScheduledTargetType.TIMELINE_SENSOR_SYNC
    target_key = "photo-library:photo_library"
    schedule_id = "timeline-sync:photo-library:photo_library"
    await repository.upsert_schedule(
        ScheduleDefinition(
            schedule_id=schedule_id,
            target_type=target_type,
            target_key=target_key,
            trigger=TriggerDefinition(
                trigger_type=TriggerType.INTERVAL,
                config={"minutes": 60},
            ),
            target_payload={"source_name": "photo_library"},
            metadata={},
            enabled=True,
            job_id=schedule_id,
        )
    )
    await repository.update_schedule_binding(
        schedule_id,
        job_id=schedule_id,
        next_run_at=1710000600.0,
    )
    await repository.record_target_success(
        target_type,
        target_key,
        result=ScheduledExecutionResult(
            success=True,
            message="timeline_sync_completed",
            stats={"count": 9, "raw_count": 11},
            next_cursor="cursor-1",
        ),
        next_run_at=1710000600.0,
        scheduler_job_id=schedule_id,
    )

    client = TestClient(app)
    response = client.get("/api/timeline/sources/status")

    assert response.status_code == 200
    body = response.json()
    assert body["sources"][0]["last_result_count"] == 9
    assert body["sources"][0]["last_raw_result_count"] == 11
    assert body["sources"][0]["next_run_at"] == 1710000600.0
    assert body["sources"][0]["scheduler_job_id"] == schedule_id


def test_get_timeline_source_status_hides_stale_errors_for_non_pull_sources(monkeypatch, tmp_path):
    app = FastAPI()
    app.include_router(timeline_router, prefix="/api/timeline")
    monkeypatch.setattr(timeline_module, "get_timeline_service", lambda: _FakeTimelineService())
    monkeypatch.setattr(timeline_module, "get_config", lambda: type("Config", (), {})())
    runtime_base_dir = tmp_path / "runtime"
    repository = ScheduleRepository(runtime_base_dir / "data" / "scheduler.db")

    async def _seed_state():
        await repository.initialize()
        schedule_id = "timeline-sync:photo-library:photo_library"
        await repository.upsert_schedule(
            ScheduleDefinition(
                schedule_id=schedule_id,
                target_type=ScheduledTargetType.TIMELINE_SENSOR_SYNC,
                target_key="photo-library:photo_library",
                trigger=TriggerDefinition(
                    trigger_type=TriggerType.INTERVAL,
                    config={"minutes": 1},
                ),
                target_payload={"source_name": "photo_library"},
                metadata={},
                enabled=True,
                job_id=schedule_id,
            )
        )
        await repository.record_target_failure(
            ScheduledTargetType.TIMELINE_SENSOR_SYNC,
            "photo-library:photo_library",
            error="timeline.photo_library does not implement pull sync",
            next_run_at=None,
            scheduler_job_id=None,
        )

    asyncio.run(_seed_state())
    monkeypatch.setattr(
        timeline_module,
        "get_runtime_paths",
        lambda: type(
            "Paths",
            (),
            {
                "base_dir": runtime_base_dir,
                "scheduler_db_path": runtime_base_dir / "data" / "scheduler.db",
            },
        )(),
    )
    plugin_state = type(
        "PluginState",
        (),
        {
            "manifest": type("Manifest", (), {"plugin_id": "photo-library"})(),
            "current_settings": {"sensors": {"photo_library": {"enabled": True, "sync_mode": "manual"}}},
        },
    )()
    monkeypatch.setattr(
        timeline_module,
        "require_plugin_manager",
        lambda: type("Manager", (), {"list_packages": lambda self: [plugin_state]})(),
    )
    monkeypatch.setattr(
        timeline_module,
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
                            "plugin_id": "photo-library",
                            "contribution_id": "timeline.photo_library",
                            "display_name": "Photo Library",
                            "description": "Photo assets referenced from a local library path.",
                            "fields": [],
                            "metadata": {
                                "domain": "timeline",
                                "source_type": "photo_library",
                                "default_settings": {
                                    "enabled": True,
                                    "sync_mode": "manual",
                                    "sync_interval_minutes": 1,
                                },
                            },
                        },
                    )()
                ],
                "resolve_domain_sensor": lambda self, domain, source_name: (
                    (
                        "photo-library",
                        "timeline.photo_library",
                        type("Sensor", (), {"supports_pull_sync": False})(),
                        object(),
                    )
                    if domain == "timeline" and source_name == "photo_library"
                    else None
                ),
            },
        )(),
    )
    client = TestClient(app)

    response = client.get("/api/timeline/sources/status")

    assert response.status_code == 200
    body = response.json()
    assert body["sources"][0]["source_name"] == "photo_library"
    assert body["sources"][0]["supports_pull_sync"] is False
    assert body["sources"][0]["last_error"] is None


def test_get_timeline_source_status_prefers_recurring_next_run_after_manual_sync(monkeypatch, tmp_path):
    app = FastAPI()
    app.include_router(timeline_router, prefix="/api/timeline")
    monkeypatch.setattr(timeline_module, "get_timeline_service", lambda: _FakeTimelineService())
    monkeypatch.setattr(timeline_module, "get_config", lambda: type("Config", (), {})())
    runtime_base_dir = tmp_path / "runtime"
    scheduler_db_path = runtime_base_dir / "data" / "scheduler.db"
    runtime_base_dir.mkdir(parents=True, exist_ok=True)

    async def _seed_state():
        service = SchedulerService(db_path=scheduler_db_path, runtime_dir=runtime_base_dir)

        async def _handler(_context):
            return ScheduledExecutionResult(success=True, message="ok", stats={"count": 1})

        service.register_handler(ScheduledTargetType.TIMELINE_SENSOR_SYNC, _handler)
        await service.start()
        await service.schedule_interval(
            schedule_id="timeline-sync:calendar:calendar",
            target_type=ScheduledTargetType.TIMELINE_SENSOR_SYNC,
            target_key="calendar:calendar",
            seconds=1800.0,
            target_payload={"plugin_id": "calendar", "source_type": "calendar", "manual": False},
        )
        await service.repository.record_target_success(
            ScheduledTargetType.TIMELINE_SENSOR_SYNC,
            "calendar:calendar",
            result=ScheduledExecutionResult(success=True, message="timeline_sync_completed", stats={"count": 1}),
            next_run_at=None,
            scheduler_job_id="timeline-sync-manual:calendar:calendar:test",
        )
        await service.stop()

    asyncio.run(_seed_state())
    monkeypatch.setattr(
        timeline_module,
        "get_runtime_paths",
        lambda: type(
            "Paths",
            (),
            {
                "base_dir": runtime_base_dir,
                "scheduler_db_path": scheduler_db_path,
            },
        )(),
    )
    plugin_state = type(
        "PluginState",
        (),
        {
            "manifest": type("Manifest", (), {"plugin_id": "calendar"})(),
            "current_settings": {
                "sensors": {
                    "calendar": {
                        "enabled": True,
                        "sync_mode": "interval",
                        "sync_interval_minutes": 30,
                    }
                }
            },
        },
    )()
    monkeypatch.setattr(
        timeline_module,
        "require_plugin_manager",
        lambda: type("Manager", (), {"list_packages": lambda self: [plugin_state]})(),
    )
    monkeypatch.setattr(
        timeline_module,
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
                            "plugin_id": "calendar",
                            "contribution_id": "timeline.calendar",
                            "display_name": "Calendar",
                            "description": "Calendar event ingestion for the timeline.",
                            "fields": [
                                ExtensionFieldSpec(
                                    key="sensors.calendar.enabled",
                                    type="switch",
                                    label="Enabled",
                                    description="Whether this source is active.",
                                    default=True,
                                    section="general",
                                    surface="timeline",
                                    order=10,
                                )
                            ],
                            "metadata": {
                                "domain": "timeline",
                                "source_type": "calendar",
                                "default_settings": {
                                    "enabled": True,
                                    "sync_mode": "interval",
                                    "sync_interval_minutes": 30,
                                },
                                "sync_mode": "interval",
                            },
                        },
                    )()
                ],
                "resolve_domain_sensor": lambda self, domain, source_name: (
                    (
                        "calendar",
                        "timeline.calendar",
                        type("Sensor", (), {"supports_pull_sync": True})(),
                        type("Spec", (), {"metadata": {"default_settings": {}}, "sync_mode": "interval"})(),
                    )
                    if domain == "timeline" and source_name == "calendar"
                    else None
                ),
            },
        )(),
    )
    client = TestClient(app)

    response = client.get("/api/timeline/sources/status")

    assert response.status_code == 200
    body = response.json()
    assert body["sources"][0]["scheduler_job_id"] == "timeline-sync:calendar:calendar"
    assert body["sources"][0]["next_run_at"] is not None


def test_trigger_timeline_source_sync_returns_schedule_id(monkeypatch):
    client, _ = _build_client(monkeypatch)

    response = client.post("/api/timeline/sources/photo_library/sync")

    assert response.status_code == 200
    assert response.json()["queued"] is True
    assert response.json()["source_name"] == "photo_library"
    assert response.json()["command_id"] == 1


def test_authorize_timeline_source_returns_authorization_result(monkeypatch):
    app = FastAPI()
    app.include_router(timeline_router, prefix="/api/timeline")
    monkeypatch.setattr(timeline_module, "get_config", lambda: type("Config", (), {})())
    sensor = type(
        "Sensor",
        (),
        {
            "request_activation_authorization": lambda self, field_values: {
                "authorized": True,
                "granted_types": ["steps"],
                "denied_types": [],
                "requested_types": ["steps"],
            }
        },
    )()
    monkeypatch.setattr(
        timeline_module,
        "require_sensor_registry",
        lambda: type(
            "Registry",
            (),
            {
                "resolve_domain_sensor": lambda self, domain, source_name: (
                    ("calendar", "timeline.calendar", sensor, object())
                    if domain == "timeline" and source_name == "calendar"
                    else None
                ),
            },
        )(),
    )

    client = TestClient(app)

    response = client.post(
        "/api/timeline/sources/calendar/authorize",
        json={"field_values": {"sensors.calendar.authorization_configured": True}},
    )

    assert response.status_code == 200
    assert response.json()["authorized"] is True
    assert response.json()["granted_types"] == ["steps"]
