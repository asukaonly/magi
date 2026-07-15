from __future__ import annotations

import asyncio

import pytest

from magi.awareness.ingestion_gateway import SensorIngestionGateway
from magi.awareness.kg_write_queue import KnowledgeGraphWriteQueue
from magi.awareness.sensor_base import SensorBase
from magi.awareness.sensor_output import (
    ActivityFacet,
    ContentBlock,
    SensorActivity,
    SensorMemoryPolicy,
    SensorNarration,
    SensorOutputMetadata,
)
from magi.config import AppConfig
from magi.events.in_memory_backend import InMemoryMessageBusBackend
from magi.memory.event_contracts import MemoryEvent
from magi.memory.subscribers.memory_ingestion_subscriber import MemoryIngestionSubscriber
from magi.timeline.handler import build_timeline_handler
from magi.timeline.subscribers.kg_subscriber import KGSubscriber


class _FakeL1Store:
    def __init__(self) -> None:
        self.timeline_events = []


class _FakeUnifiedMemory:
    def __init__(self) -> None:
        self.l1 = _FakeL1Store()
        self.edges: list[dict] = []
        self.epoch = 0

    def memory_operation_epoch(self) -> int:
        return self.epoch

    async def ingest_event(  # type: ignore[no-untyped-def]
        self,
        event,
        *,
        expected_epoch: int,
    ) -> dict:
        if expected_epoch != self.epoch:
            return {"event_id": None, "l1_written": False, "skipped": True}
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
        summary = str(payload["summary"])
        return self._build_output(
            source_item_id=source_item_id,
            activity=SensorActivity(
                source=ActivityFacet(
                    code="photo_library",
                    i18n_key="activity.source.photo_library",
                    fallback="Photo Library",
                ),
                action=ActivityFacet(
                    code="capture",
                    i18n_key="activity.action.capture",
                    fallback="Captured",
                ),
            ),
            narration=SensorNarration(body=summary, title=str(payload["title"])),
            occurred_at=float(payload["timestamp"]),
            content_blocks=[ContentBlock(kind="text", value=summary)],
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
    """The timeline handler routes a photo_library payload through the
    SensorIngestionGateway publisher; independent subscribers (memory + KG)
    consume the published SensorEventEmitted and project the canonical
    MemoryEvent and user graph edge.

    The gateway is now a thin publisher (``SensorIngestionGateway(event_bus=…)``);
    persistence side-effects live in subscribers, so the test wires the two
    relevant subscribers and drives the in-memory bus end to end.
    """
    memory = _FakeUnifiedMemory()
    bus = InMemoryMessageBusBackend()
    await bus.start()
    bus.bind_memory_operation_epoch(memory.memory_operation_epoch)

    memory_sub = MemoryIngestionSubscriber(event_bus=bus, unified_memory=memory)
    await memory_sub.start()

    kg_writer = KnowledgeGraphWriteQueue(unified_memory=memory)
    kg_sub = KGSubscriber(event_bus=bus, kg_writer=kg_writer)
    await kg_sub.start()

    gateway = SensorIngestionGateway(event_bus=bus)
    handler = build_timeline_handler(
        AppConfig(),
        memory,
        sensor_registry=_FakeSensorRegistry(),
        plugin_manager=_FakePluginManager(),
        ingestion_gateway=gateway,
    )

    try:
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

        # Let the bus fan out, then await all inflight subscriber work.
        await asyncio.sleep(0.05)
        await memory_sub.drain()
        await kg_sub.drain()
    finally:
        await kg_sub.stop()
        await memory_sub.stop()
        await bus.stop()

    assert result["handled"] is True
    assert result["source_type"] == "photo_library"
    assert len(memory.l1.timeline_events) == 1
    stored = memory.l1.timeline_events[0]
    assert isinstance(stored, MemoryEvent)
    assert result["event_id"] == stored.event_id
    assert stored.idempotency_key == "photo-1"
    assert stored.source == "photo_library"
    # build_sensor_projection composes content as "<activity display prefix>
    # <narration body>", so the persisted L1 content carries the activity
    # prefix in front of the narration body.
    assert stored.content == "Photo Library Captured I still like Asuka best."
    assert "I still like Asuka best." in stored.content
    assert len(memory.edges) == 1
    assert memory.edges[0]["predicate"] == "LIKES"
