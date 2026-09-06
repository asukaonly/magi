from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.runtime import PluginConnection
from magi_plugin_sdk.sources import SourceSpec

from magi.awareness.ingestion_gateway import SourceIngestionGateway
from magi.awareness.kg_write_queue import KnowledgeGraphWriteQueue
from magi.awareness.source_base import Source
from magi.awareness.source_store import source_object_identity
from magi.awareness.source_output import (
    ActivityFacet,
    ContentBlock,
    SourceActivity,
    SourceMemoryPolicy,
    SourceNarration,
    SourceOutputMetadata,
)
from magi.config import AppConfig
from magi.core.sqlite import sqlite_connection_async
from magi.events.in_memory_backend import InMemoryMessageBusBackend
from magi.memory.event_contracts import MemoryEvent
from magi.memory.clear_generation import ensure_memory_clear_state
from magi.memory.source_ingestion import SourceEventCommitter
from magi.timeline.handler import build_timeline_handler
from magi.timeline.subscribers.kg_subscriber import KGSubscriber


class _FakeL1Store:
    def __init__(self) -> None:
        self.timeline_events = []


class _FakeUnifiedMemory:
    def __init__(self, memory_db_path: Path) -> None:
        self.l1 = _FakeL1Store()
        self.edges: list[dict] = []
        self.epoch = 0
        self.memory_db_path = memory_db_path

    @asynccontextmanager
    async def memory_operation_guard(self):  # type: ignore[no-untyped-def]
        yield

    def memory_operation_epoch(self) -> int:
        return self.epoch

    async def ingest_event(  # type: ignore[no-untyped-def]
        self,
        event,
        *,
        expected_epoch,
    ) -> dict:
        assert expected_epoch == self.epoch
        self.l1.timeline_events.append(event)
        return {
            "event_id": event.event_id,
            "l1_written": True,
            "l1_confirmed": True,
        }

    async def upsert_user_graph_edge(self, **kwargs) -> None:
        self.edges.append(kwargs)


class _FakePhotoLibrarySource(Source):
    source_id = "timeline.photo_library"
    source_type = "photo_library"
    memory_policy = SourceMemoryPolicy(
        retention_class="compressible",
        cognition_eligible=True,
        importance_bias=0.6,
    )

    async def build_output(self, payload):
        source_item_id = str(payload["source_item_id"])
        summary = str(payload["summary"])
        return self._build_output(
            source_item_id=source_item_id,
            activity=SourceActivity(
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
            narration=SourceNarration(body=summary, title=str(payload["title"])),
            occurred_at=float(payload["timestamp"]),
            content_blocks=[ContentBlock(kind="text", value=summary)],
            tags=["photo_library"],
            domain_payload={"retention_mode": "retain_raw", "path": str(payload.get("path") or "")},
        )

    async def extract_metadata(self, payload):
        return SourceOutputMetadata(
            entities=[],
            tags=["photo_library"],
            relation_candidates=list(payload.get("relation_candidates", [])),
        )


class _FakeSourceRegistry:
    def __init__(self, tmp_path: Path) -> None:
        connection = PluginConnection(
            connection_id="photos-main", plugin_id="photo-library", display_name="Photos",
            enabled=True,
        )
        context = PluginContext(connection, tmp_path / "state", tmp_path / "resources", Mock())
        context.state_dir.mkdir(parents=True)
        context.resources_dir.mkdir(parents=True)
        self.source = _FakePhotoLibrarySource()
        self.source.bind_plugin_context(connection=connection, context=context)

    def resolve_source(self, source_type: str, *, connection_id: str):
        if source_type != "photo_library" or connection_id != "photos-main":
            return None
        return (
            "photo-library",
            "timeline.photo_library",
            self.source,
            SourceSpec(
                source_id="timeline.photo_library",
                display_name="Photos",
                domain="timeline",
                metadata={"default_settings": {"enabled": True, "edge_whitelist": ["LIKES"]}},
            ),
        )


class _FakePluginManager:
    def get_package(self, plugin_id: str):
        if plugin_id != "photo-library":
            return None
        return SimpleNamespace(manifest=SimpleNamespace(version="0.2.0"))


@pytest.mark.asyncio
async def test_runtime_timeline_handler_persists_photo_library_entry_and_user_graph_edges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The timeline handler commits memory before publishing graph projections."""
    monkeypatch.setattr(
        "magi.timeline.handler.get_runtime_paths",
        lambda: SimpleNamespace(runtime_dir=tmp_path),
    )
    memory = _FakeUnifiedMemory(tmp_path / "memory.db")
    async with sqlite_connection_async(memory.memory_db_path) as db:
        await ensure_memory_clear_state(db)
        await db.commit()
    bus = InMemoryMessageBusBackend()
    await bus.start()
    bus.bind_memory_operation_epoch(memory.memory_operation_epoch)

    kg_writer = KnowledgeGraphWriteQueue(unified_memory=memory)
    kg_sub = KGSubscriber(event_bus=bus, kg_writer=kg_writer)
    await kg_sub.start()

    gateway = SourceIngestionGateway(
        event_bus=bus,
        memory_committer=SourceEventCommitter(unified_memory=memory),
    )
    handler = build_timeline_handler(
        AppConfig(),
        memory,
        source_registry=_FakeSourceRegistry(tmp_path),
        plugin_manager=_FakePluginManager(),
        ingestion_gateway=gateway,
    )

    try:
        request = {
            "target_task_agent_id": "timeline-main",
            "connection_id": "photos-main",
            "source_type": "photo_library",
            "source_change": {
                "object_id": "photo-1",
                "version": "v1",
                "occurred_at": 1710000000.0,
                "payload": {
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
                },
            },
        }
        result = await handler(request)
        assert await handler(request) == result


        # Memory is already committed; let the bus finish graph projection.
        await asyncio.sleep(0.05)
        await kg_sub.drain()
    finally:
        await kg_sub.stop()
        await bus.stop()

    assert result["handled"] is True
    assert result["source_type"] == "photo_library"
    assert len(memory.l1.timeline_events) == 1
    stored = memory.l1.timeline_events[0]
    assert isinstance(stored, MemoryEvent)
    assert result["event_id"] == stored.event_id
    assert result["connection_id"] == "photos-main"
    metadata = stored.metadata_json
    assert metadata["source_id"] == "timeline.photo_library"
    assert metadata["source_connection_id"] == "photos-main"
    assert stored.idempotency_key == metadata["source_evidence_ref"]["resource_id"]
    assert stored.source_item_id == source_object_identity(
        "photos-main", "timeline.photo_library", "photo-1"
    )
    provenance = metadata["activity_snapshot"]["provenance"]
    assert provenance["source_id"] == "timeline.photo_library"
    assert provenance["source_connection_id"] == "photos-main"
    assert stored.source == "photo_library"
    # build_source_projection composes content as "<activity display prefix>
    # <narration body>", so the persisted L1 content carries the activity
    # prefix in front of the narration body.
    assert stored.content == "Photo Library Captured I still like Asuka best."
    assert "I still like Asuka best." in stored.content
    assert len(memory.edges) == 1
    assert memory.edges[0]["predicate"] == "LIKES"
