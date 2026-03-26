from __future__ import annotations

import pytest

from magi.config import AppConfig
from magi.timeline import TimelineContentBlock, TimelineEvent
from magi.timeline.handler import build_timeline_handler


class _FakeL1Store:
    def __init__(self) -> None:
        self.timeline_events = []


class _FakeUnifiedMemory:
    def __init__(self) -> None:
        self.l1 = _FakeL1Store()
        self.edges: list[dict] = []

    async def ingest_event(self, event) -> dict:  # type: ignore[no-untyped-def]
        self.l1.timeline_events.append(event)
        correlation_id = (
            event.get("correlation_id")
            if isinstance(event, dict)
            else getattr(event, "correlation_id", None)
        )
        return {"event_id": correlation_id, "l1_written": True}

    async def upsert_user_graph_edge(self, **kwargs) -> None:
        self.edges.append(kwargs)


class _FakeManualJournalSensor:
    async def build_timeline_event(self, payload):  # type: ignore[no-untyped-def]
        entry_id = str(payload["entry_id"])
        return TimelineEvent(
            event_id=f"manual_journal:{entry_id}",
            source_type="manual_journal",
            source_item_id=entry_id,
            occurred_at=float(payload["timestamp"]),
            captured_at=float(payload["timestamp"]),
            title=str(payload["title"]),
            summary=str(payload["text"]),
            retention_mode="retain_raw",
            content_blocks=[
                TimelineContentBlock(kind="text", value=str(payload["text"])),
            ],
            processing_status={"stored": True},
            provenance={"entry_id": entry_id},
            tags=["journal"],
        )

    async def extract_candidates(self, payload):  # type: ignore[no-untyped-def]
        return {
            "entities": [],
            "tags": ["journal"],
            "relation_candidates": list(payload.get("relation_candidates", [])),
        }


class _FakeSensorRegistry:
    def resolve_domain_sensor(self, domain: str, source_type: str):
        if domain != "timeline" or source_type != "manual_journal":
            return None
        spec = type("Spec", (), {"metadata": {"default_settings": {"enabled": True, "edge_whitelist": ["LIKES"]}}})()
        return ("core-timeline", "timeline.manual_journal", _FakeManualJournalSensor(), spec)


class _FakePluginManager:
    def get_package(self, plugin_id: str):
        if plugin_id != "core-timeline":
            return None
        return type("Package", (), {"current_settings": {"sensors": {"manual_journal": {"enabled": True}}}})()


@pytest.mark.asyncio
async def test_runtime_timeline_handler_persists_manual_journal_entry_and_user_graph_edges() -> None:
    memory = _FakeUnifiedMemory()
    handler = build_timeline_handler(
        AppConfig(),
        memory,
        sensor_registry=_FakeSensorRegistry(),
        plugin_manager=_FakePluginManager(),
    )

    result = await handler(
        {
            "target_task_agent_id": "timeline-main",
            "source_type": "manual_journal",
            "source_item_id": "journal-1",
            "entry_id": "journal-1",
            "title": "Asuka note",
            "text": "I still like Asuka best.",
            "timestamp": 1710000000.0,
            "relation_candidates": [
                {
                    "subject_id": "user:self",
                    "subject_type": "user",
                    "predicate": "LIKES",
                    "object_id": "person:asuka",
                    "object_type": "person",
                    "confidence": 0.91,
                }
            ],
        }
    )

    assert result == {"handled": True, "event_id": "manual_journal:journal-1", "source_type": "manual_journal"}
    assert len(memory.l1.timeline_events) == 1
    stored_event = memory.l1.timeline_events[0]
    assert stored_event["correlation_id"] == "manual_journal:journal-1"
    assert stored_event["data"]["provenance"]["entry_id"] == "journal-1"
    assert [block["value"] for block in stored_event["data"]["content_blocks"]] == ["I still like Asuka best."]
    assert len(memory.edges) == 1
    assert memory.edges[0]["predicate"] == "LIKES"
