from __future__ import annotations

import pytest

from magi.awareness.ingestion_gateway import SensorIngestionGateway
from magi.awareness.sensor_base import SensorBase
from magi.awareness.sensor_output import ContentBlock, SensorMemoryPolicy, SensorOutput, SensorOutputMetadata
from magi.config import AppConfig
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


class _FakePhotoLibrarySensor(SensorBase):
    sensor_id = "timeline.photo_library"
    source_type = "photo_library"
    memory_policy = SensorMemoryPolicy(
        retention_class="compressible",
        cognition_eligible=True,
        importance_bias=0.6,
    )

    async def build_output(self, payload):
        source_item_id = str(payload["source_item_id"])
        return self._build_output(
            source_item_id=source_item_id,
            title=str(payload["title"]),
            summary=str(payload["summary"]),
            occurred_at=float(payload["timestamp"]),
            content_blocks=[ContentBlock(kind="text", value=str(payload["summary"]))],
            tags=["photo_library"],
            domain_payload={"retention_mode": "retain_raw", "path": str(payload.get("path") or "")},
        )

    async def extract_metadata(self, payload):
        return SensorOutputMetadata(
            entities=[],
            tags=["photo_library"],
            relation_candidates=list(payload.get("relation_candidates", [])),
        )


class _FakeSensorRegistry:
    def resolve_domain_sensor(self, domain: str, source_type: str):
        if domain != "timeline" or source_type != "photo_library":
            return None
        spec = type("Spec", (), {"metadata": {"default_settings": {"enabled": True, "edge_whitelist": ["LIKES"]}}})()
        return ("photo-library", "timeline.photo_library", _FakePhotoLibrarySensor(), spec)


class _FakePluginManager:
    def get_package(self, plugin_id: str):
        if plugin_id != "photo-library":
            return None
        return type("Package", (), {"current_settings": {"sensors": {"photo_library": {"enabled": True}}}})()


@pytest.mark.asyncio
async def test_runtime_timeline_handler_persists_photo_library_entry_and_user_graph_edges() -> None:
    memory = _FakeUnifiedMemory()
    gateway = SensorIngestionGateway(
        unified_memory=memory,
        timeline_adapter=None,
    )
    handler = build_timeline_handler(
        AppConfig(),
        memory,
        sensor_registry=_FakeSensorRegistry(),
        plugin_manager=_FakePluginManager(),
        ingestion_gateway=gateway,
    )

    result = await handler(
        {
            "target_task_agent_id": "timeline-main",
            "source_type": "photo_library",
            "source_item_id": "photo-1",
            "path": "/tmp/photos/asuka.jpg",
            "title": "Asuka photo",
            "summary": "I still like Asuka best.",
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

    assert result == {"handled": True, "event_id": "photo_library:photo-1", "source_type": "photo_library"}
    assert len(memory.l1.timeline_events) == 1
    stored = memory.l1.timeline_events[0]
    assert stored["event_id"] == "photo_library:photo-1"
    assert stored["source"] == "photo_library"
    assert stored["content"] == "I still like Asuka best."
    assert len(memory.edges) == 1
    assert memory.edges[0]["predicate"] == "LIKES"
