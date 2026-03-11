from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import timeline as timeline_module
from magi.api.routers.timeline import timeline_router
from magi.plugins import ExtensionFieldSpec
from magi.timeline import TimelineContentBlock, TimelineEvent


class _FakeTimelineService:
    def __init__(self):
        self.created = []
        self.events = {
            "timeline-1": {
                "event_id": "timeline-1",
                "source_type": "manual_journal",
                "source_item_id": "manual-1",
                "occurred_at": 1710000000.0,
                "captured_at": 1710000001.0,
                "title": "Evening note",
                "summary": "Wrote about the day",
                "retention_mode": "retain_raw",
                "raw_payload_ref": "/tmp/day-note.md",
                "content_blocks": [{"kind": "text", "value": "Today was calm."}],
                "processing_status": {"stored": True},
                "provenance": {"sensor_id": "manual_journal"},
            }
        }

    async def list_events(self, limit=50, source_type=None):
        events = list(self.events.values())[:limit]
        if source_type:
            events = [event for event in events if event["source_type"] == source_type]
        return events

    async def get_event(self, event_id):
        return self.events.get(event_id)

    async def get_event_detail(self, event_id):
        event = self.events.get(event_id)
        if event is None:
            return None
        return {
            **event,
            "graph_evidence": [
                {
                    "subject_id": "user:self",
                    "predicate": "LIKES",
                    "object_id": "topic:day",
                    "evidence_event_ids": [event_id],
                    "confidence": 0.8,
                }
            ],
        }

    async def create_manual_journal(self, title, summary, text, image_refs):
        event = TimelineEvent(
            event_id="timeline-created",
            source_type="manual_journal",
            source_item_id="manual-created",
            occurred_at=1710000100.0,
            captured_at=1710000100.0,
            title=title,
            summary=summary,
            retention_mode="retain_raw",
            content_blocks=[
                TimelineContentBlock(kind="text", value=text),
                *[TimelineContentBlock(kind="image", value=image_ref) for image_ref in image_refs],
            ],
            processing_status={"stored": True},
            provenance={"sensor_id": "manual_journal"},
        )
        self.created.append(event)
        self.events[event.event_id] = event.to_dict()
        return event

    async def reanalyze_event(self, event_id):
        return self.events.get(event_id)


def _build_client(monkeypatch):
    app = FastAPI()
    app.include_router(timeline_router, prefix="/api/timeline")
    service = _FakeTimelineService()
    monkeypatch.setattr(timeline_module, "get_timeline_service", lambda: service)
    monkeypatch.setattr(timeline_module, "get_config", lambda: type("Config", (), {})())
    monkeypatch.setattr(
        timeline_module,
        "get_runtime_paths",
        lambda: type("Paths", (), {"base_dir": "/tmp/magi-runtime"})(),
    )
    plugin_state = type(
        "PluginState",
        (),
        {
            "manifest": type("Manifest", (), {"plugin_id": "core-timeline"})(),
            "current_settings": {
                "sensors": {
                    "browser_history": {
                        "enabled": True,
                        "sync_mode": "interval",
                        "sync_interval_minutes": 30,
                        "default_retention_mode": "analyze_only",
                        "storage_mode": "managed",
                        "source_path": "",
                        "fetch_page_content": False,
                        "edge_whitelist": ["VIEWED", "VISITED", "CARES_ABOUT", "LIKES"],
                    }
                }
            },
        },
    )()
    monkeypatch.setattr(
        timeline_module,
        "get_plugin_manager",
        lambda: type("Manager", (), {"list_packages": lambda self: [plugin_state]})(),
    )
    monkeypatch.setattr(
        timeline_module,
        "get_sensor_registry",
        lambda: type(
            "Registry",
            (),
            {
                "list_contributions": lambda self: [
                    type(
                        "Contribution",
                        (),
                        {
                            "plugin_id": "core-timeline",
                            "contribution_id": "timeline.browser_history",
                            "display_name": "Browser History",
                            "description": "Visited URLs",
                            "fields": [
                                ExtensionFieldSpec(
                                    key="sensors.browser_history.enabled",
                                    type="switch",
                                    label="Enabled",
                                    default=True,
                                    surface="timeline",
                                ),
                                ExtensionFieldSpec(
                                    key="sensors.browser_history.fetch_page_content",
                                    type="switch",
                                    label="Fetch Page Content",
                                    default=False,
                                    surface="timeline",
                                ),
                            ],
                            "metadata": {
                                "domain": "timeline",
                                "source_type": "browser_history",
                                "default_settings": {
                                    "sync_mode": "interval",
                                    "sync_interval_minutes": 30,
                                    "default_retention_mode": "analyze_only",
                                    "storage_mode": "managed",
                                    "source_path": "",
                                    "fetch_page_content": False,
                                    "edge_whitelist": ["VIEWED", "VISITED", "CARES_ABOUT", "LIKES"],
                                },
                            },
                        },
                    )()
                ],
                "resolve_domain_sensor": lambda self, domain, source_name: (
                    ("core-timeline", "timeline.browser_history", object(), object())
                    if domain == "timeline" and source_name == "browser_history"
                    else None
                ),
            },
        )(),
    )
    return TestClient(app), service


def test_list_timeline_events_returns_retention_metadata(monkeypatch):
    client, _ = _build_client(monkeypatch)

    response = client.get("/api/timeline/events")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["events"][0]["retention"]["mode"] == "retain_raw"
    assert body["events"][0]["retention"]["raw_payload_ref"] == "/tmp/day-note.md"


def test_create_manual_entry_returns_created_event(monkeypatch):
    client, service = _build_client(monkeypatch)

    response = client.post(
        "/api/timeline/manual",
        json={
            "title": "Journal",
            "summary": "Short summary",
            "text": "Today felt good.",
            "image_refs": ["/tmp/photo.png"],
        },
    )

    assert response.status_code == 201
    assert response.json()["event_id"] == "timeline-created"
    assert len(service.created) == 1


def test_get_timeline_source_status(monkeypatch):
    client, _ = _build_client(monkeypatch)

    response = client.get("/api/timeline/sources/status")

    assert response.status_code == 200
    body = response.json()
    assert body["sources"][0]["source_name"] == "browser_history"
    assert body["sources"][0]["fetch_page_content"] is False
    assert body["sources"][0]["plugin_id"] == "core-timeline"


def test_reanalyze_timeline_event_returns_existing_event(monkeypatch):
    client, _ = _build_client(monkeypatch)

    response = client.post("/api/timeline/events/timeline-1/reanalyze")

    assert response.status_code == 200
    assert response.json()["queued"] is True
    assert response.json()["event"]["event_id"] == "timeline-1"


def test_get_timeline_event_detail_includes_graph_evidence(monkeypatch):
    client, _ = _build_client(monkeypatch)

    response = client.get("/api/timeline/events/timeline-1")

    assert response.status_code == 200
    body = response.json()
    assert body["graph_evidence"][0]["predicate"] == "LIKES"
    assert body["retention"]["mode"] == "retain_raw"
