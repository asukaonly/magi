from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import timeline as timeline_module
from magi.api.routers.timeline import timeline_router
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
    monkeypatch.setattr(
        timeline_module,
        "get_config",
        lambda: type(
            "Config",
            (),
            {
                "timeline": type(
                    "TimelineConfig",
                    (),
                    {
                        "sources": type(
                            "TimelineSources",
                            (),
                            {
                                "model_dump": staticmethod(
                                    lambda: {
                                        "browser_history": {
                                            "enabled": True,
                                            "sync_mode": "interval",
                                            "sync_interval_minutes": 30,
                                            "default_retention_mode": "analyze_only",
                                            "storage_mode": "managed",
                                            "source_path": None,
                                            "fetch_page_content": False,
                                            "edge_whitelist": ["VIEWED", "VISITED", "CARES_ABOUT", "LIKES"],
                                        }
                                    }
                                )
                            },
                        )()
                    },
                )()
            },
        )(),
    )
    monkeypatch.setattr(
        timeline_module,
        "get_runtime_paths",
        lambda: type("Paths", (), {"base_dir": "/tmp/magi-runtime"})(),
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


def test_reanalyze_timeline_event_returns_existing_event(monkeypatch):
    client, _ = _build_client(monkeypatch)

    response = client.post("/api/timeline/events/timeline-1/reanalyze")

    assert response.status_code == 200
    assert response.json()["queued"] is True
    assert response.json()["event"]["event_id"] == "timeline-1"
