"""Tests for SensorIngestionGateway."""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.awareness.ingestion_gateway import SensorIngestionGateway
from magi.awareness.sensor_base import SensorBase
from magi.awareness.sensor_output import (
    ContentBlock,
    SensorMemoryPolicy,
    SensorOutput,
    SensorOutputMetadata,
)
from magi.awareness.sensor_state import SqliteSensorStateStore
from magi.memory.event_contracts import MemoryEvent
from magi.memory.event_contracts import MemoryDomain, IngestTarget, RetentionClass, TomDepth


class _FakeSensor(SensorBase):
    sensor_id = "test.fake"
    source_type = "fake_source"
    memory_event_type = "FAKE_EVENT"
    update_key_fields = ("id",)
    memory_policy = SensorMemoryPolicy(
        memory_domain="external_activity",
        ingest_target="l1_only",
        cognition_eligible=True,
        retention_class="permanent",
        importance_bias=0.7,
        author_type="external",
        content_type="observation",
    )

    async def build_output(self, item: dict[str, Any]) -> SensorOutput:
        return self._build_output(
            source_item_id=str(item["id"]),
            title="Fake title",
            summary="Fake summary",
        )


class _FakeBatchingSensor(_FakeSensor):
    def l2_batch_owner(self, output: SensorOutput) -> str | None:
        return f"{output.source_type}:default"

    def l2_batch_limits(self, output: SensorOutput) -> dict[str, int] | None:
        _ = output
        return {
            "max_events": 20,
            "max_estimated_tokens": 3200,
        }


def _make_output(**overrides: Any) -> SensorOutput:
    defaults = dict(
        source_type="fake_source",
        source_item_id="item-1",
        occurred_at=1700000000.0,
        captured_at=1700000001.0,
        title="Test Event",
        summary="Something happened",
        content_blocks=[ContentBlock(kind="text", value="hello")],
        tags=["tag1"],
    )
    defaults.update(overrides)
    return SensorOutput(**defaults)


class TestSensorIngestionGateway:
    @pytest.mark.asyncio
    async def test_ingest_calls_unified_memory(self):
        memory = MagicMock()
        memory.ingest_event = AsyncMock(return_value={"event_id": "evt-stored-1", "l1_written": True})
        memory.upsert_user_graph_edge = AsyncMock()
        gateway = SensorIngestionGateway(unified_memory=memory)
        sensor = _FakeSensor()
        output = _make_output()

        result = await gateway.ingest(sensor, output)

        assert result.event_id == "evt-stored-1"
        assert result.ingested is True
        memory.ingest_event.assert_awaited_once()

        # Verify the canonical MemoryEvent object was passed through unchanged
        call_args = memory.ingest_event.call_args[0][0]
        assert isinstance(call_args, MemoryEvent)
        assert call_args.event_id != "fake_source:item-1"
        assert call_args.event_type == "FAKE_EVENT"
        assert call_args.source == "fake_source"
        assert call_args.idempotency_key == "item-1"

    @pytest.mark.asyncio
    async def test_ingest_applies_memory_policy(self):
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        memory.upsert_user_graph_edge = AsyncMock()
        gateway = SensorIngestionGateway(unified_memory=memory)
        sensor = _FakeSensor()
        output = _make_output()

        await gateway.ingest(sensor, output)

        call_args = memory.ingest_event.call_args[0][0]
        assert isinstance(call_args, MemoryEvent)
        assert call_args.memory_domain == MemoryDomain.EXTERNAL_ACTIVITY
        assert call_args.ingest_target == IngestTarget.L1_ONLY
        assert call_args.retention_class == RetentionClass.PERMANENT
        assert call_args.importance_score == 0.7

    @pytest.mark.asyncio
    async def test_ingest_with_timeline_adapter(self):
        memory = MagicMock()
        memory.ingest_event = AsyncMock(return_value={"event_id": "evt-stored-2", "l1_written": True})
        memory.upsert_user_graph_edge = AsyncMock()
        adapter = MagicMock()
        adapter.on_sensor_output = AsyncMock()
        gateway = SensorIngestionGateway(
            unified_memory=memory,
            timeline_adapter=adapter,
        )
        sensor = _FakeSensor()
        output = _make_output()
        metadata = SensorOutputMetadata(tags=["extra"])

        await gateway.ingest(sensor, output, metadata)

        adapter.on_sensor_output.assert_awaited_once_with(
            "evt-stored-2", output, metadata,
        )

    @pytest.mark.asyncio
    async def test_ingest_no_adapter_is_ok(self):
        """Gateway works fine without a timeline adapter."""
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        gateway = SensorIngestionGateway(unified_memory=memory)
        sensor = _FakeSensor()
        output = _make_output()

        result = await gateway.ingest(sensor, output)
        assert result.ingested is True

    @pytest.mark.asyncio
    async def test_ingest_updates_state_store(self, tmp_path):
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        state_store = SqliteSensorStateStore(tmp_path / "state.db")
        gateway = SensorIngestionGateway(
            unified_memory=memory,
            sensor_state_store=state_store,
        )
        sensor = _FakeSensor()
        output = _make_output()

        await gateway.ingest(sensor, output)

        fps = await state_store.get_known_fingerprints("test.fake")
        assert len(fps) == 1

    @pytest.mark.asyncio
    async def test_ingest_processes_relations(self):
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        memory.upsert_user_graph_edge = AsyncMock()
        gateway = SensorIngestionGateway(unified_memory=memory)
        sensor = _FakeSensor()
        output = _make_output()
        metadata = SensorOutputMetadata(
            relation_candidates=[
                {
                    "predicate": "LIKES",
                    "object_id": "topic:test",
                    "confidence": 0.9,
                },
            ],
        )

        result = await gateway.ingest(
            sensor, output, metadata,
            allowed_edge_whitelist=["LIKES"],
        )
        assert result.stats["relation_count"] == 1
        memory.upsert_user_graph_edge.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ingest_skips_disallowed_relations(self):
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        memory.upsert_user_graph_edge = AsyncMock()
        gateway = SensorIngestionGateway(unified_memory=memory)
        sensor = _FakeSensor()
        output = _make_output()
        metadata = SensorOutputMetadata(
            relation_candidates=[
                {
                    "predicate": "LIKES",
                    "object_id": "topic:test",
                },
            ],
        )

        # No allowed edge whitelist → relations skipped
        result = await gateway.ingest(sensor, output, metadata)
        assert result.stats["relation_count"] == 0
        memory.upsert_user_graph_edge.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_content_fallback_to_content_blocks(self):
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        gateway = SensorIngestionGateway(unified_memory=memory)
        sensor = _FakeSensor()
        output = _make_output(title="", summary="", content_blocks=[ContentBlock(kind="text", value="block text")])

        await gateway.ingest(sensor, output)

        call_args = memory.ingest_event.call_args[0][0]
        assert isinstance(call_args, MemoryEvent)
        assert call_args.content == "block text"

    @pytest.mark.asyncio
    async def test_ingest_copies_domain_payload_to_memory_metadata(self):
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        gateway = SensorIngestionGateway(unified_memory=memory)
        sensor = _FakeSensor()
        output = _make_output(
            domain_payload={
                "bucket_start": "2026-03-27T10:00:00+08:00",
                "bundle_id": "com.apple.Safari",
                "duration_seconds": 2280,
            }
        )

        await gateway.ingest(sensor, output)

        call_args = memory.ingest_event.call_args[0][0]
        assert isinstance(call_args, MemoryEvent)
        assert call_args.metadata_json is not None
        assert call_args.metadata_json["bucket_start"] == "2026-03-27T10:00:00+08:00"
        assert call_args.metadata_json["bundle_id"] == "com.apple.Safari"
        assert call_args.metadata_json["duration_seconds"] == 2280
        assert call_args.metadata_json["timeline"] == {
            "event_id": call_args.event_id,
            "source_type": "fake_source",
            "source_item_id": "item-1",
            "occurred_at": 1700000000.0,
            "captured_at": 1700000001.0,
            "title": "Test Event",
            "summary": "Something happened",
            "retention_mode": "analyze_only",
            "raw_payload_ref": None,
            "content_blocks": [
                {
                    "kind": "text",
                    "value": "hello",
                    "mime_type": None,
                }
            ],
            "entities": [],
            "tags": ["tag1"],
            "privacy_labels": [],
            "processing_status": {"stored": True, "analyzed": False},
            "provenance": {},
        }
        assert call_args.metadata_json["processing_status"] == {"stored": True, "analyzed": False}

    @pytest.mark.asyncio
    async def test_ingest_adds_sensor_l2_batch_owner_to_memory_metadata(self):
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        gateway = SensorIngestionGateway(unified_memory=memory)
        sensor = _FakeBatchingSensor()
        output = _make_output()

        await gateway.ingest(sensor, output)

        call_args = memory.ingest_event.call_args[0][0]
        assert isinstance(call_args, MemoryEvent)
        assert call_args.metadata_json is not None
        assert call_args.metadata_json["l2_batch_owner"] == "fake_source:default"
        assert call_args.metadata_json["l2_batch_max_events"] == 20
        assert call_args.metadata_json["l2_batch_max_estimated_tokens"] == 3200
